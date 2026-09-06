use std::collections::BTreeMap;
use std::future::Future;
use std::path::PathBuf;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Barrier, Mutex, RwLock};
use std::task::{Context, Poll, Wake, Waker};

use latent_artifacts::{
    content_digest, ArtifactDescriptor, ArtifactPage, ArtifactQuery, ArtifactRepository,
    CapsuleArtifact, ContractDescriptor, FunctionDescriptor, InterfaceDescriptor,
};
use latent_core::{
    ArtifactReference, BoxFuture, ContractId, FunctionId, InterfaceId, Metadata, PlatformError,
    PlatformErrorCode, ReleaseDigest, ResourceBudget, ServiceId, TenantId,
};
use latent_manifest::{
    AvailabilityPolicy, CapsuleManifest, ContractExport, DeploymentManifest, ExecutionBackendKind,
    ExecutionRequirements, ObjectMetadata, PlacementPolicy, StateModel, ThreadingModel,
    MANIFEST_API_VERSION,
};
use latent_routing::{InvocationTarget, RouteSnapshot, RouteSnapshotSource};

use super::super::{
    error, DirectoryDeploymentRepository, DirectoryDeploymentRepositoryConfig,
};

pub(super) type Store = DirectoryDeploymentRepository;
pub(super) type Limits = DirectoryDeploymentRepositoryConfig;
pub(super) type Code = PlatformErrorCode;
pub(super) const CONTRACT: &str = "example:echo/api@1.0.0";

struct ThreadWake(std::thread::Thread);

impl Wake for ThreadWake {
    fn wake(self: Arc<Self>) {
        self.0.unpark();
    }

    fn wake_by_ref(self: &Arc<Self>) {
        self.0.unpark();
    }
}

pub(super) fn run<F: Future>(future: F) -> F::Output {
    let waker = Waker::from(Arc::new(ThreadWake(std::thread::current())));
    let mut context = Context::from_waker(&waker);
    let mut future = std::pin::pin!(future);
    loop {
        match future.as_mut().poll(&mut context) {
            Poll::Ready(result) => return result,
            Poll::Pending => std::thread::park(),
        }
    }
}

pub(super) struct TempRoot(pub PathBuf);

impl TempRoot {
    pub fn new() -> Self {
        static NEXT: AtomicUsize = AtomicUsize::new(0);
        let sequence = NEXT.fetch_add(1, Ordering::Relaxed);
        let nonce = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root = std::env::temp_dir().join(format!(
            "lsf-deployment-{}-{nonce}-{sequence}",
            std::process::id()
        ));
        std::fs::create_dir(&root).unwrap();
        Self(root)
    }
}

impl Drop for TempRoot {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

#[derive(Default)]
pub(super) struct Releases {
    pub values: RwLock<BTreeMap<ReleaseDigest, CapsuleArtifact>>,
    pub fetches: AtomicUsize,
    pub fetch_gate: Mutex<Option<Arc<Barrier>>>,
}

impl Releases {
    pub fn add(&self, marker: &str) -> ReleaseDigest {
        let artifact = artifact(marker);
        let digest = artifact.descriptor.release_digest.clone();
        self.values.write().unwrap().insert(digest.clone(), artifact);
        digest
    }
}

impl ArtifactRepository for Releases {
    fn resolve<'a>(
        &'a self,
        query: &'a ArtifactQuery,
    ) -> BoxFuture<'a, Result<Option<ArtifactDescriptor>, PlatformError>> {
        Box::pin(async move {
            Ok(query.release_digest.as_ref().and_then(|digest| {
                self.values
                    .read()
                    .unwrap()
                    .get(digest)
                    .map(|artifact| artifact.descriptor.clone())
            }))
        })
    }

    fn fetch<'a>(
        &'a self,
        digest: &'a ReleaseDigest,
    ) -> BoxFuture<'a, Result<CapsuleArtifact, PlatformError>> {
        Box::pin(async move {
            self.fetches.fetch_add(1, Ordering::Relaxed);
            let gate = self.fetch_gate.lock().unwrap().clone();
            if let Some(gate) = gate {
                gate.wait();
            }
            self.values
                .read()
                .unwrap()
                .get(digest)
                .cloned()
                .ok_or_else(|| error(Code::NotFound, "release-not-found"))
        })
    }

    fn publish<'a>(
        &'a self,
        artifact: CapsuleArtifact,
    ) -> BoxFuture<'a, Result<ArtifactDescriptor, PlatformError>> {
        Box::pin(async move {
            let descriptor = artifact.descriptor.clone();
            self.values
                .write()
                .unwrap()
                .insert(descriptor.release_digest.clone(), artifact);
            Ok(descriptor)
        })
    }

    fn list<'a>(
        &'a self,
        after: Option<&'a ReleaseDigest>,
        limit: usize,
    ) -> BoxFuture<'a, Result<ArtifactPage, PlatformError>> {
        Box::pin(async move {
            let values = self.values.read().unwrap();
            let entries = values
                .iter()
                .filter(|(digest, _)| after.is_none_or(|cursor| *digest > cursor))
                .take(limit)
                .map(|(_, artifact)| artifact.descriptor.clone())
                .collect();
            Ok(ArtifactPage {
                entries,
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

pub(super) fn open(root: &TempRoot, releases: &Arc<Releases>) -> Store {
    run(Store::open(root.0.clone(), releases.clone(), Limits::default())).unwrap()
}

pub(super) fn snapshot(store: &Store) -> RouteSnapshot {
    run(RouteSnapshotSource::current(store)).unwrap()
}

pub(super) fn assert_code<T>(result: Result<T, PlatformError>, code: Code) {
    let failure = result.err().expect("operation should fail");
    assert_eq!(failure.code, code, "{failure:?}");
}
