use std::sync::Arc;

use latent_artifacts::{
    ArtifactRepository, DirectoryArtifactRepository, DirectoryArtifactRepositoryConfig,
    LifecycleScope, ReleaseActor, ReleaseActorKind, ReleaseLifecycleAction, ReleaseLifecycleReason,
    ReleaseMutationContext, ReleaseOperationPrecondition,
};
use latent_core::{DeploymentId, ReleaseDigest};
use latent_manifest::{RuntimeCompatibilityProfile, RuntimeRequirement};
use latent_routing::{RevisionPolicySource, RouteResolver};

use super::fixtures::*;
use crate::DeploymentStore;

pub(super) fn profile(version: &str) -> Arc<RuntimeCompatibilityProfile> {
    Arc::new(
        RuntimeCompatibilityProfile::new(
            "wasmtime",
            version,
            "x86_64-unknown-linux-gnu",
            &["x86_64.sse2"],
            65536,
            1000,
        )
        .unwrap(),
    )
}

pub(super) fn revoke(repository: &DirectoryArtifactRepository, release: &ReleaseDigest) {
    run(repository.change_release_lifecycle(
        ReleaseMutationContext {
            scope: LifecycleScope::LocalUnscoped,
            actor: ReleaseActor {
                subject: "lifecycle-test".into(),
                kind: ReleaseActorKind::Host,
            },
            operation: Some(ReleaseOperationPrecondition {
                operation_id: "revoke-test".into(),
                expected_generation: 1,
            }),
        },
        release,
        ReleaseLifecycleAction::Revoke,
        ReleaseLifecycleReason::OperatorRevocation,
        &mut |_| Ok(()),
    ))
    .unwrap();
}

struct Fixture {
    store: Store,
    releases: Arc<DirectoryArtifactRepository>,
    first: ReleaseDigest,
    second: ReleaseDigest,
    roots: [TempRoot; 2],
}
impl Fixture {
    fn new() -> Self {
        let roots = [TempRoot::new(), TempRoot::new()];
        let releases = Arc::new(
            DirectoryArtifactRepository::open(
                &roots[0].0,
                DirectoryArtifactRepositoryConfig::default(),
            )
            .unwrap(),
        );
        let first = run(releases.publish(artifact("lifecycle-one")))
            .unwrap()
            .release_digest;
        let second = run(releases.publish(artifact("lifecycle-two")))
            .unwrap()
            .release_digest;
        let store = run(Store::open_with_catalog(
            &roots[1].0,
            releases.clone(),
            Limits::default(),
            releases.lifecycle_authority(),
            profile("47.0.3"),
        ))
        .unwrap();
        Self {
            store,
            releases,
            first,
            second,
            roots,
        }
    }
}

#[test]
fn local_revocation_denies_pins_and_keeps_unrelated_management_available() {
    let fixture = Fixture::new();
    let blue = deployment("blue", "alice", &fixture.first);
    run(fixture.store.apply(blue.clone())).unwrap();
    let old = fixture.store.pin().unwrap();
    let selected = old.resolve(&target("alice", Some("blue")), None).unwrap();
    revoke(&fixture.releases, &fixture.first);
    assert_code(
        old.resolve(&target("alice", Some("blue")), None),
        Code::PermissionDenied,
    );
    assert_code(old.admission_policy(&selected), Code::PermissionDenied);
    assert_code(
        run(fixture.store.apply(blue.clone())),
        Code::PermissionDenied,
    );
    assert_eq!(fixture.store.generation().0, 1);

    // An unchanged denied row may survive a different object's control update.
    run(fixture
        .store
        .apply(deployment("green", "alice", &fixture.second)))
    .unwrap();
    assert_eq!(fixture.store.generation().0, 2);
    assert_code(
        fixture.store.resolve(&target("alice", Some("blue")), None),
        Code::PermissionDenied,
    );
    assert_eq!(
        fixture
            .store
            .resolve(&target("alice", Some("green")), None)
            .unwrap()
            .release,
        fixture.second
    );
    assert_eq!(
        run(DeploymentStore::get(&fixture.store, &blue.id)).unwrap(),
        Some(blue.clone())
    );
    run(fixture.store.delete(&blue.id)).unwrap();
    assert_eq!(fixture.store.generation().0, 3);
}

#[test]
fn completed_local_compilation_cannot_publish_after_lifecycle_revocation() {
    let fixture = Fixture::new();
    run(fixture
        .store
        .apply(deployment("blue", "alice", &fixture.first)))
    .unwrap();
    let previous = fixture.store.read_catalog();
    let mut work = super::super::observation::Work::default();
    let owner = fixture.releases.lifecycle_authority();
    let profile = profile("47.0.3");
    let candidate = run(super::super::compiler::compile_versioned_with_runtime(
        previous.deployments.clone(),
        previous.versions.clone(),
        latent_core::RouteGeneration(2),
        100,
        fixture.releases.as_ref(),
        Limits::default(),
        Some(&previous),
        &mut work,
        Some(&profile),
        Some(&owner),
    ))
    .unwrap();
    let bytes = std::fs::read(fixture.roots[1].0.join("catalog.json")).unwrap();
    revoke(&fixture.releases, &fixture.first);
    assert_code(
        fixture
            .store
            .commit(latent_core::RouteGeneration(1), candidate, &mut work),
        Code::PermissionDenied,
    );
    assert_eq!(fixture.store.generation().0, 1);
    assert_eq!(
        std::fs::read(fixture.roots[1].0.join("catalog.json")).unwrap(),
        bytes
    );
    assert!(!fixture.roots[1].0.join(".catalog.pending").exists());
}

#[test]
fn revoked_desired_history_reopens_inactive_and_can_be_removed() {
    let Fixture {
        store,
        releases,
        first,
        roots,
        ..
    } = Fixture::new();
    let desired = deployment("blue", "alice", &first);
    run(store.apply(desired.clone())).unwrap();
    revoke(&releases, &first);
    let bytes = std::fs::read(roots[1].0.join("catalog.json")).unwrap();
    drop(store);
    let store = run(Store::open_with_catalog(
        &roots[1].0,
        releases.clone(),
        Limits::default(),
        releases.lifecycle_authority(),
        profile("47.0.3"),
    ))
    .unwrap();
    assert_eq!(store.generation().0, 1);
    assert_eq!(
        std::fs::read(roots[1].0.join("catalog.json")).unwrap(),
        bytes
    );
    assert_eq!(run(store.list()).unwrap(), vec![desired.clone()]);
    assert_code(
        store.resolve(&target("alice", None), None),
        Code::PermissionDenied,
    );
    assert_code(run(store.apply(desired.clone())), Code::PermissionDenied);
    run(store.delete(&desired.id)).unwrap();
    assert_eq!(store.generation().0, 2);
}

#[test]
fn inactive_history_never_hides_component_corruption() {
    let Fixture {
        store,
        releases,
        first,
        roots,
        ..
    } = Fixture::new();
    run(store.apply(deployment("blue", "alice", &first))).unwrap();
    revoke(&releases, &first);
    drop(store);
    let file = roots[0]
        .0
        .join("releases")
        .join(first.0.strip_prefix("sha256:").unwrap())
        .join("component.wasm");
    std::fs::write(file, b"tampered").unwrap();
    assert_code(
        run(Store::open_with_catalog(
            &roots[1].0,
            releases.clone(),
            Limits::default(),
            releases.lifecycle_authority(),
            profile("47.0.3"),
        )),
        Code::CorruptArtifact,
    );
}

#[test]
fn catalog_bound_store_rejects_foreign_owner_and_unsealed_metadata() {
    let fixture = Fixture::new();
    let other_root = TempRoot::new();
    let other = DirectoryArtifactRepository::open(
        &other_root.0,
        DirectoryArtifactRepositoryConfig::default(),
    )
    .unwrap();
    let route_root = TempRoot::new();
    let wrong = run(Store::open_with_catalog(
        &route_root.0,
        fixture.releases.clone(),
        Limits::default(),
        other.lifecycle_authority(),
        profile("47.0.3"),
    ))
    .unwrap();
    assert_code(
        run(wrong.apply(deployment("blue", "alice", &fixture.first))),
        Code::PermissionDenied,
    );
    assert_eq!(wrong.generation().0, 0);
    let forged = Arc::new(Releases::default());
    let digest = forged.add("unsealed");
    let forged_root = TempRoot::new();
    let wrong = run(Store::open_with_catalog(
        &forged_root.0,
        forged,
        Limits::default(),
        fixture.releases.lifecycle_authority(),
        profile("47.0.3"),
    ))
    .unwrap();
    assert_code(
        run(wrong.apply(deployment("blue", "alice", &digest))),
        Code::PermissionDenied,
    );
    assert_eq!(wrong.generation().0, 0);
}

#[test]
fn incompatible_host_recovers_static_denial_until_fresh_control_compilation() {
    let roots = [TempRoot::new(), TempRoot::new()];
    let releases = Arc::new(
        DirectoryArtifactRepository::open(
            &roots[0].0,
            DirectoryArtifactRepositoryConfig::default(),
        )
        .unwrap(),
    );
    let mut value = artifact("host-lifecycle");
    value.manifest.runtime_requirements.runtime = Some(RuntimeRequirement {
        engine: "wasmtime".into(),
        minimum_version: "47.0.3".into(),
    });
    let digest = run(releases.publish(value)).unwrap().release_digest;
    let store = run(Store::open_with_catalog(
        &roots[1].0,
        releases.clone(),
        Limits::default(),
        releases.lifecycle_authority(),
        profile("47.0.3"),
    ))
    .unwrap();
    run(store.apply(deployment("blue", "alice", &digest))).unwrap();
    drop(store);
    let store = run(Store::open_with_catalog(
        &roots[1].0,
        releases.clone(),
        Limits::default(),
        releases.lifecycle_authority(),
        profile("47.0.2"),
    ))
    .unwrap();
    let inactive = store.pin().unwrap();
    assert_code(
        inactive.resolve(&target("alice", None), None),
        Code::IncompatibleContract,
    );
    assert_code(
        run(store.apply(deployment("blue", "alice", &digest))),
        Code::IncompatibleContract,
    );
    drop(store);
    let store = run(Store::open_with_catalog(
        &roots[1].0,
        releases.clone(),
        Limits::default(),
        releases.lifecycle_authority(),
        profile("47.0.3"),
    ))
    .unwrap();
    assert_eq!(
        store.resolve(&target("alice", None), None).unwrap().release,
        digest
    );
    assert_code(
        inactive.resolve(&target("alice", None), None),
        Code::IncompatibleContract,
    );
    run(store.delete(&DeploymentId("blue".into()))).unwrap();
}
