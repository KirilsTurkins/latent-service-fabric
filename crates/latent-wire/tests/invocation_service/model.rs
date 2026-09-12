use std::collections::{BTreeMap, BTreeSet};

use latent_activation::{ActivationRequest, TraceContext};
use latent_admission::{
    CellClassPolicy, DeadlinePolicy, NodeAdmissionPolicy, OverloadPolicy, QueueClassPolicy,
    QuotaLimits, TenantAdmissionPolicy, TrustClassPolicy,
};
use latent_artifacts::{content_digest, ArtifactDescriptor, CapsuleArtifact};
use latent_core::{
    ActivationId, ArtifactReference, ContractId, FunctionId, IdempotencyKey, InvocationPrincipal,
    Metadata, PrincipalKind, ResourceBudget, ServiceId, SpanId, TenantId, TraceId,
};
use latent_manifest::{
    CapsuleManifest, ContractExport, ContractImport, ExecutionBackendKind, ExecutionRequirements,
    ObjectMetadata, PlacementPolicy, StateModel, ThreadingModel,
};
use latent_routing::{InvocationTarget, RevisionAdmissionPolicy};

pub const CONTRACT: &str = "tests:lifecycle/api@0.1.0";
pub const TENANT: &str = "tenant-a";

pub fn names(values: &[&str]) -> BTreeSet<String> {
    values.iter().map(|value| (*value).to_owned()).collect()
}

pub fn budget() -> ResourceBudget {
    ResourceBudget {
        cpu_fuel: 1000,
        memory_bytes: 65_536,
        wall_time_limit_millis: None,
        child_calls: 0,
        outbound_requests: 0,
        state_read_bytes: 0,
        state_write_bytes: 0,
        blob_read_bytes: 0,
        blob_write_bytes: 0,
        log_bytes: 128,
        effect_count: 0,
    }
}

pub fn request(id: &str) -> ActivationRequest {
    ActivationRequest {
        activation_id: Some(ActivationId(id.to_owned())),
        root_activation_id: None,
        parent_activation_id: None,
        principal: InvocationPrincipal {
            subject: "alice".to_owned(),
            kind: PrincipalKind::User,
            tenant: Some(TenantId(TENANT.to_owned())),
            service: None,
            claims: Metadata::new(),
        },
        target: InvocationTarget {
            tenant: TenantId(TENANT.to_owned()),
            service: ServiceId("echo".to_owned()),
            contract: ContractId(CONTRACT.to_owned()),
            function: FunctionId("echo".to_owned()),
            route: None,
        },
        deadline_unix_millis: None,
        priority: 10,
        trace: TraceContext {
            trace_id: TraceId("trace-pinned".to_owned()),
            span_id: SpanId("span-pinned".to_owned()),
            trace_flags: 1,
            baggage: Metadata::from([("guest.locale".to_owned(), "en".to_owned())]),
        },
        idempotency_key: Some(IdempotencyKey("retained-key".to_owned())),
        retry_attempt: 0,
        budget: budget(),
        metadata: Metadata::from([("guest.marker".to_owned(), "unchanged".to_owned())]),
        input: b"opaque payload".to_vec(),
        input_media_type: "application/octet-stream".to_owned(),
    }
}

pub fn node_policy(parallelism: u32) -> NodeAdmissionPolicy {
    let mut ceiling = budget();
    ceiling.wall_time_limit_millis = Some(10_000);
    let limits = QuotaLimits {
        maximum_concurrent_activations: 8,
        maximum_queued_activations: 8,
        maximum_reserved_cpu_fuel: 80_000,
        maximum_reserved_memory_bytes: 8 * 65_536,
    };
    let tenant = TenantAdmissionPolicy {
        limits,
        maximum_payload_bytes: 1024,
        maximum_priority: 255,
        allowed_subjects: names(&["alice"]),
        allowed_principal_kinds: vec![PrincipalKind::User, PrincipalKind::Administrator],
        allowed_trust_classes: names(&["sandbox"]),
        allowed_cell_classes: names(&["tiny"]),
    };
    NodeAdmissionPolicy {
        budget_ceiling: ceiling,
        limits,
        tenants: BTreeMap::from([
            (TenantId(TENANT.to_owned()), tenant.clone()),
            (TenantId("tenant-b".to_owned()), tenant),
        ]),
        trust_classes: BTreeMap::from([(
            "sandbox".to_owned(),
            TrustClassPolicy {
                limits,
                allowed_cell_classes: names(&["tiny"]),
            },
        )]),
        queue_classes: BTreeMap::from([(
            "normal".to_owned(),
            QueueClassPolicy {
                minimum_priority: 0,
                maximum_priority: 255,
                maximum_queued_activations: 8,
            },
        )]),
        cell_classes: BTreeMap::from([(
            "tiny".to_owned(),
            CellClassPolicy {
                maximum_memory_bytes: 65_536,
                parallelism,
                threading_models: vec![ThreadingModel::SingleThreaded],
                features: BTreeSet::new(),
            },
        )]),
        maximum_payload_bytes: 1024,
        maximum_priority: 255,
        maximum_identifier_bytes: 512,
        maximum_metadata_entries: 32,
        maximum_metadata_bytes: 4096,
        overload: OverloadPolicy {
            maximum_cpu_pressure_milli: 900,
            maximum_memory_pressure_milli: 900,
            maximum_sample_age_millis: 60_000,
        },
        deadline: DeadlinePolicy {
            estimated_service_time_millis: 1,
            minimum_execution_time_millis: 1,
            safety_margin_millis: 0,
        },
        architecture: "test-architecture".to_owned(),
        region: None,
        zone: None,
    }
}

pub fn policy() -> RevisionAdmissionPolicy {
    RevisionAdmissionPolicy {
        deployment_ceiling: budget(),
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
        placement: PlacementPolicy {
            trust_class: "sandbox".to_owned(),
            architectures: vec!["test-architecture".to_owned()],
            regions: Vec::new(),
            zones: Vec::new(),
            required_features: Vec::new(),
        },
    }
}

pub fn artifact(generation: u8, bucket: u8) -> CapsuleArtifact {
    let bytes = vec![generation, bucket];
    let digest = content_digest(&bytes);
    CapsuleArtifact {
        descriptor: ArtifactDescriptor {
            reference: ArtifactReference("local://lifecycle-fixture".to_owned()),
            release_digest: digest.clone(),
            media_type: "application/vnd.wasm.component.v1+wasm".to_owned(),
            size_bytes: 2,
            publisher: None,
            layers: Vec::new(),
            annotations: Metadata::new(),
        },
        manifest: CapsuleManifest {
            api_version: "latent.dev/v1alpha1".to_owned(),
            metadata: ObjectMetadata {
                name: "echo".to_owned(),
                tenant: Some(TenantId(TENANT.to_owned())),
                namespace: None,
                labels: Metadata::new(),
                annotations: Metadata::new(),
            },
            semantic_version: "0.1.0".to_owned(),
            component_digest: digest,
            world: ContractId("tests:lifecycle/service@0.1.0".to_owned()),
            exports: vec![ContractExport {
                contract: ContractId(CONTRACT.to_owned()),
            }],
            imports: ["latent:context/context@0.1.0", "latent:log/log@0.1.0"]
                .iter()
                .map(|contract| ContractImport {
                    contract: ContractId((*contract).to_owned()),
                    optional: false,
                })
                .collect(),
            execution: policy().execution,
            minimum_fabric_version: "0.1.0-alpha.0".to_owned(),
            runtime_requirements: latent_manifest::RuntimeRequirements::default(),
        },
        contracts: Vec::new(),
        component_bytes: bytes,
    }
}
