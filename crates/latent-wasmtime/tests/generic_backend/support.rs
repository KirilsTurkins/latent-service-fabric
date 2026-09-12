use std::fs;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use latent_activation::{ActivationEnvelope, TraceContext};
use latent_artifacts::{ArtifactDescriptor, CapsuleArtifact};
use latent_core::{
    ActivationId, ArtifactReference, CellId, ContractId, FunctionId, InvocationPrincipal, Metadata,
    PlatformError, PrincipalKind, ReleaseDigest, ResourceBudget, ServiceId, SpanId, TenantId,
    TraceId,
};
use latent_executor::{
    ExecutionBackend, ExecutionCancellation, ExecutionCancellationProbe, ExecutionCell,
    ExecutionCleanup, ExecutionRequest, GuestOutcome, PreparedComponent,
};
use latent_manifest::{
    CapsuleManifest, ContractExport, ExecutionBackendKind, ExecutionRequirements, ObjectMetadata,
    StateModel, ThreadingModel,
};
use latent_routing::InvocationTarget;
use latent_wasmtime::{WasmtimeBackend, WasmtimeComponentEngineFactory, WasmtimeConfig};
use serde_json::Value;
use sha2::{Digest, Sha256};

pub const MEDIA: &str = "application/vnd.latent.wit-values.v1+json";
pub const VALUES: &str = "tests:generic/values@0.1.0";
pub const ALTERNATE: &str = "tests:generic/alternate@0.1.0";
pub const ADVERSARIAL: &str = "tests:adversarial/api@0.1.0";
pub const MAX_FUEL: u64 = 1_000_000_000_000;
pub const MEMORY: u64 = 16 * 1024 * 1024;
pub const WATCHDOG: Duration = Duration::from_secs(5);

#[derive(Default)]
pub struct CancellationState(AtomicBool);

impl ExecutionCancellationProbe for CancellationState {
    fn is_cancelled(&self) -> bool {
        self.0.load(Ordering::Acquire)
    }

    fn reason(&self) -> Option<String> {
        self.is_cancelled()
            .then(|| "controlled generic cancellation".to_owned())
    }
}

pub struct Cancellation {
    pub id: ActivationId,
    pub state: Arc<CancellationState>,
    pub deadline: Option<latent_core::EffectiveDeadline>,
}

impl Cancellation {
    pub fn new(id: &str) -> Self {
        Self {
            id: ActivationId(id.to_owned()),
            state: Arc::default(),
            deadline: None,
        }
    }

    pub fn cancel(&self) {
        self.state.0.store(true, Ordering::Release);
    }
}

impl ExecutionCancellation for Cancellation {
    fn activation_id(&self) -> &ActivationId {
        &self.id
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

    fn effective_deadline(&self) -> Option<&latent_core::EffectiveDeadline> {
        self.deadline.as_ref()
    }
}

pub fn config() -> WasmtimeConfig {
    WasmtimeConfig {
        maximum_memory_bytes: MEMORY,
        maximum_fuel: MAX_FUEL,
        epoch_tick_interval_millis: 1,
        prepared_cache_maximum_entries: 2,
        ..WasmtimeConfig::default()
    }
}

pub fn budget() -> ResourceBudget {
    ResourceBudget {
        cpu_fuel: MAX_FUEL,
        memory_bytes: MEMORY,
        wall_time_limit_millis: None,
        child_calls: 0,
        outbound_requests: 0,
        state_read_bytes: 0,
        state_write_bytes: 0,
        blob_read_bytes: 0,
        blob_write_bytes: 0,
        log_bytes: 0,
        effect_count: 0,
    }
}

pub fn artifact() -> CapsuleArtifact {
    artifact_bytes(
        fs::read(required_path("LSF_GENERIC_COMPONENT")).expect("generic component"),
        &[VALUES, ALTERNATE],
    )
}

pub fn adversarial(name: &str) -> CapsuleArtifact {
    artifact_bytes(
        fs::read(required_path("LSF_GENERIC_FIXTURES").join(format!("{name}.wasm")))
            .expect("adversarial component"),
        &[ADVERSARIAL],
    )
}

pub fn artifact_bytes(component_bytes: Vec<u8>, exports: &[&str]) -> CapsuleArtifact {
    let digest = ReleaseDigest(format!("sha256:{:x}", Sha256::digest(&component_bytes)));
    let manifest = CapsuleManifest {
        api_version: "latent.dev/v1alpha1".to_owned(),
        metadata: ObjectMetadata {
            name: "generic-capsule".to_owned(),
            tenant: Some(TenantId("tests".to_owned())),
            namespace: None,
            labels: Metadata::new(),
            annotations: Metadata::new(),
        },
        semantic_version: "0.1.0".to_owned(),
        component_digest: digest.clone(),
        world: ContractId("tests:generic/service@0.1.0".to_owned()),
        exports: exports
            .iter()
            .map(|name| ContractExport {
                contract: ContractId((*name).to_owned()),
            })
            .collect(),
        imports: Vec::new(),
        execution: ExecutionRequirements {
            backend: ExecutionBackendKind::WasmComponent,
            threading: ThreadingModel::SingleThreaded,
            state_model: StateModel::Stateless,
            resource_budget_ceiling: budget(),
            host_call_depth_maximum: 8,
            component_call_depth_maximum: 8,
            snapshot_eligible: false,
            fusion_eligible: false,
        },
        minimum_fabric_version: "0.1.0-alpha.0".to_owned(),
        runtime_requirements: Default::default(),
    };
    CapsuleArtifact {
        descriptor: ArtifactDescriptor {
            reference: ArtifactReference("local://generic-fixture".to_owned()),
            release_digest: digest,
            media_type: "application/vnd.wasm.component.v1+wasm".to_owned(),
            size_bytes: u64::try_from(component_bytes.len()).expect("fixture size fits"),
            publisher: None,
            layers: Vec::new(),
            annotations: Metadata::new(),
        },
        manifest,
        contracts: Vec::new(),
        component_bytes,
    }
}

pub async fn prepared(config: WasmtimeConfig) -> (WasmtimeBackend, PreparedComponent) {
    let factory = WasmtimeComponentEngineFactory::new(config).expect("factory");
    let backend = factory.create_backend_instance();
    let artifact = artifact();
    let prepared = backend
        .prepare(
            &artifact,
            &factory.preparation_key(artifact.descriptor.release_digest.clone()),
        )
        .await
        .expect("generic fixture prepares without imports");
    assert_eq!(backend.resource_snapshot().stores_created, 0);
    (backend, prepared)
}

pub fn request(
    prepared: PreparedComponent,
    id: &ActivationId,
    contract: &str,
    function: &str,
    input: &[u8],
    budget: ResourceBudget,
) -> ExecutionRequest {
    let deadline = ResourceBudget::effective_deadline_unix_millis(now_millis(), None, [&budget]);
    ExecutionRequest {
        activation: ActivationEnvelope {
            activation_id: id.clone(),
            root_activation_id: id.clone(),
            parent_activation_id: None,
            principal: InvocationPrincipal {
                subject: "generic-test".to_owned(),
                kind: PrincipalKind::Service,
                tenant: Some(TenantId("tests".to_owned())),
                service: Some(ServiceId("generic".to_owned())),
                claims: Metadata::new(),
            },
            target: InvocationTarget {
                tenant: TenantId("tests".to_owned()),
                service: ServiceId("generic".to_owned()),
                contract: ContractId(contract.to_owned()),
                function: FunctionId(function.to_owned()),
                route: None,
            },
            resolved_revision: None,
            deadline_unix_millis: deadline,
            priority: 0,
            trace: TraceContext {
                trace_id: TraceId("trace-generic".to_owned()),
                span_id: SpanId("span-generic".to_owned()),
                trace_flags: 1,
                baggage: Metadata::new(),
            },
            idempotency_key: None,
            retry_attempt: 0,
            budget: budget.clone(),
            metadata: Metadata::new(),
            input: input.to_vec(),
            input_media_type: MEDIA.to_owned(),
        },
        prepared,
        cell: ExecutionCell {
            id: CellId("generic-cell".to_owned()),
            class: "standard".to_owned(),
            maximum_memory_bytes: budget.memory_bytes,
            metadata: Metadata::new(),
        },
        imports: Vec::new(),
        budget,
    }
}

pub async fn run(
    backend: &WasmtimeBackend,
    request: ExecutionRequest,
    cancellation: &Cancellation,
) -> Result<GuestOutcome, PlatformError> {
    let report = tokio::time::timeout(WATCHDOG, backend.invoke_contained(request, cancellation))
        .await
        .expect("generic invocation watchdog");
    assert_eq!(
        report.cleanup,
        ExecutionCleanup::Reusable,
        "backend must prove cleanup"
    );
    report.outcome
}

pub async fn call(
    backend: &WasmtimeBackend,
    prepared: &PreparedComponent,
    function: &str,
    input: &[u8],
) -> GuestOutcome {
    let cancellation = Cancellation::new(function);
    run(
        backend,
        request(
            prepared.clone(),
            &cancellation.id,
            VALUES,
            function,
            input,
            budget(),
        ),
        &cancellation,
    )
    .await
    .expect("guest outcome")
}

pub fn returned(outcome: GuestOutcome) -> Value {
    match outcome {
        GuestOutcome::Returned {
            output,
            output_media_type,
            ..
        } => {
            assert_eq!(output_media_type, MEDIA);
            serde_json::from_slice(&output).expect("canonical JSON output")
        }
        other => panic!("expected generic return, got {other:?}"),
    }
}

pub fn idle(backend: &WasmtimeBackend) {
    let snapshot = backend.resource_snapshot();
    assert_eq!(snapshot.active_invocations, 0);
    assert_eq!(snapshot.live_stores, 0);
    assert_eq!(snapshot.live_host_states, 0);
    assert_eq!(snapshot.live_component_instances, 0);
    assert_eq!(snapshot.live_temporary_buffers, 0);
    assert_eq!(snapshot.live_cancellation_probes, 0);
}

pub fn now_millis() -> u64 {
    u64::try_from(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("clock")
            .as_millis(),
    )
    .expect("clock fits")
}

fn required_path(name: &str) -> PathBuf {
    std::env::var_os(name).map_or_else(
        || panic!("{name} must be supplied by contracts gate"),
        PathBuf::from,
    )
}
