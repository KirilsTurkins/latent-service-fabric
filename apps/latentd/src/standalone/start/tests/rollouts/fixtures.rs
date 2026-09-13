use latent_artifacts::{
    content_digest, ArtifactDescriptor, CapsuleArtifact, ContractDescriptor, FunctionDescriptor,
    InterfaceDescriptor,
};
use latent_core::{
    ArtifactReference, ContractId, FunctionId, InterfaceId, Metadata, ReleaseDigest,
    ResourceBudget, TenantId,
};
use latent_manifest::{
    CapsuleManifest, ContractExport, ExecutionBackendKind, ExecutionRequirements, ObjectMetadata,
    StateModel, ThreadingModel, MANIFEST_API_VERSION,
};
use latent_wire::management::proto;

pub(in super::super) fn artifact(tenant: &str, service: &str, marker: &str) -> CapsuleArtifact {
    let component_bytes = marker.as_bytes().to_vec();
    let digest = content_digest(&component_bytes);
    let contract = format!("{tenant}:echo/api@1.0.0");
    CapsuleArtifact {
        descriptor: ArtifactDescriptor {
            reference: ArtifactReference(format!("local://tests/{marker}")),
            release_digest: digest.clone(),
            media_type: "application/vnd.wasm.component.v1+wasm".to_owned(),
            size_bytes: u64::try_from(component_bytes.len()).unwrap(),
            publisher: None,
            layers: Vec::new(),
            annotations: Metadata::new(),
        },
        manifest: CapsuleManifest {
            api_version: MANIFEST_API_VERSION.to_owned(),
            metadata: ObjectMetadata {
                name: service.to_owned(),
                tenant: Some(TenantId(tenant.to_owned())),
                namespace: None,
                labels: Metadata::new(),
                annotations: Metadata::new(),
            },
            semantic_version: "1.0.0".to_owned(),
            component_digest: digest,
            world: ContractId(contract.clone()),
            exports: vec![ContractExport {
                contract: ContractId(contract.clone()),
            }],
            imports: Vec::new(),
            execution: ExecutionRequirements {
                backend: ExecutionBackendKind::WasmComponent,
                threading: ThreadingModel::SingleThreaded,
                state_model: StateModel::Stateless,
                resource_budget_ceiling: budget(),
                host_call_depth_maximum: 1,
                component_call_depth_maximum: 1,
                snapshot_eligible: false,
                fusion_eligible: false,
            },
            minimum_fabric_version: "0.1.0".to_owned(),
            runtime_requirements: latent_manifest::RuntimeRequirements::default(),
        },
        contracts: vec![ContractDescriptor {
            id: ContractId(contract.clone()),
            package_name: format!("{tenant}:echo"),
            semantic_version: "1.0.0".to_owned(),
            dependencies: Vec::new(),
            digest: content_digest(b"contract-v1").0,
            interfaces: vec![InterfaceDescriptor {
                id: InterfaceId(contract),
                documentation: None,
                digest: content_digest(b"interface-v1").0,
                functions: vec![FunctionDescriptor {
                    id: FunctionId("echo".to_owned()),
                    name: "echo".to_owned(),
                    asynchronous: false,
                    parameters: Vec::new(),
                    results: Vec::new(),
                    documentation: None,
                    attributes: Metadata::new(),
                }],
            }],
        }],
        component_bytes,
    }
}

pub(in super::super) fn deployment(
    id: &str,
    tenant: &str,
    service: &str,
    digest: &ReleaseDigest,
) -> proto::Deployment {
    proto::Deployment {
        id: id.to_owned(),
        metadata: Some(proto::ObjectMetadata {
            name: id.to_owned(),
            tenant: Some(tenant.to_owned()),
            namespace: None,
            labels: [("tier".to_owned(), "gold".to_owned())].into(),
            annotations: [("inert.auth.claim".to_owned(), "operator=true".to_owned())].into(),
        }),
        service: service.to_owned(),
        release_digest: digest.0.clone(),
        route_weight: 1,
        grants: Vec::new(),
        resources: Some(latent_wire::management::control_budget_to_proto(&budget())),
        availability: Some(proto::AvailabilityPolicy {
            minimum_cached_copies: 1,
            minimum_zones: 1,
        }),
        placement: Some(proto::PlacementPolicy {
            trust_class: "local".to_owned(),
            architectures: vec!["x86_64".to_owned()],
            regions: Vec::new(),
            zones: Vec::new(),
            required_features: Vec::new(),
        }),
        generation: 0,
    }
}

fn budget() -> ResourceBudget {
    ResourceBudget {
        cpu_fuel: 1000,
        memory_bytes: 65_536,
        wall_time_limit_millis: Some(1000),
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
