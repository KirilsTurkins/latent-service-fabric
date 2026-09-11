use std::collections::BTreeMap;
use std::future::Future;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, RwLock};
use std::task::{Context, Poll, Waker};

use latent_artifacts::{
    content_digest, ArtifactDescriptor, ArtifactPage, ArtifactQuery, ArtifactRepository,
    CapsuleArtifact, ContractDescriptor, FunctionDescriptor, InterfaceDescriptor,
};
use latent_core::{
    ArtifactReference, BoxFuture, ContractId, FunctionId, InterfaceId, Metadata, PlatformError,
    ReleaseDigest, ResourceBudget, RouteGeneration, ServiceId, TenantId,
};
use latent_manifest::{
    AvailabilityPolicy, CapsuleManifest, ContractExport, DeploymentManifest, ExecutionBackendKind,
    ExecutionRequirements, ObjectMetadata, PlacementPolicy, StateModel, ThreadingModel,
    MANIFEST_API_VERSION,
};
use latent_routing::InvocationTarget;

use super::super::{compile_versioned, CompiledCatalog, DirectoryDeploymentRepositoryConfig};

pub(super) const CONTRACT: &str = "example:echo/api@1.0.0";

#[derive(Default)]
pub(super) struct Releases {
    pub values: RwLock<BTreeMap<ReleaseDigest, CapsuleArtifact>>,
    pub fetches: AtomicUsize,
}
impl Releases {
    pub fn add(&self, marker: &str) -> ReleaseDigest {
        let value = artifact(marker);
        let digest = value.descriptor.release_digest.clone();
        self.values.write().unwrap().insert(digest.clone(), value);
        digest
    }
}
impl ArtifactRepository for Releases {
    fn resolve<'a>(
        &'a self,
        _: &'a ArtifactQuery,
    ) -> BoxFuture<'a, Result<Option<ArtifactDescriptor>, PlatformError>> {
        unreachable!("compiler resolves explicit releases")
    }
    fn fetch<'a>(
        &'a self,
        digest: &'a ReleaseDigest,
    ) -> BoxFuture<'a, Result<CapsuleArtifact, PlatformError>> {
        Box::pin(async move {
            self.fetches.fetch_add(1, Ordering::Relaxed);
            Ok(self
                .values
                .read()
                .unwrap()
                .get(digest)
                .expect("fixture release")
                .clone())
        })
    }
    fn publish<'a>(
        &'a self,
        _: CapsuleArtifact,
    ) -> BoxFuture<'a, Result<ArtifactDescriptor, PlatformError>> {
        unreachable!("compiler does not publish artifacts")
    }
    fn list<'a>(
        &'a self,
        _: Option<&'a ReleaseDigest>,
        _: usize,
    ) -> BoxFuture<'a, Result<ArtifactPage, PlatformError>> {
        unreachable!("compiler does not enumerate artifacts")
    }
}

pub(super) fn compile(
    releases: &Releases,
    deployments: Vec<DeploymentManifest>,
    generation: u64,
    previous: Option<&CompiledCatalog>,
) -> Result<CompiledCatalog, PlatformError> {
    let desired = deployments
        .into_iter()
        .map(|value| (value.id.clone(), Arc::new(value)))
        .collect::<BTreeMap<_, _>>();
    let versions = desired.keys().map(|id| (id.clone(), generation)).collect();
    let mut work = crate::deployments::observation::Work::default();
    let future = compile_versioned(
        desired,
        versions,
        RouteGeneration(generation),
        generation * 10,
        releases,
        DirectoryDeploymentRepositoryConfig::default(),
        previous,
        &mut work,
    );
    let mut future = std::pin::pin!(future);
    match future
        .as_mut()
        .poll(&mut Context::from_waker(Waker::noop()))
    {
        Poll::Ready(result) => {
            result.map(crate::deployments::persistence::EncodedCatalog::into_catalog)
        }
        Poll::Pending => panic!("fixture metadata is immediately ready"),
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

fn metadata(name: &str, tenant: Option<&str>) -> ObjectMetadata {
    ObjectMetadata {
        name: name.to_owned(),
        tenant: tenant.map(|value| TenantId(value.to_owned())),
        namespace: None,
        labels: Metadata::new(),
        annotations: Metadata::new(),
    }
}

pub(super) fn artifact(marker: &str) -> CapsuleArtifact {
    let digest = content_digest(marker.as_bytes());
    CapsuleArtifact {
        descriptor: ArtifactDescriptor {
            reference: ArtifactReference(format!("local://tests/{marker}")),
            release_digest: digest.clone(),
            media_type: "application/vnd.wasm.component.v1+wasm".to_owned(),
            size_bytes: marker.len() as u64,
            publisher: None,
            layers: Vec::new(),
            annotations: Metadata::new(),
        },
        manifest: CapsuleManifest {
            api_version: MANIFEST_API_VERSION.to_owned(),
            metadata: metadata("echo", None),
            semantic_version: "1.0.0".to_owned(),
            component_digest: digest,
            world: ContractId(CONTRACT.to_owned()),
            exports: vec![ContractExport {
                contract: ContractId(CONTRACT.to_owned()),
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
        },
        contracts: vec![ContractDescriptor {
            id: ContractId(CONTRACT.to_owned()),
            package_name: "example:echo".to_owned(),
            semantic_version: "1.0.0".to_owned(),
            dependencies: Vec::new(),
            digest: content_digest(b"contract-v1").0,
            interfaces: vec![InterfaceDescriptor {
                id: InterfaceId(CONTRACT.to_owned()),
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
        component_bytes: marker.as_bytes().to_vec(),
    }
}

pub(super) fn deployment(id: &str, tenant: &str, release: &ReleaseDigest) -> DeploymentManifest {
    DeploymentManifest {
        api_version: MANIFEST_API_VERSION.to_owned(),
        id: latent_core::DeploymentId(id.to_owned()),
        metadata: metadata(id, Some(tenant)),
        service: ServiceId("echo".to_owned()),
        release: release.clone(),
        route_weight: 1,
        grants: Vec::new(),
        resources: budget(),
        availability: AvailabilityPolicy {
            minimum_cached_copies: 1,
            minimum_zones: 1,
        },
        placement: PlacementPolicy {
            trust_class: "local".to_owned(),
            architectures: vec!["x86_64".to_owned()],
            regions: Vec::new(),
            zones: Vec::new(),
            required_features: Vec::new(),
        },
    }
}

pub(super) fn target(tenant: &str, route: Option<&str>) -> InvocationTarget {
    InvocationTarget {
        tenant: TenantId(tenant.to_owned()),
        service: ServiceId("echo".to_owned()),
        contract: ContractId(CONTRACT.to_owned()),
        function: FunctionId("echo".to_owned()),
        route: route.map(str::to_owned),
    }
}
