use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, RwLock};
use std::thread;

use latent_core::{
    BoxFuture, ContractId, DeploymentId, FunctionId, PlatformError, PlatformErrorCode,
    ReleaseDigest, ResourceBudget, RouteGeneration, ServiceId, TenantId,
};
use latent_manifest::{AvailabilityPolicy, DeploymentManifest, ObjectMetadata, PlacementPolicy};
use latent_routing::{
    InvocationTarget, RouteCompiler, RouteContract, RouteSnapshotPublisher, RouteSnapshotSource,
};
use tempfile::TempDir;

use super::compiler::{ReleaseDefinition, ReleaseInspector};
use super::fault_injection::{fail_once, FaultPoint};
use super::persistence;
use super::{
    platform_error, stable_fields, EmbeddedCatalogOptions, EmbeddedDeploymentCatalog,
    ROUTE_ANNOTATION_KEY,
};

#[derive(Default)]
struct FakeInspector {
    releases: RwLock<BTreeMap<ReleaseDigest, ReleaseDefinition>>,
}

impl FakeInspector {
    fn insert(&self, release: ReleaseDefinition) {
        self.releases
            .write()
            .expect("fake release lock")
            .insert(release.release.clone(), release);
    }
}

impl ReleaseInspector for FakeInspector {
    fn inspect<'a>(
        &'a self,
        digest: &'a ReleaseDigest,
    ) -> BoxFuture<'a, Result<ReleaseDefinition, PlatformError>> {
        Box::pin(async move {
            self.releases
                .read()
                .expect("fake release lock")
                .get(digest)
                .cloned()
                .ok_or_else(|| {
                    platform_error(
                        PlatformErrorCode::NotFound,
                        "missing-release",
                        "release is absent from the fake catalog",
                        stable_fields([("release_digest", digest.0.clone())]),
                    )
                })
        })
    }
}

#[tokio::test(flavor = "current_thread")]
async fn deployment_transactions_are_pinned_persistent_and_restart_stable() {
    let root = TempDir::new().expect("temporary catalog");
    let releases = Arc::new(FakeInspector::default());
    releases.insert(release("rel-a", None, "echo"));
    let catalog = open(root.path(), Arc::clone(&releases)).await;
    let deployment = deployment("dep-a", "tenant-a", "echo", "rel-a", 10_000, None);

    assert_eq!(
        catalog.apply_manifest(deployment.clone()).await.unwrap(),
        RouteGeneration(1)
    );
    assert_eq!(
        catalog.deployment(&deployment.id).unwrap(),
        Some(deployment.clone())
    );
    assert_eq!(
        catalog
            .deployments(Some(&TenantId("tenant-a".into())))
            .unwrap(),
        vec![deployment.clone()]
    );

    let pinned = catalog
        .resolve_target(&target("tenant-a", "echo", None), Some("order-7"))
        .unwrap();
    assert_eq!(pinned.route_generation, RouteGeneration(1));
    assert_eq!(pinned.release, ReleaseDigest("rel-a".into()));
    let revision = pinned.revision.clone();
    drop(catalog);

    let restarted = open(root.path(), Arc::clone(&releases)).await;
    assert_eq!(restarted.generation().unwrap(), RouteGeneration(1));
    let after_restart = restarted
        .resolve_target(&target("tenant-a", "echo", None), Some("order-7"))
        .unwrap();
    assert_eq!(after_restart.revision, revision);
    assert_eq!(after_restart.release, ReleaseDigest("rel-a".into()));

    assert_eq!(
        restarted.delete_manifest(&deployment.id).await.unwrap(),
        RouteGeneration(2)
    );
    assert_eq!(restarted.deployment(&deployment.id).unwrap(), None);
    let missing = restarted
        .resolve_target(&target("tenant-a", "echo", None), None)
        .unwrap_err();
    assert_error(
        &missing,
        PlatformErrorCode::RouteUnavailable,
        "route-not-found",
    );
}

#[tokio::test(flavor = "current_thread")]
async fn failed_apply_is_atomic_and_duplicate_ids_are_stable() {
    let root = TempDir::new().unwrap();
    let releases = Arc::new(FakeInspector::default());
    let catalog = open(root.path(), Arc::clone(&releases)).await;
    let missing = deployment("dep-a", "tenant-a", "echo", "missing", 10_000, None);

    let error = catalog.apply_manifest(missing.clone()).await.unwrap_err();
    assert_error(&error, PlatformErrorCode::NotFound, "missing-release");
    assert_eq!(catalog.generation().unwrap(), RouteGeneration(0));
    assert!(catalog.deployments(None).unwrap().is_empty());

    releases.insert(release("missing", None, "echo"));
    assert_eq!(
        catalog.apply_manifest(missing.clone()).await.unwrap(),
        RouteGeneration(1)
    );
    let duplicate = catalog.apply_manifest(missing).await.unwrap_err();
    assert_error(
        &duplicate,
        PlatformErrorCode::AlreadyExists,
        "duplicate-deployment-id",
    );
    assert_eq!(catalog.generation().unwrap(), RouteGeneration(1));

    let conflicting = deployment("dep-a", "tenant-b", "echo", "rel-a", 10_000, None);
    let error = catalog.apply_manifest(conflicting).await.unwrap_err();
    assert_error(
        &error,
        PlatformErrorCode::StateConflict,
        "deployment-identity-conflict",
    );
    assert_eq!(catalog.generation().unwrap(), RouteGeneration(1));
    assert_eq!(
        RouteSnapshotSource::watch(&catalog, RouteGeneration(0))
            .await
            .unwrap()
            .len(),
        1
    );
}

#[tokio::test(flavor = "current_thread")]
async fn tenant_default_and_named_routes_are_strictly_isolated() {
    let root = TempDir::new().unwrap();
    let releases = Arc::new(FakeInspector::default());
    releases.insert(release("rel-a", None, "echo"));
    releases.insert(release("rel-b", None, "echo"));
    releases.insert(release("rel-canary", None, "echo"));
    let catalog = open(root.path(), Arc::clone(&releases)).await;

    catalog
        .apply_manifest(deployment(
            "dep-a", "tenant-a", "echo", "rel-a", 10_000, None,
        ))
        .await
        .unwrap();
    catalog
        .apply_manifest(deployment(
            "dep-b", "tenant-b", "echo", "rel-b", 10_000, None,
        ))
        .await
        .unwrap();
    catalog
        .apply_manifest(deployment(
            "dep-canary",
            "tenant-a",
            "echo",
            "rel-canary",
            10_000,
            Some("canary"),
        ))
        .await
        .unwrap();

    assert_eq!(
        catalog
            .resolve_target(&target("tenant-a", "echo", None), None)
            .unwrap()
            .release,
        ReleaseDigest("rel-a".into())
    );
    assert_eq!(
        catalog
            .resolve_target(&target("tenant-b", "echo", None), None)
            .unwrap()
            .release,
        ReleaseDigest("rel-b".into())
    );
    assert_eq!(
        catalog
            .resolve_target(&target("tenant-a", "echo", Some("canary")), None)
            .unwrap()
            .release,
        ReleaseDigest("rel-canary".into())
    );

    let wrong_tenant = catalog
        .resolve_target(&target("tenant-c", "echo", None), None)
        .unwrap_err();
    assert_error(
        &wrong_tenant,
        PlatformErrorCode::RouteUnavailable,
        "route-not-found",
    );
    let wrong_route = catalog
        .resolve_target(&target("tenant-b", "echo", Some("canary")), None)
        .unwrap_err();
    assert_error(
        &wrong_route,
        PlatformErrorCode::RouteUnavailable,
        "route-not-found",
    );

    let mut wrong_function = target("tenant-a", "echo", None);
    wrong_function.function = FunctionId("missing".into());
    let mismatch = catalog.resolve_target(&wrong_function, None).unwrap_err();
    assert_error(
        &mismatch,
        PlatformErrorCode::IncompatibleContract,
        "contract-function-mismatch",
    );
}

#[tokio::test(flavor = "current_thread")]
async fn weighting_and_revision_identity_are_deterministic() {
    let first_root = TempDir::new().unwrap();
    let second_root = TempDir::new().unwrap();
    let releases = Arc::new(FakeInspector::default());
    releases.insert(release("rel-a", None, "echo"));
    releases.insert(release("rel-b", None, "echo"));
    let first = open(first_root.path(), Arc::clone(&releases)).await;
    let second = open(second_root.path(), Arc::clone(&releases)).await;
    let a = deployment("dep-a", "tenant-a", "echo", "rel-a", 3_000, None);
    let b = deployment("dep-b", "tenant-a", "echo", "rel-b", 7_000, None);

    first.apply_manifest(a.clone()).await.unwrap();
    first.apply_manifest(b.clone()).await.unwrap();
    second.apply_manifest(b.clone()).await.unwrap();
    second.apply_manifest(a.clone()).await.unwrap();

    let target = target("tenant-a", "echo", None);
    let mut seen = BTreeSet::new();
    for index in 0..2_000 {
        let key = format!("routing-key-{index}");
        let left = first.resolve_target(&target, Some(&key)).unwrap();
        let repeated = first.resolve_target(&target, Some(&key)).unwrap();
        let right = second.resolve_target(&target, Some(&key)).unwrap();
        assert_eq!(left.release, repeated.release);
        assert_eq!(left.revision, repeated.revision);
        assert_eq!(left.release, right.release);
        assert_eq!(left.revision, right.revision);
        seen.insert(left.release);
    }
    assert_eq!(
        seen.len(),
        2,
        "both positive weighted revisions must be selectable"
    );

    let before = first.resolve_target(&target, Some("identity-key")).unwrap();
    let mut changed = a;
    changed
        .metadata
        .labels
        .insert("configuration".into(), "v2".into());
    first.apply_manifest(changed).await.unwrap();
    let snapshot = first.snapshot().unwrap();
    let changed_revision = snapshot.services[0]
        .revisions
        .iter()
        .find(|revision| revision.release == ReleaseDigest("rel-a".into()))
        .unwrap();
    let previous_snapshot = second.snapshot().unwrap();
    let previous_revision = previous_snapshot.services[0]
        .revisions
        .iter()
        .find(|revision| revision.release == ReleaseDigest("rel-a".into()))
        .unwrap();
    assert_ne!(changed_revision.revision, previous_revision.revision);
    assert!(before.route_generation.0 < first.generation().unwrap().0);
}

#[tokio::test(flavor = "current_thread")]
async fn release_and_route_validation_returns_stable_errors() {
    let cases = [
        (
            "backend",
            ReleaseDefinition {
                wasm_component_backend: false,
                ..release("backend-rel", None, "echo")
            },
            "unsupported-execution-backend",
        ),
        (
            "state",
            ReleaseDefinition {
                stateless: false,
                ..release("state-rel", None, "echo")
            },
            "unsupported-state-model",
        ),
    ];
    for (name, release, kind) in cases {
        let root = TempDir::new().unwrap();
        let releases = Arc::new(FakeInspector::default());
        let digest = release.release.0.clone();
        releases.insert(release);
        let catalog = open(root.path(), Arc::clone(&releases)).await;
        let error = catalog
            .apply_manifest(deployment(name, "tenant-a", "echo", &digest, 10_000, None))
            .await
            .unwrap_err();
        assert_error(&error, PlatformErrorCode::InvalidArgument, kind);
    }

    let root = TempDir::new().unwrap();
    let releases = Arc::new(FakeInspector::default());
    releases.insert(release("rel-a", Some("tenant-b"), "echo"));
    let catalog = open(root.path(), Arc::clone(&releases)).await;
    let tenant_error = catalog
        .apply_manifest(deployment("dep", "tenant-a", "echo", "rel-a", 10_000, None))
        .await
        .unwrap_err();
    assert_eq!(error_kind(&tenant_error), Some("tenant-scope-conflict"));

    let root = TempDir::new().unwrap();
    let releases = Arc::new(FakeInspector::default());
    releases.insert(release("rel-a", None, "echo"));
    let catalog = open(root.path(), Arc::clone(&releases)).await;
    let invalid_weight = catalog
        .apply_manifest(deployment("dep", "tenant-a", "echo", "rel-a", 0, None))
        .await
        .unwrap_err();
    assert_error(
        &invalid_weight,
        PlatformErrorCode::InvalidArgument,
        "invalid-route-weight",
    );

    let mut too_large = deployment("dep", "tenant-a", "echo", "rel-a", 10_000, None);
    too_large.resources.memory_bytes = budget().memory_bytes + 1;
    let budget_error = catalog.apply_manifest(too_large).await.unwrap_err();
    assert_error(
        &budget_error,
        PlatformErrorCode::InvalidArgument,
        "deployment-budget-exceeds-release",
    );

    catalog
        .apply_manifest(deployment(
            "dep-a", "tenant-a", "echo", "rel-a", 6_000, None,
        ))
        .await
        .unwrap();
    let aggregate = catalog
        .apply_manifest(deployment(
            "dep-b", "tenant-a", "echo", "rel-a", 5_000, None,
        ))
        .await
        .unwrap_err();
    assert_error(
        &aggregate,
        PlatformErrorCode::InvalidArgument,
        "invalid-route-weight-total",
    );

    let mut incompatible = release("rel-b", None, "echo");
    incompatible.contracts = vec![RouteContract {
        contract: ContractId("other".into()),
        functions: vec![FunctionId("invoke".into())],
    }];
    releases.insert(incompatible);
    let contract_error = catalog
        .apply_manifest(deployment(
            "dep-b", "tenant-a", "echo", "rel-b", 4_000, None,
        ))
        .await
        .unwrap_err();
    assert_error(
        &contract_error,
        PlatformErrorCode::IncompatibleContract,
        "weighted-contract-surface-mismatch",
    );
}

#[tokio::test(flavor = "current_thread")]
async fn readers_only_observe_complete_old_or_new_generations() {
    let root = TempDir::new().unwrap();
    let releases = Arc::new(FakeInspector::default());
    releases.insert(release("rel-a", None, "echo"));
    releases.insert(release("rel-b", None, "echo"));
    let catalog = open(root.path(), Arc::clone(&releases)).await;
    catalog
        .apply_manifest(deployment("dep", "tenant-a", "echo", "rel-a", 10_000, None))
        .await
        .unwrap();

    let stop = Arc::new(AtomicBool::new(false));
    let mut readers = Vec::new();
    for _ in 0..8 {
        let catalog = catalog.clone();
        let stop = Arc::clone(&stop);
        readers.push(thread::spawn(move || {
            let target = target("tenant-a", "echo", None);
            let mut observations = 0_usize;
            while !stop.load(Ordering::Acquire) {
                let resolved = catalog.resolve_target(&target, Some("stable-key")).unwrap();
                assert!(
                    (resolved.route_generation == RouteGeneration(1)
                        && resolved.release == ReleaseDigest("rel-a".into()))
                        || (resolved.route_generation == RouteGeneration(2)
                            && resolved.release == ReleaseDigest("rel-b".into()))
                );
                observations += 1;
            }
            observations
        }));
    }

    let replacement = deployment("dep", "tenant-a", "echo", "rel-b", 10_000, None);
    assert_eq!(
        catalog.apply_manifest(replacement).await.unwrap(),
        RouteGeneration(2)
    );
    for _ in 0..100 {
        tokio::task::yield_now().await;
    }
    stop.store(true, Ordering::Release);
    assert!(
        readers
            .into_iter()
            .map(|reader| reader.join().unwrap())
            .sum::<usize>()
            > 0
    );
    assert_eq!(
        catalog
            .resolve_target(&target("tenant-a", "echo", None), None)
            .unwrap()
            .release,
        ReleaseDigest("rel-b".into())
    );
}

#[tokio::test(flavor = "current_thread")]
async fn marker_directory_sync_failure_after_publication_returns_committed_state() {
    exercise_post_commit_fault(FaultPoint::CommitDirectorySyncAfterMarkerRename).await;
}

#[tokio::test(flavor = "current_thread")]
async fn in_memory_publication_failure_after_marker_is_reconciled() {
    exercise_post_commit_fault(FaultPoint::ReplacePublished).await;
}

#[tokio::test(flavor = "current_thread")]
async fn maintenance_reclaims_state_and_marker_temporaries() {
    let root = TempDir::new().unwrap();
    let releases = Arc::new(FakeInspector::default());
    releases.insert(release("rel-a", None, "echo"));
    releases.insert(release("rel-b", None, "echo"));
    let catalog = open(root.path(), Arc::clone(&releases)).await;
    let first = deployment("dep", "tenant-a", "echo", "rel-a", 10_000, None);
    catalog.apply_manifest(first.clone()).await.unwrap();

    let valid_state = root.path().join("generations/00000000000000000001.json");
    let valid_marker = root.path().join("commits/00000000000000000001.commit");
    let state_temporary = root
        .path()
        .join("generations/.00000000000000000002.json.tmp-crash");
    let marker_temporary = root
        .path()
        .join("commits/.00000000000000000002.commit.tmp-crash");
    fs::write(&state_temporary, b"interrupted state").unwrap();
    fs::write(&marker_temporary, b"interrupted marker").unwrap();

    let replacement = deployment("dep", "tenant-a", "echo", "rel-b", 10_000, None);
    assert_eq!(
        catalog.apply_manifest(replacement.clone()).await.unwrap(),
        RouteGeneration(2)
    );

    assert!(!state_temporary.exists());
    assert!(!marker_temporary.exists());
    assert!(valid_state.exists());
    assert!(valid_marker.exists());
    assert_persisted_state(root.path(), RouteGeneration(1), &first);
    assert_persisted_state(root.path(), RouteGeneration(2), &replacement);
}

#[tokio::test(flavor = "current_thread")]
async fn compiler_publisher_replay_retention_and_orphan_recovery_are_complete() {
    let root = TempDir::new().unwrap();
    let releases = Arc::new(FakeInspector::default());
    releases.insert(release("rel-a", None, "echo"));
    let options = EmbeddedCatalogOptions {
        retained_generations: 2,
        ..EmbeddedCatalogOptions::default()
    };
    let catalog = EmbeddedDeploymentCatalog::open_with_release_inspector(
        root.path(),
        releases.clone(),
        options.clone(),
    )
    .await
    .unwrap();
    catalog
        .apply_manifest(deployment("dep", "tenant-a", "echo", "rel-a", 10_000, None))
        .await
        .unwrap();

    let current = RouteSnapshotSource::current(&catalog).await.unwrap();
    let compiled = RouteCompiler::compile(&catalog, Some(&current))
        .await
        .unwrap();
    assert_eq!(compiled.generation, RouteGeneration(2));
    fail_once(root.path(), FaultPoint::ReplacePublished);
    RouteSnapshotPublisher::publish(&catalog, compiled)
        .await
        .unwrap();
    let replay = RouteSnapshotSource::watch(&catalog, RouteGeneration(0))
        .await
        .unwrap();
    assert_eq!(
        replay
            .iter()
            .map(|snapshot| snapshot.generation)
            .collect::<Vec<_>>(),
        vec![RouteGeneration(1), RouteGeneration(2)]
    );

    let current = catalog.snapshot().unwrap();
    let next = RouteCompiler::compile(&catalog, Some(&current))
        .await
        .unwrap();
    RouteSnapshotPublisher::publish(&catalog, next)
        .await
        .unwrap();
    let retained = RouteSnapshotSource::watch(&catalog, RouteGeneration(0))
        .await
        .unwrap();
    assert_eq!(
        retained
            .iter()
            .map(|snapshot| snapshot.generation)
            .collect::<Vec<_>>(),
        vec![RouteGeneration(2), RouteGeneration(3)]
    );

    let stale = catalog.snapshot().unwrap();
    let error = RouteSnapshotPublisher::publish(&catalog, stale)
        .await
        .unwrap_err();
    assert_error(
        &error,
        PlatformErrorCode::StateConflict,
        "non-monotonic-route-generation",
    );

    let orphan = root.path().join("generations/00000000000000000004.json");
    let state_temporary = root
        .path()
        .join("generations/.00000000000000000004.json.tmp-crash");
    let marker_temporary = root
        .path()
        .join("commits/.00000000000000000004.commit.tmp-crash");
    fs::write(&orphan, b"incomplete").unwrap();
    fs::write(&state_temporary, b"interrupted state").unwrap();
    fs::write(&marker_temporary, b"interrupted marker").unwrap();
    drop(catalog);
    let restarted =
        EmbeddedDeploymentCatalog::open_with_release_inspector(root.path(), releases, options)
            .await
            .unwrap();
    assert_eq!(restarted.generation().unwrap(), RouteGeneration(3));
    assert!(!orphan.exists());
    assert!(!state_temporary.exists());
    assert!(!marker_temporary.exists());
    assert!(root
        .path()
        .join("generations/00000000000000000003.json")
        .exists());
    assert!(root
        .path()
        .join("commits/00000000000000000003.commit")
        .exists());
}

async fn exercise_post_commit_fault(point: FaultPoint) {
    let root = TempDir::new().unwrap();
    let releases = Arc::new(FakeInspector::default());
    releases.insert(release("rel-a", None, "echo"));
    releases.insert(release("rel-b", None, "echo"));
    let catalog = open(root.path(), Arc::clone(&releases)).await;
    let first = deployment("dep", "tenant-a", "echo", "rel-a", 10_000, None);

    fail_once(root.path(), point);
    assert_eq!(
        catalog.apply_manifest(first.clone()).await.unwrap(),
        RouteGeneration(1)
    );
    assert_catalog_state(&catalog, RouteGeneration(1), &first);
    assert_persisted_state(root.path(), RouteGeneration(1), &first);

    let replacement = deployment("dep", "tenant-a", "echo", "rel-b", 10_000, None);
    assert_eq!(
        catalog.apply_manifest(replacement.clone()).await.unwrap(),
        RouteGeneration(2)
    );
    assert_catalog_state(&catalog, RouteGeneration(2), &replacement);
    assert_persisted_state(root.path(), RouteGeneration(1), &first);
    assert_persisted_state(root.path(), RouteGeneration(2), &replacement);

    drop(catalog);
    let restarted = open(root.path(), releases).await;
    assert_catalog_state(&restarted, RouteGeneration(2), &replacement);
    assert_persisted_state(root.path(), RouteGeneration(1), &first);
    assert_persisted_state(root.path(), RouteGeneration(2), &replacement);
}

fn assert_catalog_state(
    catalog: &EmbeddedDeploymentCatalog,
    generation: RouteGeneration,
    expected: &DeploymentManifest,
) {
    assert_eq!(catalog.generation().unwrap(), generation);
    assert_eq!(catalog.snapshot().unwrap().generation, generation);
    assert_eq!(
        catalog.deployment(&expected.id).unwrap(),
        Some(expected.clone())
    );
    let resolved = catalog
        .resolve_target(&target("tenant-a", "echo", None), Some("post-commit-key"))
        .unwrap();
    assert_eq!(resolved.route_generation, generation);
    assert_eq!(resolved.release, expected.release.clone());
}

fn assert_persisted_state(
    root: &std::path::Path,
    generation: RouteGeneration,
    expected: &DeploymentManifest,
) {
    let persisted =
        persistence::load_generation(root, generation, &EmbeddedCatalogOptions::default())
            .unwrap()
            .expect("retained generation");
    let (deployments, snapshot) = persisted.into_domain().unwrap();
    assert_eq!(snapshot.generation, generation);
    assert_eq!(deployments.get(&expected.id), Some(expected));
}

async fn open(root: &std::path::Path, releases: Arc<FakeInspector>) -> EmbeddedDeploymentCatalog {
    EmbeddedDeploymentCatalog::open_with_release_inspector(
        root,
        releases,
        EmbeddedCatalogOptions::default(),
    )
    .await
    .expect("open embedded catalog")
}

fn deployment(
    id: &str,
    tenant: &str,
    service: &str,
    release: &str,
    weight: u16,
    route: Option<&str>,
) -> DeploymentManifest {
    let mut annotations = BTreeMap::new();
    if let Some(route) = route {
        annotations.insert(ROUTE_ANNOTATION_KEY.to_owned(), route.to_owned());
    }
    DeploymentManifest {
        api_version: "latent.dev/v1alpha1".into(),
        id: DeploymentId(id.into()),
        metadata: ObjectMetadata {
            name: id.into(),
            tenant: Some(TenantId(tenant.into())),
            namespace: Some("default".into()),
            labels: BTreeMap::new(),
            annotations,
        },
        service: ServiceId(service.into()),
        release: ReleaseDigest(release.into()),
        route_weight: weight,
        grants: Vec::new(),
        resources: budget(),
        availability: AvailabilityPolicy {
            minimum_cached_copies: 1,
            minimum_zones: 1,
        },
        placement: PlacementPolicy {
            trust_class: "trusted".into(),
            architectures: vec!["x86_64".into()],
            regions: Vec::new(),
            zones: Vec::new(),
            required_features: Vec::new(),
        },
    }
}

fn release(digest: &str, tenant: Option<&str>, service: &str) -> ReleaseDefinition {
    ReleaseDefinition {
        release: ReleaseDigest(digest.into()),
        tenant: tenant.map(|tenant| TenantId(tenant.into())),
        namespace: Some("default".into()),
        service_name: service.into(),
        wasm_component_backend: true,
        stateless: true,
        contracts: vec![RouteContract {
            contract: ContractId("echo".into()),
            functions: vec![FunctionId("invoke".into())],
        }],
        resource_ceiling: budget(),
    }
}

fn target(tenant: &str, service: &str, route: Option<&str>) -> InvocationTarget {
    InvocationTarget {
        tenant: TenantId(tenant.into()),
        service: ServiceId(service.into()),
        contract: ContractId("echo".into()),
        function: FunctionId("invoke".into()),
        route: route.map(str::to_owned),
    }
}

fn budget() -> ResourceBudget {
    ResourceBudget {
        cpu_fuel: 1_000_000,
        memory_bytes: 64 * 1024 * 1024,
        wall_time_limit_millis: Some(1_000),
        child_calls: 16,
        outbound_requests: 16,
        state_read_bytes: 0,
        state_write_bytes: 0,
        blob_read_bytes: 1024,
        blob_write_bytes: 1024,
        log_bytes: 64 * 1024,
        effect_count: 16,
    }
}

fn assert_error(error: &PlatformError, code: PlatformErrorCode, kind: &str) {
    assert_eq!(error.code, code);
    assert_eq!(error_kind(error), Some(kind));
}

fn error_kind(error: &PlatformError) -> Option<&str> {
    error.details.first().map(|detail| detail.kind.as_str())
}
