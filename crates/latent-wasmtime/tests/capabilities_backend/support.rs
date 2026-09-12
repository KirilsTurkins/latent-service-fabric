use std::fs;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use latent_activation::{ActivationEnvelope, TraceContext};
use latent_artifacts::{ArtifactDescriptor, CapsuleArtifact};
use latent_core::{
    ActivationBudget, ActivationClock, ActivationId, ArtifactReference, CapabilityId, CellId,
    ClockSample, ContractId, EffectiveActivationBudget, FunctionId, InvocationPrincipal, Metadata,
    PrincipalKind, ReleaseDigest, ResourceBudget, ServiceId, SpanId, TenantId, TraceId,
};
use latent_executor::{
    BoundImport, ExecutionBackend, ExecutionCancellation, ExecutionCell, ExecutionCleanup,
    ExecutionRequest, GuestOutcome, PreparedComponent,
};
use latent_manifest::{
    CapsuleManifest, ContractExport, ContractImport, ExecutionBackendKind, ExecutionRequirements,
    ObjectMetadata, StateModel, ThreadingModel,
};
use latent_routing::InvocationTarget;
use latent_wasmtime::{
    WasmtimeBackend, WasmtimeComponentEngineFactory, WasmtimeConfig, WasmtimeHostServices,
};
use serde_json::Value;
use sha2::{Digest, Sha256};

pub const MEDIA: &str = "application/vnd.latent.wit-values.v1+json";
pub const CONTRACT: &str = "tests:capabilities/api@0.1.0";
pub const IMPORTS: [&str; 4] = [
    "latent:context/context@0.1.0",
    "latent:log/log@0.1.0",
    "latent:clock/monotonic@0.1.0",
    "latent:clock/wall@0.1.0",
];
const MEMORY: u64 = 16 * 1024 * 1024;
const FUEL: u64 = 20_000_000;

pub struct ManualClock(Mutex<ClockSample>);

impl ManualClock {
    pub fn new() -> Self {
        Self(Mutex::new(ClockSample::new(10_000, Instant::now())))
    }

    pub fn set(&self, value: ClockSample) {
        *self.0.lock().expect("clock lock") = value;
    }
}

impl ActivationClock for ManualClock {
    fn sample(&self) -> ClockSample {
        *self.0.lock().expect("clock lock")
    }

    fn monotonic_now(&self) -> Instant {
        self.sample().monotonic()
    }
}

pub struct Cancellation {
    pub id: ActivationId,
    pub accounting: ActivationBudget,
}

impl Cancellation {
    pub fn new(id: &str, grant: &ResourceBudget, sample: ClockSample) -> Self {
        Self {
            id: ActivationId(id.to_owned()),
            accounting: ActivationBudget::new(
                EffectiveActivationBudget::admit_at(grant, grant, grant, None, sample)
                    .expect("fixture budget"),
            ),
        }
    }
}

impl ExecutionCancellation for Cancellation {
    fn activation_id(&self) -> &ActivationId {
        &self.id
    }

    fn is_cancelled(&self) -> bool {
        false
    }

    fn reason(&self) -> Option<String> {
        None
    }

    fn budget_accounting(&self) -> Option<&ActivationBudget> {
        Some(&self.accounting)
    }
}

pub fn config() -> WasmtimeConfig {
    WasmtimeConfig {
        maximum_memory_bytes: MEMORY,
        maximum_fuel: FUEL,
        epoch_tick_interval_millis: 1,
        ..WasmtimeConfig::default()
    }
}

pub fn budget() -> ResourceBudget {
    ResourceBudget {
        cpu_fuel: FUEL,
        memory_bytes: MEMORY,
        wall_time_limit_millis: None,
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

pub fn artifact() -> CapsuleArtifact {
    let path = std::env::var_os("LSF_CAPABILITIES_COMPONENT")
        .expect("LSF_CAPABILITIES_COMPONENT must be supplied by contracts gate");
    let bytes = fs::read(path).expect("capabilities component");
    let digest = ReleaseDigest(format!("sha256:{:x}", Sha256::digest(&bytes)));
    CapsuleArtifact {
        descriptor: ArtifactDescriptor {
            reference: ArtifactReference("local://capabilities-fixture".to_owned()),
            release_digest: digest.clone(),
            media_type: "application/vnd.wasm.component.v1+wasm".to_owned(),
            size_bytes: u64::try_from(bytes.len()).expect("fixture size"),
            publisher: None,
            layers: Vec::new(),
            annotations: Metadata::new(),
        },
        manifest: CapsuleManifest {
            api_version: "latent.dev/v1alpha1".to_owned(),
            metadata: ObjectMetadata {
                name: "capabilities-capsule".to_owned(),
                tenant: Some(TenantId("tests".to_owned())),
                namespace: None,
                labels: Metadata::new(),
                annotations: Metadata::new(),
            },
            semantic_version: "0.1.0".to_owned(),
            component_digest: digest,
            world: ContractId("tests:capabilities/service@0.1.0".to_owned()),
            exports: vec![ContractExport {
                contract: ContractId(CONTRACT.to_owned()),
            }],
            imports: IMPORTS
                .iter()
                .map(|name| ContractImport {
                    contract: ContractId((*name).to_owned()),
                    optional: false,
                })
                .collect(),
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
        },
        contracts: Vec::new(),
        component_bytes: bytes,
    }
}

pub async fn prepared(
    config: WasmtimeConfig,
    services: WasmtimeHostServices,
) -> (WasmtimeBackend, PreparedComponent) {
    let factory = WasmtimeComponentEngineFactory::with_host_services(config, services)
        .expect("capability factory");
    let backend = factory.create_backend_instance();
    let artifact = artifact();
    let prepared = backend
        .prepare(
            &artifact,
            &factory.preparation_key(artifact.descriptor.release_digest.clone()),
        )
        .await
        .expect("four capability imports prepare");
    assert_eq!(backend.resource_snapshot().stores_created, 0);
    (backend, prepared)
}

pub fn request(
    prepared: &PreparedComponent,
    cancellation: &Cancellation,
    function: &str,
    input: &Value,
) -> ExecutionRequest {
    let grant = cancellation.accounting.granted().clone();
    ExecutionRequest {
        activation: ActivationEnvelope {
            activation_id: cancellation.id.clone(),
            root_activation_id: ActivationId("root-pinned".to_owned()),
            parent_activation_id: Some(ActivationId("parent-pinned".to_owned())),
            principal: InvocationPrincipal {
                subject: "authenticated-subject".to_owned(),
                kind: PrincipalKind::Service,
                tenant: Some(TenantId("tests".to_owned())),
                service: Some(ServiceId("caller".to_owned())),
                claims: Metadata::new(),
            },
            target: InvocationTarget {
                tenant: TenantId("tests".to_owned()),
                service: ServiceId("capabilities".to_owned()),
                contract: ContractId(CONTRACT.to_owned()),
                function: FunctionId(function.to_owned()),
                route: None,
            },
            resolved_revision: None,
            deadline_unix_millis: cancellation.accounting.deadline().unix_millis(),
            priority: 0,
            trace: TraceContext {
                trace_id: TraceId("trace-pinned".to_owned()),
                span_id: SpanId("span-pinned".to_owned()),
                trace_flags: 1,
                baggage: Metadata::new(),
            },
            idempotency_key: None,
            retry_attempt: 0,
            budget: grant.clone(),
            metadata: Metadata::new(),
            input: serde_json::to_vec(input).expect("fixture input"),
            input_media_type: MEDIA.to_owned(),
        },
        prepared: prepared.clone(),
        cell: ExecutionCell {
            id: CellId("reused-capability-cell".to_owned()),
            class: "standard".to_owned(),
            maximum_memory_bytes: grant.memory_bytes,
            metadata: Metadata::new(),
        },
        imports: IMPORTS
            .iter()
            .map(|contract| BoundImport {
                capability: CapabilityId((*contract).to_owned()),
                contract: (*contract).to_owned(),
                opaque_handle: "activation-scoped".to_owned(),
            })
            .collect(),
        budget: grant,
    }
}

pub async fn run(
    backend: &WasmtimeBackend,
    request: ExecutionRequest,
    cancellation: &Cancellation,
) -> GuestOutcome {
    let report = tokio::time::timeout(
        Duration::from_secs(5),
        backend.invoke_contained(request, cancellation),
    )
    .await
    .expect("capabilities invocation watchdog");
    assert_eq!(report.cleanup, ExecutionCleanup::Reusable);
    idle(backend);
    report.outcome.expect("capability invocation outcome")
}

pub fn returned(outcome: GuestOutcome) -> Value {
    match outcome {
        GuestOutcome::Returned {
            output,
            output_media_type,
            ..
        } => {
            assert_eq!(output_media_type, MEDIA);
            serde_json::from_slice(&output).expect("canonical capability output")
        }
        other => panic!("expected capability return: {other:?}"),
    }
}

pub fn unsigned(value: &Value) -> u64 {
    value.as_str().expect("canonical u64").parse().expect("u64")
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

pub fn services(clock: &Arc<ManualClock>) -> WasmtimeHostServices {
    WasmtimeHostServices {
        clock: clock.clone(),
        log_sink: None,
    }
}
