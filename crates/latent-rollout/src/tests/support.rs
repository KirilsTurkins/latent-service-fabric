use latent_artifacts::{
    content_digest, ArtifactDescriptor, ArtifactPage, ArtifactQuery, ArtifactRepository,
    CapsuleArtifact, ContractDescriptor, FunctionDescriptor, InterfaceDescriptor,
};
use latent_artifacts::{ReleaseActor, ReleaseActorKind};
use latent_control_store::{
    rollouts::{
        DeploymentExpectation, RolloutContext, RolloutId, RolloutOperationPrecondition,
        RolloutRequest, StartRolloutSpec,
    },
    DeploymentStore, DirectoryDeploymentRepository, DirectoryDeploymentRepositoryConfig,
};
use latent_core::{
    ArtifactReference, BoxFuture, ContractId, DeploymentId, FunctionId, InterfaceId, Metadata,
    PlatformError, ReleaseDigest, ResourceBudget, ServiceId, TenantId,
};
use latent_manifest::{
    AvailabilityPolicy, CapsuleManifest, ContractExport, DeploymentManifest, ExecutionBackendKind,
    ExecutionRequirements, ObjectMetadata, PlacementPolicy, StateModel, ThreadingModel,
    MANIFEST_API_VERSION,
};
use std::{collections::BTreeMap, sync::Arc};

const CONTRACT: &str = "alice:echo/api@1.0.0";
pub struct Releases(BTreeMap<ReleaseDigest, CapsuleArtifact>);
impl ArtifactRepository for Releases {
    fn resolve<'a>(
        &'a self,
        query: &'a ArtifactQuery,
    ) -> BoxFuture<'a, Result<Option<ArtifactDescriptor>, PlatformError>> {
        Box::pin(async move {
            Ok(query
                .release_digest
                .as_ref()
                .and_then(|d| self.0.get(d))
                .map(|a| a.descriptor.clone()))
        })
    }
    fn fetch<'a>(
        &'a self,
        digest: &'a ReleaseDigest,
    ) -> BoxFuture<'a, Result<CapsuleArtifact, PlatformError>> {
        Box::pin(async move { self.0.get(digest).cloned().ok_or_else(crate::closed) })
    }
    fn publish(
        &self,
        _: CapsuleArtifact,
    ) -> BoxFuture<'_, Result<ArtifactDescriptor, PlatformError>> {
        Box::pin(async { Err(crate::closed()) })
    }
    fn list<'a>(
        &'a self,
        _: Option<&'a ReleaseDigest>,
        _: usize,
    ) -> BoxFuture<'a, Result<ArtifactPage, PlatformError>> {
        Box::pin(async {
            Ok(ArtifactPage {
                entries: Vec::new(),
                next_after: None,
            })
        })
    }
}
fn budget() -> ResourceBudget {
    ResourceBudget {
        cpu_fuel: 1000,
        memory_bytes: 65536,
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
fn metadata(name: &str) -> ObjectMetadata {
    ObjectMetadata {
        name: name.into(),
        tenant: Some(TenantId("alice".into())),
        namespace: None,
        labels: Metadata::new(),
        annotations: Metadata::new(),
    }
}
fn artifact(marker: &[u8]) -> CapsuleArtifact {
    let digest = content_digest(marker);
    CapsuleArtifact {
        descriptor: ArtifactDescriptor {
            reference: ArtifactReference("local://rollout-test".into()),
            release_digest: digest.clone(),
            media_type: "application/vnd.wasm.component.v1+wasm".into(),
            size_bytes: marker.len() as u64,
            publisher: None,
            layers: Vec::new(),
            annotations: Metadata::new(),
        },
        manifest: CapsuleManifest {
            api_version: MANIFEST_API_VERSION.into(),
            metadata: metadata("echo"),
            semantic_version: "1.0.0".into(),
            component_digest: digest,
            world: ContractId(CONTRACT.into()),
            exports: vec![ContractExport {
                contract: ContractId(CONTRACT.into()),
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
            minimum_fabric_version: "0.1.0".into(),
            runtime_requirements: latent_manifest::RuntimeRequirements::default(),
        },
        contracts: vec![ContractDescriptor {
            id: ContractId(CONTRACT.into()),
            package_name: "alice:echo".into(),
            semantic_version: "1.0.0".into(),
            dependencies: Vec::new(),
            digest: content_digest(b"contract").0,
            interfaces: vec![InterfaceDescriptor {
                id: InterfaceId(CONTRACT.into()),
                documentation: None,
                digest: content_digest(b"interface").0,
                functions: vec![FunctionDescriptor {
                    id: FunctionId("echo".into()),
                    name: "echo".into(),
                    asynchronous: false,
                    parameters: Vec::new(),
                    results: Vec::new(),
                    documentation: None,
                    attributes: Metadata::new(),
                }],
            }],
        }],
        component_bytes: marker.to_vec(),
    }
}
fn deployment(id: &str, release: ReleaseDigest) -> DeploymentManifest {
    DeploymentManifest {
        api_version: MANIFEST_API_VERSION.into(),
        id: DeploymentId(id.into()),
        metadata: metadata(id),
        service: ServiceId("echo".into()),
        release,
        route_weight: 10000,
        grants: Vec::new(),
        resources: budget(),
        availability: AvailabilityPolicy {
            minimum_cached_copies: 1,
            minimum_zones: 1,
        },
        placement: PlacementPolicy {
            trust_class: "local".into(),
            architectures: vec!["x86_64".into()],
            regions: Vec::new(),
            zones: Vec::new(),
            required_features: Vec::new(),
        },
    }
}
pub fn context(operation: &str, revision: u64) -> RolloutContext {
    RolloutContext {
        tenant: TenantId("alice".into()),
        actor: ReleaseActor {
            kind: ReleaseActorKind::User,
            subject: "operator".into(),
        },
        operation: RolloutOperationPrecondition {
            operation_id: operation.into(),
            expected_revision: revision,
        },
    }
}
pub async fn repository(path: &std::path::Path) -> Arc<DirectoryDeploymentRepository> {
    let releases = Arc::new(Releases(
        [artifact(b"base"), artifact(b"candidate")]
            .into_iter()
            .map(|a| (a.descriptor.release_digest.clone(), a))
            .collect(),
    ));
    let repository = DirectoryDeploymentRepository::open(
        path.to_path_buf(),
        releases,
        DirectoryDeploymentRepositoryConfig::default(),
    )
    .await
    .unwrap();
    repository
        .apply(deployment("base", content_digest(b"base")))
        .await
        .unwrap();
    Arc::new(repository)
}
pub fn start() -> RolloutRequest {
    let mut candidate = deployment("candidate", content_digest(b"candidate"));
    candidate.route_weight = 1000;
    RolloutRequest::Start {
        context: context("start", 0),
        spec: StartRolloutSpec {
            id: RolloutId("rollout".into()),
            base: DeploymentExpectation {
                id: DeploymentId("base".into()),
                generation: 1,
            },
            candidate,
            candidate_weights: vec![1000, 5000, 10000],
            canary_policy: None,
        },
    }
}
