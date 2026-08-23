use std::env;
use std::fs;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use latent_activation::{ActivationEnvelope, TraceContext};
use latent_artifacts::{ArtifactDescriptor, CapsuleArtifact};
use latent_core::{
    ActivationId, ArtifactReference, CapabilityId, CellId, ContractId, FunctionId,
    InvocationPrincipal, Metadata, NodeId, PrincipalKind, ReleaseDigest, ResourceBudget, ServiceId,
    SpanId, TenantId, TraceId,
};
use latent_executor::{
    BoundImport, ExecutionBackend, ExecutionCancellation, ExecutionCancellationProbe,
    ExecutionCell, ExecutionRequest, GuestInterruptionKind, GuestOutcome, PreparedComponent,
};
use latent_manifest::{
    CapsuleManifest, ContractExport, ContractImport, ExecutionBackendKind, ExecutionRequirements,
    ObjectMetadata, StateModel, ThreadingModel,
};
use latent_routing::InvocationTarget;
use latent_wasmtime::{
    Phase0WasmtimeBackend, Phase0WasmtimeConfig, Phase0WasmtimeEngineFactory, CONTEXT_IMPORT,
    ECHO_EXPORT, ECHO_SUCCESS_MEDIA_TYPE, ECHO_WORLD, LOG_IMPORT,
};
use sha2::{Digest, Sha256};

const TRAP_MODE: &str = "__latent_test_trap";
const INFINITE_MODE: &str = "__latent_test_infinite";
const MEMORY_MODE: &str = "__latent_test_memory";
const MAXIMUM_FUEL: u64 = 100_000_000;
const MAXIMUM_MEMORY_BYTES: u64 = 32 * 1024 * 1024;

#[derive(Default)]
struct CancellationState {
    cancelled: AtomicBool,
    reason: Mutex<Option<String>>,
}

impl CancellationState {
    fn cancel(&self, reason: &str) {
        *self
            .reason
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner) = Some(reason.to_owned());
        self.cancelled.store(true, Ordering::Release);
    }
}

impl ExecutionCancellationProbe for CancellationState {
    fn is_cancelled(&self) -> bool {
        self.cancelled.load(Ordering::Acquire)
    }

    fn reason(&self) -> Option<String> {
        self.reason
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .clone()
    }
}

struct TestCancellation {
    activation_id: ActivationId,
    state: Arc<CancellationState>,
}

impl TestCancellation {
    fn never(activation_id: ActivationId) -> Self {
        Self {
            activation_id,
            state: Arc::new(CancellationState::default()),
        }
    }
}

impl ExecutionCancellation for TestCancellation {
    fn activation_id(&self) -> &ActivationId {
        &self.activation_id
    }

    fn is_cancelled(&self) -> bool {
        self.state.is_cancelled()
    }

    fn reason(&self) -> Option<String> {
        self.state.reason()
    }

    fn probe(&self) -> Option<Arc<dyn ExecutionCancellationProbe>> {
        Some(self.state.clone())
    }
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires the containment component built by tools/validate_contracts.sh"]
async fn contains_real_component_failures_and_reclaims_every_invocation_resource() {
    let artifact = load_containment_artifact();
    let config = Phase0WasmtimeConfig {
        maximum_memory_bytes: MAXIMUM_MEMORY_BYTES,
        maximum_fuel: MAXIMUM_FUEL,
        epoch_tick_interval_millis: 1,
        prepared_cache_maximum_entries: 2,
        ..Phase0WasmtimeConfig::default()
    };
    let factory = Phase0WasmtimeEngineFactory::new(config).expect("factory must build");
    let backend = factory.create_backend_instance();
    let key = factory.preparation_key(artifact.descriptor.release_digest.clone());
    let prepared = backend
        .prepare(&artifact, &key)
        .await
        .expect("containment fixture must prepare");

    let trap_id = ActivationId("containment-trap".to_owned());
    let trap = invoke(
        &backend,
        prepared.clone(),
        trap_id.clone(),
        TRAP_MODE,
        budget(MAXIMUM_FUEL, 16 * 1024 * 1024, None),
        &TestCancellation::never(trap_id),
    )
    .await;
    match trap {
        GuestOutcome::Trapped { trap, .. } => {
            assert_eq!(trap.code, "guest-trap");
            assert!(trap.message.len() <= 512);
            assert!(trap.guest_backtrace.is_empty());
        }
        other => panic!("controlled trap must be classified as a guest trap: {other:?}"),
    }
    assert_backend_reclaimed(&backend);
    assert_healthy_echo(&backend, &prepared, 1).await;

    let fuel_id = ActivationId("containment-fuel".to_owned());
    let fuel = invoke(
        &backend,
        prepared.clone(),
        fuel_id.clone(),
        INFINITE_MODE,
        budget(2_000, 16 * 1024 * 1024, None),
        &TestCancellation::never(fuel_id),
    )
    .await;
    assert_interrupted(fuel, GuestInterruptionKind::FuelExhausted);
    assert_backend_reclaimed(&backend);
    assert_healthy_echo(&backend, &prepared, 2).await;

    let deadline_id = ActivationId("containment-deadline".to_owned());
    let deadline = now_unix_millis().saturating_add(25);
    let timed_out = invoke(
        &backend,
        prepared.clone(),
        deadline_id.clone(),
        INFINITE_MODE,
        budget(MAXIMUM_FUEL, 16 * 1024 * 1024, Some(deadline)),
        &TestCancellation::never(deadline_id),
    )
    .await;
    assert_interrupted(timed_out, GuestInterruptionKind::DeadlineExceeded);
    assert_backend_reclaimed(&backend);
    assert_healthy_echo(&backend, &prepared, 3).await;

    let cancellation_id = ActivationId("containment-cancel".to_owned());
    let cancellation = TestCancellation::never(cancellation_id.clone());
    let cancellation_state = Arc::clone(&cancellation.state);
    let request = request(
        prepared.clone(),
        cancellation_id,
        INFINITE_MODE,
        budget(MAXIMUM_FUEL, 16 * 1024 * 1024, None),
    );
    let invocation = backend.invoke(request, &cancellation);
    let cancel = async move {
        tokio::time::sleep(Duration::from_millis(5)).await;
        cancellation_state.cancel("controlled running cancellation");
    };
    let (cancelled, ()) = tokio::join!(invocation, cancel);
    assert_interrupted(
        cancelled.expect("running cancellation remains a guest outcome"),
        GuestInterruptionKind::Cancelled,
    );
    assert_backend_reclaimed(&backend);
    assert_healthy_echo(&backend, &prepared, 4).await;

    let memory_id = ActivationId("containment-memory".to_owned());
    let memory = invoke(
        &backend,
        prepared.clone(),
        memory_id.clone(),
        MEMORY_MODE,
        budget(MAXIMUM_FUEL, 8 * 1024 * 1024, None),
        &TestCancellation::never(memory_id),
    )
    .await;
    assert_interrupted(memory, GuestInterruptionKind::MemoryExhausted);
    assert_backend_reclaimed(&backend);
    assert_healthy_echo(&backend, &prepared, 5).await;

    for index in 0..24_u64 {
        let activation_id = ActivationId(format!("containment-repeat-{index}"));
        let outcome = invoke(
            &backend,
            prepared.clone(),
            activation_id.clone(),
            if index % 2 == 0 { TRAP_MODE } else { INFINITE_MODE },
            if index % 2 == 0 {
                budget(MAXIMUM_FUEL, 16 * 1024 * 1024, None)
            } else {
                budget(2_000, 16 * 1024 * 1024, None)
            },
            &TestCancellation::never(activation_id),
        )
        .await;
        assert!(matches!(
            outcome,
            GuestOutcome::Trapped { .. } | GuestOutcome::Interrupted { .. }
        ));
        assert_backend_reclaimed(&backend);
    }

    let concurrent_a = concurrent_echo(&backend, prepared.clone(), 10, "alpha");
    let concurrent_b = concurrent_echo(&backend, prepared.clone(), 11, "beta");
    let concurrent_c = concurrent_echo(&backend, prepared.clone(), 12, "gamma");
    let concurrent_d = concurrent_echo(&backend, prepared, 13, "delta");
    let (a, b, c, d) = tokio::join!(concurrent_a, concurrent_b, concurrent_c, concurrent_d);
    assert_returned(a, b"alpha");
    assert_returned(b, b"beta");
    assert_returned(c, b"gamma");
    assert_returned(d, b"delta");
    assert_backend_reclaimed(&backend);
    assert_eq!(backend.cache_snapshot().entries, 1);
}

async fn concurrent_echo(
    backend: &Phase0WasmtimeBackend,
    prepared: PreparedComponent,
    index: u64,
    message: &str,
) -> GuestOutcome {
    let activation_id = ActivationId(format!("containment-concurrent-{index}"));
    invoke(
        backend,
        prepared,
        activation_id.clone(),
        message,
        budget(MAXIMUM_FUEL, 16 * 1024 * 1024, None),
        &TestCancellation::never(activation_id),
    )
    .await
}

async fn assert_healthy_echo(
    backend: &Phase0WasmtimeBackend,
    prepared: &PreparedComponent,
    index: u64,
) {
    let message = format!("healthy-after-failure-{index}");
    let activation_id = ActivationId(format!("containment-healthy-{index}"));
    let outcome = invoke(
        backend,
        prepared.clone(),
        activation_id.clone(),
        &message,
        budget(MAXIMUM_FUEL, 16 * 1024 * 1024, None),
        &TestCancellation::never(activation_id),
    )
    .await;
    assert_returned(outcome, message.as_bytes());
    assert_backend_reclaimed(backend);
}

async fn invoke(
    backend: &Phase0WasmtimeBackend,
    prepared: PreparedComponent,
    activation_id: ActivationId,
    message: &str,
    budget: ResourceBudget,
    cancellation: &dyn ExecutionCancellation,
) -> GuestOutcome {
    tokio::time::timeout(
        Duration::from_secs(5),
        backend.invoke(
            request(prepared, activation_id, message, budget),
            cancellation,
        ),
    )
    .await
    .expect("contained invocation must terminate")
    .expect("controlled failure remains an execution outcome")
}

fn assert_interrupted(outcome: GuestOutcome, expected: GuestInterruptionKind) {
    match outcome {
        GuestOutcome::Interrupted {
            kind,
            reason,
            consumption,
        } => {
            assert_eq!(kind, expected);
            assert!(!reason.is_empty());
            assert!(reason.len() <= 512);
            assert!(consumption.wall_time_micros > 0);
        }
        other => panic!("expected {expected:?}, got {other:?}"),
    }
}

fn assert_returned(outcome: GuestOutcome, expected: &[u8]) {
    match outcome {
        GuestOutcome::Returned {
            output,
            output_media_type,
            ..
        } => {
            assert_eq!(output, expected);
            assert_eq!(output_media_type, ECHO_SUCCESS_MEDIA_TYPE);
        }
        other => panic!("expected a healthy echo, got {other:?}"),
    }
}

fn assert_backend_reclaimed(backend: &Phase0WasmtimeBackend) {
    let snapshot = backend.resource_snapshot();
    assert_eq!(snapshot.active_invocations, 0);
    assert_eq!(snapshot.live_stores, 0);
    assert_eq!(snapshot.live_host_states, 0);
    assert_eq!(snapshot.live_temporary_buffers, 0);
    assert_eq!(snapshot.live_cancellation_probes, 0);
}

fn load_containment_artifact() -> CapsuleArtifact {
    let component_path = required_env_path("LSF_CONTAINMENT_COMPONENT");
    let component_bytes = fs::read(&component_path)
        .expect("LSF_CONTAINMENT_COMPONENT must identify a readable component");
    let digest = ReleaseDigest(component_digest(&component_bytes));
    let budget = budget(MAXIMUM_FUEL, MAXIMUM_MEMORY_BYTES, None);
    let manifest = CapsuleManifest {
        api_version: "latent.dev/v1alpha1".to_owned(),
        metadata: ObjectMetadata {
            name: "containment-capsule".to_owned(),
            tenant: Some(TenantId("examples".to_owned())),
            namespace: Some("default".to_owned()),
            labels: Metadata::new(),
            annotations: Metadata::from([(
                "latent.dev/test-fixture".to_owned(),
                "issue-22".to_owned(),
            )]),
        },
        semantic_version: "0.1.0".to_owned(),
        component_digest: digest.clone(),
        world: ContractId(ECHO_WORLD.to_owned()),
        exports: vec![ContractExport {
            contract: ContractId(ECHO_EXPORT.to_owned()),
        }],
        imports: vec![
            ContractImport {
                contract: ContractId(CONTEXT_IMPORT.to_owned()),
                optional: false,
            },
            ContractImport {
                contract: ContractId(LOG_IMPORT.to_owned()),
                optional: false,
            },
        ],
        execution: ExecutionRequirements {
            backend: ExecutionBackendKind::WasmComponent,
            threading: ThreadingModel::SingleThreaded,
            state_model: StateModel::Stateless,
            resource_budget_ceiling: budget,
            host_call_depth_maximum: 8,
            component_call_depth_maximum: 8,
            snapshot_eligible: false,
            fusion_eligible: false,
        },
        minimum_fabric_version: "0.1.0-alpha.0".to_owned(),
    };

    CapsuleArtifact {
        descriptor: ArtifactDescriptor {
            reference: ArtifactReference(format!("file://{}", component_path.display())),
            release_digest: digest,
            media_type: "application/vnd.wasm.component.v1+wasm".to_owned(),
            size_bytes: u64::try_from(component_bytes.len()).expect("component size fits u64"),
            publisher: None,
            layers: Vec::new(),
            annotations: manifest.metadata.annotations.clone(),
        },
        manifest,
        contracts: Vec::new(),
        component_bytes,
    }
}

fn request(
    prepared: PreparedComponent,
    activation_id: ActivationId,
    message: &str,
    budget: ResourceBudget,
) -> ExecutionRequest {
    let deadline = budget.wall_deadline_unix_millis;
    ExecutionRequest {
        activation: ActivationEnvelope {
            activation_id: activation_id.clone(),
            parent_activation_id: None,
            root_activation_id: activation_id,
            principal: InvocationPrincipal {
                subject: "containment-test".to_owned(),
                kind: PrincipalKind::Service,
                tenant: Some(TenantId("examples".to_owned())),
                service: Some(ServiceId("containment".to_owned())),
                claims: Metadata::new(),
            },
            target: InvocationTarget {
                tenant: TenantId("examples".to_owned()),
                service: ServiceId("echo".to_owned()),
                contract: ContractId(ECHO_EXPORT.to_owned()),
                function: FunctionId("echo".to_owned()),
                route: None,
            },
            resolved_revision: None,
            deadline_unix_millis: deadline,
            priority: 0,
            trace: TraceContext {
                trace_id: TraceId("trace-containment".to_owned()),
                span_id: SpanId("span-containment".to_owned()),
                trace_flags: 1,
                baggage: Metadata::from([("suite".to_owned(), "issue-22".to_owned())]),
            },
            idempotency_key: None,
            retry_attempt: 0,
            budget: budget.clone(),
            metadata: Metadata::new(),
            input: message.as_bytes().to_vec(),
            input_media_type: ECHO_SUCCESS_MEDIA_TYPE.to_owned(),
        },
        prepared,
        cell: ExecutionCell {
            id: CellId("containment-cell".to_owned()),
            class: "standard".to_owned(),
            maximum_memory_bytes: budget.memory_bytes,
            metadata: Metadata::from([("node".to_owned(), NodeId("node-test".to_owned()).0)]),
        },
        imports: vec![
            BoundImport {
                capability: CapabilityId("context".to_owned()),
                contract: CONTEXT_IMPORT.to_owned(),
                opaque_handle: "activation-context".to_owned(),
            },
            BoundImport {
                capability: CapabilityId("log".to_owned()),
                contract: LOG_IMPORT.to_owned(),
                opaque_handle: "bounded-log".to_owned(),
            },
        ],
        budget,
    }
}

fn budget(
    cpu_fuel: u64,
    memory_bytes: u64,
    deadline: Option<u64>,
) -> ResourceBudget {
    ResourceBudget {
        cpu_fuel,
        memory_bytes,
        wall_deadline_unix_millis: deadline,
        child_calls: 0,
        outbound_requests: 0,
        state_read_bytes: 0,
        state_write_bytes: 0,
        blob_read_bytes: 0,
        blob_write_bytes: 0,
        log_bytes: 16 * 1024,
        effect_count: 0,
    }
}

fn required_env_path(name: &str) -> PathBuf {
    env::var_os(name)
        .map(PathBuf::from)
        .unwrap_or_else(|| panic!("{name} must be set by the contract validation gate"))
}

fn component_digest(bytes: &[u8]) -> String {
    let digest = Sha256::digest(bytes);
    format!(
        "sha256:{}",
        digest
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect::<String>()
    )
}

fn now_unix_millis() -> u64 {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis();
    u64::try_from(millis).unwrap_or(u64::MAX)
}
