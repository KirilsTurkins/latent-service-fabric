use std::collections::BTreeMap;
use std::sync::{Arc, RwLock};

use latent_core::{
    BindingId, BoxFuture, ContractId, DeploymentId, FunctionId, PlatformError, PlatformErrorCode,
    ReleaseDigest, ResourceBudget, RevisionId, RouteGeneration, RouteId, ServiceId, TenantId,
};
use latent_manifest::{
    AvailabilityPolicy, BindingMode, DeploymentManifest, ObjectMetadata, PlacementPolicy,
};
use latent_routing::{
    BindingRoute, InvocationTarget, RevisionRoute, RouteContract, RouteSnapshot, ServiceRoute,
};
use tempfile::TempDir;

use crate::{CompiledRouteStore, DeploymentStore, TenantDeploymentStore};

use super::compiler::{snapshot_digest, ReleaseDefinition, ReleaseInspector, RouteIndex};
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
async fn namespace_identity_and_release_scope_are_enforced() {
    let root = TempDir::new().unwrap();
    let releases = Arc::new(FakeInspector::default());
    releases.insert(release("rel-default", None, Some("default"), "echo"));
    releases.insert(release("rel-other", None, Some("other"), "echo"));
    let catalog = open(root.path(), Arc::clone(&releases)).await;

    catalog
        .apply_manifest(deployment(
            "dep-a",
            "tenant-a",
            Some("default"),
            "echo",
            "rel-default",
            10_000,
            None,
        ))
        .await
        .unwrap();

    let mixed = catalog
        .apply_manifest(deployment(
            "dep-b",
            "tenant-a",
            Some("other"),
            "echo",
            "rel-other",
            10_000,
            Some("preview"),
        ))
        .await
        .unwrap_err();
    assert_error(
        &mixed,
        PlatformErrorCode::StateConflict,
        "namespace-route-identity-conflict",
    );

    let moved = catalog
        .apply_manifest(deployment(
            "dep-a",
            "tenant-a",
            Some("other"),
            "echo",
            "rel-other",
            10_000,
            None,
        ))
        .await
        .unwrap_err();
    assert_error(
        &moved,
        PlatformErrorCode::StateConflict,
        "deployment-identity-conflict",
    );
    assert_eq!(catalog.generation().unwrap(), RouteGeneration(1));

    let scoped_root = TempDir::new().unwrap();
    let scoped_releases = Arc::new(FakeInspector::default());
    scoped_releases.insert(release("rel-scoped", None, Some("default"), "echo"));
    let scoped_catalog = open(scoped_root.path(), Arc::clone(&scoped_releases)).await;
    let namespace_error = scoped_catalog
        .apply_manifest(deployment(
            "dep-unscoped",
            "tenant-a",
            None,
            "echo",
            "rel-scoped",
            10_000,
            None,
        ))
        .await
        .unwrap_err();
    assert_error(
        &namespace_error,
        PlatformErrorCode::StateConflict,
        "namespace-scope-conflict",
    );

    let tenant_root = TempDir::new().unwrap();
    let tenant_releases = Arc::new(FakeInspector::default());
    tenant_releases.insert(release(
        "rel-tenant",
        Some("tenant-b"),
        Some("default"),
        "echo",
    ));
    let tenant_catalog = open(tenant_root.path(), Arc::clone(&tenant_releases)).await;
    let tenant_error = tenant_catalog
        .apply_manifest(deployment(
            "dep-tenant",
            "tenant-a",
            Some("default"),
            "echo",
            "rel-tenant",
            10_000,
            None,
        ))
        .await
        .unwrap_err();
    assert_error(
        &tenant_error,
        PlatformErrorCode::StateConflict,
        "tenant-scope-conflict",
    );
}

#[tokio::test(flavor = "current_thread")]
async fn route_canonicalization_is_shared_by_lookup_and_weighting() {
    let root = TempDir::new().unwrap();
    let releases = Arc::new(FakeInspector::default());
    releases.insert(release("rel-a", None, Some("default"), "echo"));
    releases.insert(release("rel-b", None, Some("default"), "echo"));
    let catalog = open(root.path(), Arc::clone(&releases)).await;

    catalog
        .apply_manifest(deployment(
            "dep-a",
            "tenant-a",
            Some("default"),
            "echo",
            "rel-a",
            3_000,
            Some("preview"),
        ))
        .await
        .unwrap();
    catalog
        .apply_manifest(deployment(
            "dep-b",
            "tenant-a",
            Some("default"),
            "echo",
            "rel-b",
            7_000,
            Some("preview"),
        ))
        .await
        .unwrap();

    let canonical = target("tenant-a", "echo", Some("preview"));
    let padded = target("tenant-a", "echo", Some(" preview "));
    for index in 0..2_000 {
        let routing_key = format!("routing-key-{index}");
        let left = catalog
            .resolve_target(&canonical, Some(&routing_key))
            .unwrap();
        let right = catalog.resolve_target(&padded, Some(&routing_key)).unwrap();
        assert_eq!(left.revision, right.revision);
        assert_eq!(left.release, right.release);
        assert_eq!(right.target.route.as_deref(), Some("preview"));
    }

    let whitespace = catalog
        .resolve_target(&target("tenant-a", "echo", Some("   ")), None)
        .unwrap_err();
    assert_error(
        &whitespace,
        PlatformErrorCode::InvalidArgument,
        "invalid-route-name",
    );
}

#[tokio::test(flavor = "current_thread")]
async fn original_control_store_ports_remain_available() {
    let root = TempDir::new().unwrap();
    let releases = Arc::new(FakeInspector::default());
    releases.insert(release("rel-a", None, Some("default"), "echo"));
    let catalog = open(root.path(), Arc::clone(&releases)).await;
    let manifest = deployment(
        "dep-a",
        "tenant-a",
        Some("default"),
        "echo",
        "rel-a",
        10_000,
        None,
    );

    DeploymentStore::apply(&catalog, manifest.clone())
        .await
        .unwrap();
    assert_eq!(
        DeploymentStore::list(&catalog).await.unwrap(),
        vec![manifest.clone()]
    );
    assert_eq!(
        TenantDeploymentStore::list_for_tenant(&catalog, &TenantId("tenant-a".into()))
            .await
            .unwrap(),
        vec![manifest]
    );
    assert!(CompiledRouteStore::get(&catalog, RouteGeneration(1))
        .await
        .unwrap()
        .is_some());
}

#[test]
fn route_index_rejects_cross_route_namespace_mixing() {
    let mut first_attributes = BTreeMap::new();
    first_attributes.insert("latent.dev/namespace".into(), "default".into());
    let mut second_attributes = BTreeMap::new();
    second_attributes.insert("latent.dev/namespace".into(), "other".into());
    let contract = route_contract();

    let mut snapshot = RouteSnapshot {
        generation: RouteGeneration(1),
        generated_at_unix_millis: 1,
        snapshot_digest: String::new(),
        services: vec![
            ServiceRoute {
                id: RouteId("route-default".into()),
                tenant: TenantId("tenant-a".into()),
                service: ServiceId("echo".into()),
                route: None,
                revisions: vec![RevisionRoute {
                    revision: RevisionId("revision-default".into()),
                    release: ReleaseDigest("release-default".into()),
                    weight: 10_000,
                    contracts: vec![contract.clone()],
                    attributes: first_attributes,
                }],
            },
            ServiceRoute {
                id: RouteId("route-preview".into()),
                tenant: TenantId("tenant-a".into()),
                service: ServiceId("echo".into()),
                route: Some("preview".into()),
                revisions: vec![RevisionRoute {
                    revision: RevisionId("revision-preview".into()),
                    release: ReleaseDigest("release-preview".into()),
                    weight: 10_000,
                    contracts: vec![contract],
                    attributes: second_attributes,
                }],
            },
        ],
        bindings: Vec::new(),
        policy_digests: Vec::new(),
    };
    snapshot.snapshot_digest = snapshot_digest(&snapshot);

    let error = RouteIndex::build(Arc::new(snapshot)).unwrap_err();
    assert_error(
        &error,
        PlatformErrorCode::CorruptArtifact,
        "compiled-namespace-route-identity-conflict",
    );
}

#[test]
#[allow(clippy::too_many_lines)]
fn checked_in_route_snapshot_example_has_a_runtime_valid_digest() {
    const EXPECTED_DIGEST: &str =
        "blake3:21e36fc95778961415948d37de370a5507da209d42e8317d2cbcff7914fb394d";

    let mut stable_attributes = BTreeMap::new();
    stable_attributes.insert("latent.dev/deployment-id".into(), "echo-stable".into());
    stable_attributes.insert("latent.dev/trust-class".into(), "trusted".into());
    let mut canary_attributes = BTreeMap::new();
    canary_attributes.insert("latent.dev/deployment-id".into(), "echo-canary".into());
    canary_attributes.insert("latent.dev/trust-class".into(), "trusted".into());
    let mut preview_attributes = BTreeMap::new();
    preview_attributes.insert("latent.dev/deployment-id".into(), "echo-preview".into());
    preview_attributes.insert("latent.dev/route".into(), "preview".into());
    preview_attributes.insert("latent.dev/trust-class".into(), "trusted".into());

    let contract = RouteContract {
        contract: ContractId("examples.echo.v1".into()),
        functions: vec![FunctionId("invoke".into())],
    };
    let snapshot = RouteSnapshot {
        generation: RouteGeneration(7),
        generated_at_unix_millis: 1_788_120_000_000,
        snapshot_digest: EXPECTED_DIGEST.into(),
        services: vec![
            ServiceRoute {
                id: RouteId(
                    "route-blake3:2ec8f3104f3f69ae754688ca1ac51a64d65e77dff1a0e29e8c5b34510aa56ec5"
                        .into(),
                ),
                tenant: TenantId("examples".into()),
                service: ServiceId("echo".into()),
                route: None,
                revisions: vec![
                    RevisionRoute {
                        revision: RevisionId(
                            "rev-blake3:18f504a3776e2222678cf99e2a2d56e95b9534771f3c6d1cb0961069114a1818"
                                .into(),
                        ),
                        release: ReleaseDigest(
                            "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
                                .into(),
                        ),
                        weight: 9_000,
                        contracts: vec![contract.clone()],
                        attributes: stable_attributes,
                    },
                    RevisionRoute {
                        revision: RevisionId(
                            "rev-blake3:ea792412353369465157507ff0b2906249fb14d6b5b810feea03e3dfaa924c3d"
                                .into(),
                        ),
                        release: ReleaseDigest(
                            "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
                                .into(),
                        ),
                        weight: 1_000,
                        contracts: vec![contract.clone()],
                        attributes: canary_attributes,
                    },
                ],
            },
            ServiceRoute {
                id: RouteId(
                    "route-blake3:3e1ff659985064ab785a66d3c8ff8aef7a7ffb611994e762403ed89f4a74f684"
                        .into(),
                ),
                tenant: TenantId("examples".into()),
                service: ServiceId("echo".into()),
                route: Some("preview".into()),
                revisions: vec![RevisionRoute {
                    revision: RevisionId(
                        "rev-blake3:3333333333333333333333333333333333333333333333333333333333333333"
                            .into(),
                    ),
                    release: ReleaseDigest(
                        "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
                            .into(),
                    ),
                    weight: 10_000,
                    contracts: vec![contract],
                    attributes: preview_attributes,
                }],
            },
        ],
        bindings: vec![BindingRoute {
    id: BindingId("examples:gateway-to-echo".into()),
    consumer_tenant: TenantId("examples".into()),
    consumer_service: ServiceId("gateway".into()),
    imported_contract: ContractId("examples.echo.v1".into()),
    provider_tenant: TenantId("examples".into()),
    provider_service: ServiceId("echo".into()),
    provider_contract: ContractId("examples.echo.v1".into()),
    mode: BindingMode::Auto,
    policy_digest:
        "sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
            .into(),
}],
policy_digests: vec![
    "sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
        .into(),
],
    };

    assert_eq!(snapshot_digest(&snapshot), EXPECTED_DIGEST);
    RouteIndex::build(Arc::new(snapshot)).unwrap();

    let example = include_str!("../../../../examples/route-snapshot.json");
    let parsed: serde_json::Value = serde_json::from_str(example).unwrap();
    assert_eq!(parsed["snapshotDigest"], EXPECTED_DIGEST);
    assert_eq!(parsed["bindings"][0]["consumerTenant"], "examples");
    assert_eq!(parsed["bindings"][0]["providerTenant"], "examples");
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
    namespace: Option<&str>,
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
            namespace: namespace.map(str::to_owned),
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

fn release(
    digest: &str,
    tenant: Option<&str>,
    namespace: Option<&str>,
    service: &str,
) -> ReleaseDefinition {
    ReleaseDefinition {
        release: ReleaseDigest(digest.into()),
        tenant: tenant.map(|tenant| TenantId(tenant.into())),
        namespace: namespace.map(str::to_owned),
        service_name: service.into(),
        wasm_component_backend: true,
        stateless: true,
        contracts: vec![route_contract()],
        resource_ceiling: budget(),
    }
}

fn route_contract() -> RouteContract {
    RouteContract {
        contract: ContractId("echo".into()),
        functions: vec![FunctionId("invoke".into())],
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
        blob_read_bytes: 1_024,
        blob_write_bytes: 1_024,
        log_bytes: 64 * 1_024,
        effect_count: 16,
    }
}

fn assert_error(error: &PlatformError, code: PlatformErrorCode, kind: &str) {
    assert_eq!(error.code, code);
    assert_eq!(
        error.details.first().map(|detail| detail.kind.as_str()),
        Some(kind)
    );
}
