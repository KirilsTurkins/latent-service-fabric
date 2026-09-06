use super::*;

use std::future::Future;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::task::{Context, Poll, Wake, Waker};

use latent_artifacts::{
    content_digest, ArtifactDescriptor, ArtifactPage, ArtifactQuery, CapsuleArtifact,
    ContractDescriptor, FunctionDescriptor, InterfaceDescriptor,
};
use latent_core::{
    ArtifactReference, FunctionId, InterfaceId, ReleaseDigest, ResourceBudget, ServiceId, TenantId,
};
use latent_manifest::{
    __serde_json as json, AvailabilityPolicy, CapsuleManifest, ContractExport, ExecutionBackendKind,
    ExecutionRequirements, ObjectMetadata, PlacementPolicy, StateModel, ThreadingModel,
    MANIFEST_API_VERSION,
};

const CONTRACT: &str = "example:echo/api@1.0.0";

struct ThreadWake(std::thread::Thread);
impl Wake for ThreadWake {
    fn wake(self: Arc<Self>) { self.0.unpark(); }
    fn wake_by_ref(self: &Arc<Self>) { self.0.unpark(); }
}

fn run<F: Future>(future: F) -> F::Output {
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

struct TempRoot(PathBuf);
impl TempRoot {
    fn new() -> Self {
        static NEXT: AtomicUsize = AtomicUsize::new(0);
        let root = std::env::temp_dir().join(format!("lsf-deployment-{}-{}", std::process::id(), NEXT.fetch_add(1, Ordering::Relaxed)));
        std::fs::create_dir(&root).unwrap();
        Self(root)
    }
}
impl Drop for TempRoot {
    fn drop(&mut self) { let _ = std::fs::remove_dir_all(&self.0); }
}

#[derive(Default)]
struct Releases {
    values: RwLock<BTreeMap<ReleaseDigest, CapsuleArtifact>>,
    fetches: AtomicUsize,
}
impl Releases {
    fn add(&self, marker: &str) -> ReleaseDigest {
        let artifact = artifact(marker);
        let digest = artifact.descriptor.release_digest.clone();
        self.values.write().unwrap().insert(digest.clone(), artifact);
        digest
    }
}
impl ArtifactRepository for Releases {
    fn resolve<'a>(&'a self, query: &'a ArtifactQuery) -> BoxFuture<'a, Result<Option<ArtifactDescriptor>, PlatformError>> {
        Box::pin(async move {
            Ok(query.release_digest.as_ref().and_then(|digest| self.values.read().unwrap().get(digest).map(|artifact| artifact.descriptor.clone())))
        })
    }
    fn fetch<'a>(&'a self, digest: &'a ReleaseDigest) -> BoxFuture<'a, Result<CapsuleArtifact, PlatformError>> {
        Box::pin(async move {
            self.fetches.fetch_add(1, Ordering::Relaxed);
            self.values.read().unwrap().get(digest).cloned().ok_or_else(|| error(PlatformErrorCode::NotFound, "release-not-found"))
        })
    }
    fn publish<'a>(&'a self, artifact: CapsuleArtifact) -> BoxFuture<'a, Result<ArtifactDescriptor, PlatformError>> {
        Box::pin(async move {
            let descriptor = artifact.descriptor.clone();
            self.values.write().unwrap().insert(descriptor.release_digest.clone(), artifact);
            Ok(descriptor)
        })
    }
    fn list<'a>(&'a self, after: Option<&'a ReleaseDigest>, limit: usize) -> BoxFuture<'a, Result<ArtifactPage, PlatformError>> {
        Box::pin(async move {
            let values = self.values.read().unwrap();
            let entries = values.iter().filter(|(digest, _)| after.is_none_or(|cursor| *digest > cursor))
                .take(limit).map(|(_, artifact)| artifact.descriptor.clone()).collect();
            Ok(ArtifactPage { entries, next_after: None })
        })
    }
}

fn budget() -> ResourceBudget {
    ResourceBudget {
        cpu_fuel: 1000, memory_bytes: 65536, wall_time_limit_millis: Some(1000),
        child_calls: 0, outbound_requests: 0, state_read_bytes: 0, state_write_bytes: 0,
        blob_read_bytes: 0, blob_write_bytes: 0, log_bytes: 128, effect_count: 0,
    }
}

fn metadata(name: &str, tenant: Option<&str>) -> ObjectMetadata {
    ObjectMetadata {
        name: name.to_owned(), tenant: tenant.map(|value| TenantId(value.to_owned())),
        namespace: None, labels: Metadata::new(), annotations: Metadata::new(),
    }
}

fn artifact(marker: &str) -> CapsuleArtifact {
    let digest = content_digest(marker.as_bytes());
    CapsuleArtifact {
        descriptor: ArtifactDescriptor {
            reference: ArtifactReference(format!("local:{marker}")), release_digest: digest.clone(),
            media_type: "application/wasm".to_owned(), size_bytes: marker.len() as u64,
            publisher: None, layers: Vec::new(), annotations: Metadata::new(),
        },
        manifest: CapsuleManifest {
            api_version: MANIFEST_API_VERSION.to_owned(), metadata: metadata("echo", None),
            semantic_version: "1.0.0".to_owned(), component_digest: digest,
            world: latent_core::ContractId(CONTRACT.to_owned()),
            exports: vec![ContractExport { contract: latent_core::ContractId(CONTRACT.to_owned()) }],
            imports: Vec::new(),
            execution: ExecutionRequirements {
                backend: ExecutionBackendKind::WasmComponent, threading: ThreadingModel::SingleThreaded,
                state_model: StateModel::Stateless, resource_budget_ceiling: budget(),
                host_call_depth_maximum: 1, component_call_depth_maximum: 1,
                snapshot_eligible: false, fusion_eligible: false,
            },
            minimum_fabric_version: "0.1.0".to_owned(),
        },
        contracts: vec![ContractDescriptor {
            id: latent_core::ContractId(CONTRACT.to_owned()), package_name: "example:echo".to_owned(),
            semantic_version: "1.0.0".to_owned(), dependencies: Vec::new(), digest: "contract-v1".to_owned(),
            interfaces: vec![InterfaceDescriptor {
                id: InterfaceId("example:echo/api@1.0.0".to_owned()), documentation: None,
                digest: "interface-v1".to_owned(),
                functions: vec![FunctionDescriptor {
                    id: FunctionId("echo".to_owned()), name: "echo".to_owned(), asynchronous: false,
                    parameters: Vec::new(), results: Vec::new(), documentation: None, attributes: Metadata::new(),
                }],
            }],
        }],
        component_bytes: marker.as_bytes().to_vec(),
    }
}

fn deployment(id: &str, tenant: &str, release: &ReleaseDigest) -> DeploymentManifest {
    DeploymentManifest {
        api_version: MANIFEST_API_VERSION.to_owned(), id: DeploymentId(id.to_owned()),
        metadata: metadata(id, Some(tenant)), service: ServiceId("echo".to_owned()),
        release: release.clone(), route_weight: 1, grants: Vec::new(), resources: budget(),
        availability: AvailabilityPolicy { minimum_cached_copies: 1, minimum_zones: 1 },
        placement: PlacementPolicy {
            trust_class: "local".to_owned(), architectures: vec!["x86_64".to_owned()],
            regions: Vec::new(), zones: Vec::new(), required_features: Vec::new(),
        },
    }
}

fn target(tenant: &str, route: Option<&str>) -> InvocationTarget {
    InvocationTarget {
        tenant: TenantId(tenant.to_owned()), service: ServiceId("echo".to_owned()),
        contract: latent_core::ContractId(CONTRACT.to_owned()), function: FunctionId("echo".to_owned()),
        route: route.map(str::to_owned),
    }
}

fn open(root: &TempRoot, releases: &Arc<Releases>) -> DirectoryDeploymentRepository {
    run(DirectoryDeploymentRepository::open(root.0.clone(), releases.clone(), DirectoryDeploymentRepositoryConfig::default())).unwrap()
}

#[test]
fn apply_read_list_delete_and_pinned_revision() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let one = releases.add("one");
    let two = releases.add("two");
    let repository = open(&root, &releases);
    let first = deployment("blue", "alice", &one);
    run(DeploymentStore::apply(&repository, first.clone())).unwrap();
    assert_eq!(repository.generation(), RouteGeneration(1));
    assert_eq!(run(DeploymentStore::get(&repository, &first.id)).unwrap(), Some(first.clone()));
    assert_eq!(run(DeploymentStore::list(&repository)).unwrap(), vec![first]);
    let pinned = repository.pin().unwrap();
    let resolved = pinned.resolve(&target("alice", None), Some("key")).unwrap();
    run(DeploymentStore::apply(&repository, deployment("blue", "alice", &two))).unwrap();
    assert_eq!(repository.resolve(&target("alice", None), Some("key")).unwrap().release, two);
    assert_eq!(pinned.resolve(&target("alice", None), Some("key")).unwrap(), resolved);
    assert_eq!(resolved.release, one);
    assert_eq!(resolved.route_generation, RouteGeneration(1));
    run(DeploymentStore::delete(&repository, &DeploymentId("blue".to_owned()))).unwrap();
    assert_eq!(repository.generation(), RouteGeneration(3));
    assert_eq!(repository.resolve(&target("alice", None), None).unwrap_err().code, PlatformErrorCode::RouteUnavailable);
    assert_eq!(pinned.resolve(&target("alice", None), None).unwrap().release, one);
    assert_eq!(run(DeploymentStore::delete(&repository, &DeploymentId("missing".to_owned()))).unwrap_err().code, PlatformErrorCode::NotFound);
}

#[test]
fn tenants_and_named_routes_never_cross_boundaries() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let one = releases.add("one");
    let two = releases.add("two");
    let repository = open(&root, &releases);
    run(repository.apply_many(vec![deployment("alice-blue", "alice", &one), deployment("bob-blue", "bob", &two)])).unwrap();
    for key in [None, Some(""), Some("same-key")] {
        assert_eq!(repository.resolve(&target("alice", None), key).unwrap().release, one);
        assert_eq!(repository.resolve(&target("bob", None), key).unwrap().release, two);
    }
    assert_eq!(repository.resolve(&target("alice", Some("bob-blue")), None).unwrap_err().code, PlatformErrorCode::RouteUnavailable);
    assert_eq!(repository.resolve(&target("unknown", None), None).unwrap_err().code, PlatformErrorCode::RouteUnavailable);
    let mut wrong = target("alice", None);
    wrong.function.0 = "missing".to_owned();
    assert_eq!(repository.resolve(&wrong, None).unwrap_err().code, PlatformErrorCode::IncompatibleContract);
    wrong.contract.0 = "missing:contract/api@1.0.0".to_owned();
    assert_eq!(repository.resolve(&wrong, None).unwrap_err().code, PlatformErrorCode::IncompatibleContract);
}

#[test]
fn weighting_is_deterministic_order_independent_and_restart_stable() {
    let root = TempRoot::new();
    let other = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let one = releases.add("one");
    let two = releases.add("two");
    let blue = deployment("blue", "alice", &one);
    let mut green = deployment("green", "alice", &two);
    green.route_weight = 3;
    let repository = open(&root, &releases);
    let reverse = open(&other, &releases);
    run(repository.apply_many(vec![blue.clone(), green.clone()])).unwrap();
    run(reverse.apply_many(vec![green, blue.clone()])).unwrap();
    let mut choices = Vec::new();
    for index in 0..2048 {
        let key = format!("key-{index}");
        let result = repository.resolve(&target("alice", None), Some(&key)).unwrap();
        assert_eq!(result, reverse.resolve(&target("alice", None), Some(&key)).unwrap());
        choices.push(result);
    }
    let blue_count = choices.iter().filter(|choice| choice.release == one).count();
    assert!((400..=625).contains(&blue_count), "blue count: {blue_count}");
    assert_eq!(repository.resolve(&target("alice", Some("blue")), Some("any")).unwrap().release, one);
    let mut reweighted = blue.clone();
    reweighted.route_weight = 10_000;
    assert_eq!(deployment_revision_id(&blue).unwrap(), deployment_revision_id(&reweighted).unwrap());
    reweighted.resources.cpu_fuel -= 1;
    assert_ne!(deployment_revision_id(&blue).unwrap(), deployment_revision_id(&reweighted).unwrap());
    drop(repository);
    let repository = open(&root, &releases);
    for (index, choice) in choices.iter().enumerate() {
        assert_eq!(repository.resolve(&target("alice", None), Some(&format!("key-{index}"))).unwrap(), *choice);
    }
}

#[test]
fn invalid_batches_leave_generation_and_state_unchanged() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let one = releases.add("one");
    let repository = open(&root, &releases);
    let blue = deployment("blue", "alice", &one);
    run(DeploymentStore::apply(&repository, blue.clone())).unwrap();
    let before = run(RouteSnapshotSource::current(&repository)).unwrap();
    for weight in [0, 10_001, u16::MAX] {
        let mut invalid = blue.clone();
        invalid.route_weight = weight;
        assert_eq!(run(DeploymentStore::apply(&repository, invalid)).unwrap_err().code, PlatformErrorCode::InvalidArgument);
    }
    assert_eq!(run(repository.apply_many(vec![blue.clone(), blue.clone()])).unwrap_err().code, PlatformErrorCode::AlreadyExists);
    let mut conflict = blue.clone();
    conflict.metadata.tenant = Some(TenantId("bob".to_owned()));
    assert_eq!(run(DeploymentStore::apply(&repository, conflict)).unwrap_err().code, PlatformErrorCode::PermissionDenied);
    let mut namespace = deployment("green", "alice", &one);
    namespace.metadata.namespace = Some("other".to_owned());
    assert_eq!(run(DeploymentStore::apply(&repository, namespace)).unwrap_err().code, PlatformErrorCode::PermissionDenied);
    let missing = deployment("missing", "alice", &content_digest(b"missing"));
    assert_eq!(run(repository.apply_many(vec![deployment("valid", "alice", &one), missing])).unwrap_err().code, PlatformErrorCode::NotFound);
    assert_eq!(run(RouteSnapshotSource::current(&repository)).unwrap(), before);
    assert_eq!(run(DeploymentStore::list(&repository)).unwrap(), vec![blue]);
}

#[test]
fn rejects_unsupported_releases_and_contract_conflicts() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let one = releases.add("one");
    let two = releases.add("two");
    let repository = open(&root, &releases);
    run(DeploymentStore::apply(&repository, deployment("blue", "alice", &one))).unwrap();
    for backend in [ExecutionBackendKind::Container, ExecutionBackendKind::MicroVm, ExecutionBackendKind::EphemeralProcess, ExecutionBackendKind::RemoteProvider] {
        releases.values.write().unwrap().get_mut(&two).unwrap().manifest.execution.backend = backend;
        assert_eq!(run(DeploymentStore::apply(&repository, deployment("green", "alice", &two))).unwrap_err().code, PlatformErrorCode::InvalidArgument);
    }
    releases.values.write().unwrap().get_mut(&two).unwrap().manifest.execution.backend = ExecutionBackendKind::WasmComponent;
    for state in [StateModel::Entity, StateModel::DurableWorkflow, StateModel::TransactionalKeyed] {
        releases.values.write().unwrap().get_mut(&two).unwrap().manifest.execution.state_model = state;
        assert_eq!(run(DeploymentStore::apply(&repository, deployment("green", "alice", &two))).unwrap_err().code, PlatformErrorCode::InvalidArgument);
    }
    releases.values.write().unwrap().get_mut(&two).unwrap().manifest.execution.state_model = StateModel::Stateless;
    releases.values.write().unwrap().get_mut(&two).unwrap().contracts[0].interfaces[0].functions[0].asynchronous = true;
    assert_eq!(run(DeploymentStore::apply(&repository, deployment("green", "alice", &two))).unwrap_err().code, PlatformErrorCode::IncompatibleContract);
    releases.values.write().unwrap().get_mut(&two).unwrap().contracts.clear();
    assert_eq!(run(DeploymentStore::apply(&repository, deployment("green", "alice", &two))).unwrap_err().code, PlatformErrorCode::IncompatibleContract);
    assert_eq!(repository.generation(), RouteGeneration(1));
}

#[test]
fn compiler_publisher_and_coalescing_source_enforce_complete_generations() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let one = releases.add("one");
    let repository = open(&root, &releases);
    run(DeploymentStore::apply(&repository, deployment("blue", "alice", &one))).unwrap();
    let old = run(RouteSnapshotSource::current(&repository)).unwrap();
    let next = run(RouteCompiler::compile(&repository, Some(&old))).unwrap();
    let mut invalid = next.clone();
    invalid.services.clear();
    assert_eq!(run(RouteSnapshotPublisher::publish(&repository, invalid)).unwrap_err().code, PlatformErrorCode::InvalidArgument);
    run(RouteSnapshotPublisher::publish(&repository, next.clone())).unwrap();
    assert_eq!(run(RouteSnapshotPublisher::publish(&repository, next.clone())).unwrap_err().code, PlatformErrorCode::StateConflict);
    assert_eq!(run(RouteCompiler::compile(&repository, Some(&old))).unwrap_err().code, PlatformErrorCode::StateConflict);
    assert_eq!(run(RouteSnapshotSource::watch(&repository, old.generation)).unwrap(), vec![next.clone()]);
    assert!(run(RouteSnapshotSource::watch(&repository, next.generation)).unwrap().is_empty());
    assert_eq!(run(RouteSnapshotSource::watch(&repository, RouteGeneration(999))).unwrap_err().code, PlatformErrorCode::InvalidArgument);
    assert!(run(CompiledRouteStore::get(&repository, old.generation)).unwrap().is_none());
}

#[test]
fn restart_ignores_pending_but_rejects_corrupt_or_missing_complete_state() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let one = releases.add("one");
    let repository = open(&root, &releases);
    run(DeploymentStore::apply(&repository, deployment("blue", "alice", &one))).unwrap();
    let snapshot = run(RouteSnapshotSource::current(&repository)).unwrap();
    drop(repository);
    std::fs::write(root.0.join(".catalog.pending"), b"incomplete").unwrap();
    let repository = open(&root, &releases);
    assert_eq!(run(RouteSnapshotSource::current(&repository)).unwrap(), snapshot);
    assert!(!root.0.join(".catalog.pending").exists());
    drop(repository);
    let state = root.0.join(persistence::STATE_FILE);
    std::fs::write(&state, b"broken").unwrap();
    assert_eq!(run(DirectoryDeploymentRepository::open(root.0.clone(), releases.clone(), DirectoryDeploymentRepositoryConfig::default())).err().unwrap().code, PlatformErrorCode::CorruptArtifact);
    std::fs::remove_file(&state).unwrap();
    assert_eq!(run(DirectoryDeploymentRepository::open(root.0.clone(), releases, DirectoryDeploymentRepositoryConfig::default())).err().unwrap().code, PlatformErrorCode::CorruptArtifact);
}

#[test]
fn crash_boundaries_keep_disk_and_memory_on_complete_snapshots() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let one = releases.add("one");
    let two = releases.add("two");
    let repository = open(&root, &releases);
    run(DeploymentStore::apply(&repository, deployment("blue", "alice", &one))).unwrap();
    repository.fail_before_rename.store(true, Ordering::SeqCst);
    assert!(run(DeploymentStore::apply(&repository, deployment("blue", "alice", &two))).is_err());
    assert_eq!(repository.resolve(&target("alice", None), None).unwrap().release, one);
    drop(repository);
    let repository = open(&root, &releases);
    assert_eq!(repository.resolve(&target("alice", None), None).unwrap().release, one);
    repository.fail_parent_sync.store(true, Ordering::SeqCst);
    let failure = run(DeploymentStore::apply(&repository, deployment("blue", "alice", &two))).unwrap_err();
    assert_eq!(failure.message, "commit-durability-uncertain");
    assert_eq!(repository.resolve(&target("alice", None), None).unwrap().release, two);
    drop(repository);
    assert_eq!(open(&root, &releases).resolve(&target("alice", None), None).unwrap().release, two);
}

#[test]
fn root_ownership_limits_and_hot_path_are_explicit() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let one = releases.add("one");
    let repository = open(&root, &releases);
    assert_eq!(run(DirectoryDeploymentRepository::open(root.0.clone(), releases.clone(), DirectoryDeploymentRepositoryConfig::default())).err().unwrap().code, PlatformErrorCode::Unavailable);
    run(DeploymentStore::apply(&repository, deployment("blue", "alice", &one))).unwrap();
    let calls = releases.fetches.load(Ordering::Relaxed);
    for _ in 0..100 { repository.resolve(&target("alice", None), Some("key")).unwrap(); }
    assert_eq!(releases.fetches.load(Ordering::Relaxed), calls);
    let guard = repository.current.write().unwrap();
    assert_eq!(repository.resolve(&target("alice", None), None).unwrap_err().code, PlatformErrorCode::Unavailable);
    drop(guard);
    assert_eq!(repository.resolve(&target("alice", None), Some(&"x".repeat(4097))).unwrap_err().code, PlatformErrorCode::InvalidArgument);
    drop(repository);
    let mut config = DirectoryDeploymentRepositoryConfig::default();
    config.max_state_bytes = 1024;
    assert_eq!(run(DirectoryDeploymentRepository::open(root.0.clone(), releases, config)).err().unwrap().code, PlatformErrorCode::ResourceExhausted);
}

#[test]
fn concurrent_snapshot_replacement_never_exposes_half_a_batch() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let one = releases.add("one");
    let two = releases.add("two");
    let repository = open(&root, &releases);
    run(repository.apply_many(vec![deployment("blue", "alice", &one), deployment("green", "alice", &one)])).unwrap();
    let barrier = std::sync::Barrier::new(5);
    std::thread::scope(|scope| {
        for _ in 0..4 {
            let repository = &repository;
            let barrier = &barrier;
            scope.spawn(move || {
                barrier.wait();
                let mut completed = 0;
                while completed < 1000 {
                    match repository.pin() {
                        Ok(view) => {
                            let blue = view.resolve(&target("alice", Some("blue")), None).unwrap();
                            let green = view.resolve(&target("alice", Some("green")), None).unwrap();
                            assert_eq!(blue.release, green.release);
                            assert_eq!(blue.route_generation, green.route_generation);
                            completed += 1;
                        }
                        Err(failure) => assert_eq!(failure.code, PlatformErrorCode::Unavailable),
                    }
                }
            });
        }
        barrier.wait();
        for index in 0..20 {
            let release = if index % 2 == 0 { &two } else { &one };
            run(repository.apply_many(vec![deployment("blue", "alice", release), deployment("green", "alice", release)])).unwrap();
        }
    });
}

#[test]
fn tampered_complete_snapshot_and_generation_exhaustion_are_rejected() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let repository = open(&root, &releases);
    let exhausted = run(compiler::compile(BTreeMap::new(), RouteGeneration(u64::MAX), 0, releases.as_ref(), repository.config)).unwrap();
    repository.commit(RouteGeneration(0), exhausted).unwrap();
    assert_eq!(run(RouteCompiler::compile(&repository, None)).unwrap_err().code, PlatformErrorCode::StateConflict);
    let current = run(RouteSnapshotSource::current(&repository)).unwrap();
    assert_eq!(run(RouteCompiler::compile(&repository, Some(&current))).unwrap_err().code, PlatformErrorCode::ResourceExhausted);
    drop(repository);
    let path = root.0.join(persistence::STATE_FILE);
    let mut record: json::Value = json::from_slice(&std::fs::read(&path).unwrap()).unwrap();
    record["payload"]["snapshot"]["generation"] = json::json!(1);
    record["checksum"] = json::json!(content_digest(&json::to_vec(&record["payload"]).unwrap()).0);
    std::fs::write(path, json::to_vec(&record).unwrap()).unwrap();
    assert_eq!(run(DirectoryDeploymentRepository::open(root.0.clone(), releases, DirectoryDeploymentRepositoryConfig::default())).err().unwrap().code, PlatformErrorCode::CorruptArtifact);
}
