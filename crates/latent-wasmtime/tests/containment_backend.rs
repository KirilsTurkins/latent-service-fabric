use std::env;
use std::fs;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use latent_activation::{ActivationEnvelope, ActivationManager, ActivationOutcome, TraceContext};
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
// Keep deadline fixtures comfortably below fuel exhaustion even on fast CI hosts.
const MAXIMUM_FUEL: u64 = 1_000_000_000_000;
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
    let factory = Phase0WasmtimeEngineFactory::new(config.clone()).expect("factory must build");
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
    let requested_deadline = Duration::from_millis(25);
    let deadline = now_unix_millis().saturating_add(
        u64::try_from(requested_deadline.as_millis()).expect("test duration fits u64"),
    );
    let deadline_started = Instant::now();
    let timed_out = invoke(
        &backend,
        prepared.clone(),
        deadline_id.clone(),
        INFINITE_MODE,
        budget(MAXIMUM_FUEL, 16 * 1024 * 1024, Some(deadline)),
        &TestCancellation::never(deadline_id),
    )
    .await;
    let deadline_elapsed = deadline_started.elapsed();
    assert_interrupted(timed_out, GuestInterruptionKind::DeadlineExceeded);
    assert_deadline_tolerance(deadline_elapsed, requested_deadline, &config);
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
    let granted_memory = 8 * 1024 * 1024;
    let memory = invoke(
        &backend,
        prepared.clone(),
        memory_id.clone(),
        MEMORY_MODE,
        budget(MAXIMUM_FUEL, granted_memory, None),
        &TestCancellation::never(memory_id),
    )
    .await;
    let memory_consumption = assert_interrupted(memory, GuestInterruptionKind::MemoryExhausted);
    assert!(
        memory_consumption.peak_memory_bytes <= granted_memory,
        "reported peak {} exceeded grant {granted_memory}",
        memory_consumption.peak_memory_bytes
    );
    assert_backend_reclaimed(&backend);
    assert_healthy_echo(&backend, &prepared, 5).await;

    for index in 0..24_u64 {
        let activation_id = ActivationId(format!("containment-repeat-{index}"));
        let outcome = invoke(
            &backend,
            prepared.clone(),
            activation_id.clone(),
            if index % 2 == 0 {
                TRAP_MODE
            } else {
                INFINITE_MODE
            },
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

fn assert_interrupted(
    outcome: GuestOutcome,
    expected: GuestInterruptionKind,
) -> latent_core::BudgetConsumption {
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
            consumption
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
    assert_eq!(snapshot.live_component_instances, 0);
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

fn budget(cpu_fuel: u64, memory_bytes: u64, deadline: Option<u64>) -> ResourceBudget {
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

const DELAYED_TRAP_MODE: &str = "__latent_test_delayed_trap";
const DELAYED_ECHO_PREFIX: &str = "__latent_test_delayed_echo:";
const DEADLINE_CI_SCHEDULING_ALLOWANCE_MILLIS: u64 = 500;

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
#[ignore = "requires the containment component built by tools/validate_contracts.sh"]
async fn healthy_activations_remain_correct_while_an_infinite_activation_times_out() {
    let (runner, pool, backend, config) = runner_fixture(5).await;
    let requested_deadline = Duration::from_millis(75);
    let deadline = now_unix_millis().saturating_add(
        u64::try_from(requested_deadline.as_millis()).expect("test duration fits u64"),
    );
    let failure_id = ActivationId("mixed-deadline-failure".to_owned());
    let failure = {
        let runner = Arc::clone(&runner);
        tokio::spawn(async move {
            let started = Instant::now();
            let outcome = runner
                .invoke(activation_envelope(
                    failure_id,
                    INFINITE_MODE,
                    budget(MAXIMUM_FUEL, 16 * 1024 * 1024, Some(deadline)),
                ))
                .await;
            (started.elapsed(), outcome)
        })
    };
    wait_for_runtime_active(&backend, 1).await;
    let healthy = spawn_mixed_healthy(&runner, "deadline", 4);
    wait_for_runtime_active(&backend, 2).await;

    let (elapsed, outcome) = tokio::time::timeout(Duration::from_secs(5), failure)
        .await
        .expect("deadline fixture terminates")
        .expect("deadline task joins");
    let consumption = assert_activation_failure(
        outcome,
        latent_core::ActivationTerminalState::DeadlineExceeded,
        latent_core::PlatformErrorCode::DeadlineExceeded,
        "activation.deadline-exceeded",
    );
    assert!(consumption.wall_time_micros > 0);
    assert_deadline_tolerance(elapsed, requested_deadline, &config);

    assert_mixed_healthy(healthy, &backend, "deadline").await;
    assert_end_to_end_reclaimed(&runner, &pool, &backend, 5);
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
#[ignore = "requires the containment component built by tools/validate_contracts.sh"]
async fn healthy_activations_remain_correct_while_another_activation_traps() {
    let (runner, pool, backend, _) = runner_fixture(5).await;
    let failure_id = ActivationId("mixed-trap-failure".to_owned());
    let failure = {
        let runner = Arc::clone(&runner);
        tokio::spawn(async move {
            runner
                .invoke(activation_envelope(
                    failure_id,
                    DELAYED_TRAP_MODE,
                    budget(MAXIMUM_FUEL, 16 * 1024 * 1024, None),
                ))
                .await
        })
    };
    wait_for_runtime_active(&backend, 1).await;
    let healthy = spawn_mixed_healthy(&runner, "trap", 4);
    wait_for_runtime_active(&backend, 2).await;

    let outcome = tokio::time::timeout(Duration::from_secs(5), failure)
        .await
        .expect("trap fixture terminates")
        .expect("trap task joins");
    assert_activation_failure(
        outcome,
        latent_core::ActivationTerminalState::GuestTrap,
        latent_core::PlatformErrorCode::GuestTrap,
        "activation.guest-trap",
    );
    assert_mixed_healthy(healthy, &backend, "trap").await;
    assert_end_to_end_reclaimed(&runner, &pool, &backend, 5);
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
#[ignore = "requires the containment component built by tools/validate_contracts.sh"]
async fn memory_pressure_stays_within_the_grant_while_healthy_activations_complete() {
    let (runner, pool, backend, _) = runner_fixture(5).await;
    let granted_memory = 8 * 1024 * 1024;
    let failure_id = ActivationId("mixed-memory-failure".to_owned());
    let failure = {
        let runner = Arc::clone(&runner);
        tokio::spawn(async move {
            runner
                .invoke(activation_envelope(
                    failure_id,
                    MEMORY_MODE,
                    budget(MAXIMUM_FUEL, granted_memory, None),
                ))
                .await
        })
    };
    wait_for_runtime_active(&backend, 1).await;
    let healthy = spawn_mixed_healthy(&runner, "memory", 4);
    wait_for_runtime_active(&backend, 2).await;

    let outcome = tokio::time::timeout(Duration::from_secs(5), failure)
        .await
        .expect("memory fixture terminates")
        .expect("memory task joins");
    let consumption = assert_activation_failure(
        outcome,
        latent_core::ActivationTerminalState::ResourceExhausted,
        latent_core::PlatformErrorCode::ResourceExhausted,
        "activation.memory-exhausted",
    );
    assert!(
        consumption.peak_memory_bytes <= granted_memory,
        "reported peak {} exceeded grant {granted_memory}",
        consumption.peak_memory_bytes
    );
    assert_mixed_healthy(healthy, &backend, "memory").await;
    assert_end_to_end_reclaimed(&runner, &pool, &backend, 5);
}

async fn runner_fixture(
    capacity: u32,
) -> (
    Arc<latent_node::Phase0ActivationRunner>,
    latent_scheduler::FixedCellPool,
    Arc<Phase0WasmtimeBackend>,
    Phase0WasmtimeConfig,
) {
    let artifact = load_containment_artifact();
    let config = Phase0WasmtimeConfig {
        maximum_memory_bytes: MAXIMUM_MEMORY_BYTES,
        maximum_fuel: MAXIMUM_FUEL,
        epoch_tick_interval_millis: 1,
        prepared_cache_maximum_entries: 2,
        ..Phase0WasmtimeConfig::default()
    };
    let factory = Phase0WasmtimeEngineFactory::new(config.clone()).expect("factory must build");
    let backend = Arc::new(factory.create_backend_instance());
    let key = factory.preparation_key(artifact.descriptor.release_digest.clone());
    let prepared = backend
        .prepare(&artifact, &key)
        .await
        .expect("containment fixture must prepare");
    let pool = latent_scheduler::FixedCellPool::new(latent_scheduler::FixedCellPoolConfig::new(
        NodeId("mixed-containment-node".to_owned()),
        latent_scheduler::CellClass::Standard,
        capacity,
        32,
    ))
    .expect("mixed containment pool is valid");
    let runner_pool: Arc<dyn latent_scheduler::CellPool> = Arc::new(pool.clone());
    let runner_backend: Arc<dyn ExecutionBackend> = backend.clone();
    let runner = Arc::new(
        latent_node::Phase0ActivationRunner::new(
            latent_node::Phase0ActivationRunnerConfig::default(),
            runner_pool,
            runner_backend,
            prepared,
            bound_imports(),
        )
        .expect("mixed containment runner is valid"),
    );
    (runner, pool, backend, config)
}

fn spawn_mixed_healthy(
    runner: &Arc<latent_node::Phase0ActivationRunner>,
    suite: &str,
    count: u64,
) -> Vec<(
    ActivationId,
    String,
    tokio::task::JoinHandle<ActivationOutcome>,
)> {
    (0..count)
        .map(|index| {
            let activation_id = ActivationId(format!("mixed-{suite}-healthy-{index}"));
            let expected = format!("{suite}-healthy-output-{index}");
            let input = format!("{DELAYED_ECHO_PREFIX}{expected}");
            let runner = Arc::clone(runner);
            let task_activation_id = activation_id.clone();
            let task = tokio::spawn(async move {
                runner
                    .invoke(activation_envelope(
                        task_activation_id,
                        &input,
                        budget(MAXIMUM_FUEL, 16 * 1024 * 1024, None),
                    ))
                    .await
            });
            (activation_id, expected, task)
        })
        .collect()
}

async fn assert_mixed_healthy(
    tasks: Vec<(
        ActivationId,
        String,
        tokio::task::JoinHandle<ActivationOutcome>,
    )>,
    backend: &Phase0WasmtimeBackend,
    suite: &str,
) {
    for (activation_id, expected, task) in tasks {
        let outcome = tokio::time::timeout(Duration::from_secs(5), task)
            .await
            .unwrap_or_else(|_| panic!("{suite} healthy invocation timed out"))
            .expect("healthy task joins");
        match outcome {
            ActivationOutcome::Succeeded(success) => {
                assert_eq!(success.output, expected.as_bytes());
                assert_eq!(success.output_media_type, ECHO_SUCCESS_MEDIA_TYPE);
            }
            ActivationOutcome::Failed { error, .. } => {
                panic!("{suite} healthy activation failed: {error:?}");
            }
        }
        let logs = backend.log_sink().snapshot_for(&activation_id);
        assert_eq!(logs.len(), 1, "healthy activation has one isolated log");
        assert_eq!(
            logs[0].fields.get("activation_id"),
            Some(&activation_id.0),
            "host context must remain activation-local"
        );
    }
}

fn activation_envelope(
    activation_id: ActivationId,
    message: &str,
    budget: ResourceBudget,
) -> ActivationEnvelope {
    let deadline = budget.wall_deadline_unix_millis;
    ActivationEnvelope {
        activation_id: activation_id.clone(),
        parent_activation_id: None,
        root_activation_id: activation_id.clone(),
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
            trace_id: TraceId(format!("trace-{}", activation_id.0)),
            span_id: SpanId(format!("span-{}", activation_id.0)),
            trace_flags: 1,
            baggage: Metadata::from([("suite".to_owned(), "issue-22-mixed".to_owned())]),
        },
        idempotency_key: None,
        retry_attempt: 0,
        budget,
        metadata: Metadata::new(),
        input: message.as_bytes().to_vec(),
        input_media_type: ECHO_SUCCESS_MEDIA_TYPE.to_owned(),
    }
}

fn bound_imports() -> Vec<BoundImport> {
    vec![
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
    ]
}

fn assert_activation_failure(
    outcome: ActivationOutcome,
    terminal_state: latent_core::ActivationTerminalState,
    code: latent_core::PlatformErrorCode,
    detail_kind: &str,
) -> latent_core::BudgetConsumption {
    match outcome {
        ActivationOutcome::Failed {
            terminal_state: actual_terminal_state,
            error,
            consumption,
        } => {
            assert_eq!(actual_terminal_state, terminal_state);
            assert_eq!(error.code, code);
            assert!(!error.retryable);
            assert!(error.message.len() <= 512);
            assert_eq!(error.details.len(), 1);
            assert_eq!(error.details[0].kind, detail_kind);
            assert!(error.details[0]
                .fields
                .iter()
                .all(|(name, value)| name.len() <= 64 && value.len() <= 256));
            consumption
        }
        ActivationOutcome::Succeeded(success) => {
            panic!("expected failure, got output {:?}", success.output);
        }
    }
}

fn assert_deadline_tolerance(
    elapsed: Duration,
    requested_deadline: Duration,
    config: &Phase0WasmtimeConfig,
) {
    let containment_tolerance = Duration::from_millis(
        config
            .epoch_tick_interval_millis
            .saturating_mul(config.epoch_deadline_ticks),
    );
    let maximum_elapsed = requested_deadline
        .saturating_add(containment_tolerance)
        .saturating_add(Duration::from_millis(
            DEADLINE_CI_SCHEDULING_ALLOWANCE_MILLIS,
        ));
    assert!(
        elapsed <= maximum_elapsed,
        "deadline interruption took {elapsed:?}, exceeding {maximum_elapsed:?}"
    );
}

async fn wait_for_runtime_active(backend: &Phase0WasmtimeBackend, minimum: u64) {
    tokio::time::timeout(Duration::from_secs(2), async {
        while backend.resource_snapshot().active_invocations < minimum {
            // Give the spawned blocking guest invocation a scheduling window;
            // a yield-only polling loop can otherwise monopolize an executor
            // worker while the parallel test suite is under load.
            tokio::time::sleep(Duration::from_millis(1)).await;
        }
    })
    .await
    .unwrap_or_else(|_| panic!("runtime never reached {minimum} concurrent invocations"));
}

fn assert_end_to_end_reclaimed(
    runner: &latent_node::Phase0ActivationRunner,
    pool: &latent_scheduler::FixedCellPool,
    backend: &Phase0WasmtimeBackend,
    capacity: u32,
) {
    let runner_snapshot = runner.snapshot();
    assert_eq!(runner_snapshot.active_cancellation_registrations, 0);
    assert_eq!(runner_snapshot.running_invocations, 0);
    assert_eq!(runner_snapshot.disposition_failures, 0);
    assert_eq!(runner_snapshot.quarantined_cells, 0);
    assert_eq!(
        runner_snapshot.released_cells, runner_snapshot.total_invocations,
        "every terminal path must release its affine lease exactly once"
    );

    let runtime = backend.resource_snapshot();
    assert_eq!(runtime.active_invocations, 0);
    assert_eq!(runtime.live_stores, 0);
    assert_eq!(runtime.live_host_states, 0);
    assert_eq!(runtime.live_component_instances, 0);
    assert_eq!(runtime.live_temporary_buffers, 0);
    assert_eq!(runtime.live_cancellation_probes, 0);

    let cache = backend.cache_snapshot();
    assert_eq!(cache.entries, 1);
    assert!(cache.entries <= cache.maximum_entries);
    assert!(cache.source_bytes <= cache.maximum_source_bytes);

    let observations = pool.observations();
    assert_eq!(observations.capacity, capacity);
    assert_eq!(observations.available, capacity);
    assert_eq!(observations.active_leases, 0);
    assert_eq!(observations.queue_depth, 0);
    assert_eq!(observations.quarantined, 0);
    assert_eq!(
        observations.available + observations.active_leases + observations.quarantined,
        observations.capacity
    );
}
