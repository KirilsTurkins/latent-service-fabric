#[path = "../../../tests/admission/support.rs"]
mod authority;

use std::sync::atomic::Ordering;
use std::sync::Arc;

use latent_artifacts::{
    AdmissionAuthority, AdmissionStorageLimits, ArtifactRepository, DirectoryArtifactRepository,
    DirectoryArtifactRepositoryConfig,
};
use latent_core::{PlatformErrorCode, RouteGeneration, TenantId};
use latent_routing::{RevisionPolicySource, RouteResolver};

use super::fixtures::*;
use crate::DeploymentStore;

struct Fixture {
    store: Store,
    releases: Arc<DirectoryArtifactRepository>,
    authority: Arc<authority::Authority>,
    first: latent_core::ReleaseDigest,
    second: latent_core::ReleaseDigest,
    _roots: [TempRoot; 2],
}
impl Fixture {
    fn new() -> Self {
        let mut artifacts = [artifact("admitted-one"), artifact("admitted-two")];
        for artifact in &mut artifacts {
            artifact.manifest.metadata.tenant = Some(TenantId("example".to_owned()));
        }
        let first = artifacts[0].descriptor.release_digest.clone();
        let second = artifacts[1].descriptor.release_digest.clone();
        let authority = authority::Authority::new_many(artifacts.to_vec());
        let trusted: Arc<dyn AdmissionAuthority> = authority.clone();
        let roots = [TempRoot::new(), TempRoot::new()];
        let releases = Arc::new(
            DirectoryArtifactRepository::open_enforced(
                &roots[0].0,
                DirectoryArtifactRepositoryConfig::default(),
                AdmissionStorageLimits::default(),
                trusted.clone(),
            )
            .unwrap(),
        );
        for artifact in artifacts {
            run(releases.admit_package(
                &TenantId("example".to_owned()),
                authority::upload(&artifact),
                &mut |_| Ok(()),
            ))
            .unwrap();
        }
        let store = run(Store::open_enforced(
            &roots[1].0,
            releases.clone(),
            Limits::default(),
            trusted,
        ))
        .unwrap();
        Self {
            store,
            releases,
            authority,
            first,
            second,
            _roots: roots,
        }
    }
}

#[test]
fn whole_generation_checks_distinct_grants_under_one_non_reentrant_authority() {
    let fixture = Fixture::new();
    run(fixture.store.apply_many(vec![
        deployment("blue", "example", &fixture.first),
        deployment("green", "example", &fixture.second),
    ]))
    .unwrap();
    assert_eq!(fixture.store.generation(), RouteGeneration(1));
    assert_eq!(fixture.store.read_catalog().eligibility.len(), 2);
    let pinned = fixture.store.pin().unwrap();
    let resolved = pinned
        .resolve(&target("example", Some("blue")), None)
        .unwrap();
    fixture
        .authority
        .state
        .active
        .store(false, Ordering::SeqCst);
    assert!(pinned
        .resolve(&target("example", Some("blue")), None)
        .is_err());
    assert!(pinned.admission_policy(&resolved).is_err());
    assert!(fixture
        .store
        .resolve(&target("example", Some("green")), None)
        .is_err());
}

#[test]
fn completed_compilation_cannot_commit_after_its_authority_changes() {
    let fixture = Fixture::new();
    run(fixture
        .store
        .apply(deployment("blue", "example", &fixture.first)))
    .unwrap();
    let previous = fixture.store.read_catalog();
    let mut work = super::super::observation::Work::default();
    let compiled = run(super::super::compiler::compile_versioned(
        previous.deployments.clone(),
        previous.versions.clone(),
        RouteGeneration(2),
        100,
        fixture.releases.as_ref(),
        Limits::default(),
        Some(&previous),
        &mut work,
    ))
    .unwrap();
    let stored = std::fs::read(fixture.store.root.join("catalog.json")).unwrap();
    fixture
        .authority
        .state
        .active
        .store(false, Ordering::SeqCst);
    assert!(fixture
        .store
        .commit(RouteGeneration(1), compiled, &mut work)
        .is_err());
    assert_eq!(fixture.store.generation(), RouteGeneration(1));
    assert_eq!(
        std::fs::read(fixture.store.root.join("catalog.json")).unwrap(),
        stored
    );
}

#[test]
fn expiry_during_sync_preserves_committed_generation_but_never_eligibility() {
    let fixture = Fixture::new();
    let state = Arc::clone(&fixture.authority.state);
    *fixture.store.after_parent_sync.lock().unwrap() = Some(Box::new(move || {
        state.now.store(200, Ordering::SeqCst);
    }));
    let result = run(fixture
        .store
        .apply(deployment("blue", "example", &fixture.first)));
    assert!(result.is_err());
    assert_eq!(
        fixture.store.generation(),
        RouteGeneration(1),
        "rename committed the complete generation"
    );
    assert!(fixture
        .store
        .resolve(&target("example", Some("blue")), None)
        .is_err());
    assert!(fixture
        .store
        .pin()
        .unwrap()
        .resolve(&target("example", Some("blue")), None)
        .is_err());
}

#[test]
fn enforced_route_store_rejects_local_entries_and_another_authority() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let digest = releases.add("local-only");
    let trusted = authority::Authority::new(artifact("unrelated"));
    let store = run(Store::open_enforced(
        &root.0,
        releases,
        Limits::default(),
        trusted,
    ))
    .unwrap();
    let failure = run(store.apply(deployment("local", "example", &digest))).unwrap_err();
    assert_eq!(failure.code, PlatformErrorCode::PermissionDenied);
    assert_eq!(store.generation(), RouteGeneration(0));

    let fixture = Fixture::new();
    let other_root = TempRoot::new();
    let foreign = authority::Authority::new(artifact("admitted-one"));
    let store = run(Store::open_enforced(
        &other_root.0,
        fixture.releases.clone(),
        Limits::default(),
        foreign,
    ))
    .unwrap();
    assert!(run(store.apply(deployment("foreign", "example", &fixture.first))).is_err());
    assert_eq!(store.generation(), RouteGeneration(0));
}

#[test]
fn revoked_unchanged_metadata_cannot_be_reapplied_or_reopened_as_current() {
    let fixture = Fixture::new();
    let deployment = deployment("blue", "example", &fixture.first);
    run(fixture.store.apply(deployment.clone())).unwrap();
    fixture
        .authority
        .state
        .active
        .store(false, Ordering::SeqCst);
    assert!(run(fixture.store.apply(deployment)).is_err());
    assert_eq!(fixture.store.generation(), RouteGeneration(1));
    let Fixture {
        store,
        releases,
        authority,
        _roots: roots,
        ..
    } = fixture;
    drop(store);
    assert!(run(Store::open_enforced(
        &roots[1].0,
        releases,
        Limits::default(),
        authority
    ))
    .is_err());
}

#[test]
fn catalog_bound_recovery_keeps_trust_denials_visible_until_fresh_control_refresh() {
    let Fixture {
        store,
        releases,
        authority,
        first,
        _roots: roots,
        ..
    } = Fixture::new();
    let desired = deployment("blue", "example", &first);
    run(store.apply(desired.clone())).unwrap();
    authority.state.active.store(false, Ordering::SeqCst);
    drop(store);
    let store = run(Store::open_with_catalog(
        &roots[1].0,
        releases.clone(),
        Limits::default(),
        releases.lifecycle_authority(),
        super::lifecycle::profile("47.0.3"),
    ))
    .unwrap();
    let denied = store.pin().unwrap();
    assert_code(
        denied.resolve(&target("example", None), None),
        Code::PermissionDenied,
    );
    assert_eq!(run(store.list()).unwrap(), vec![desired.clone()]);
    authority.state.active.store(true, Ordering::SeqCst);
    assert_code(
        denied.resolve(&target("example", None), None),
        Code::PermissionDenied,
    );
    // A new bounded control compilation may obtain fresh proof; an old pin cannot.
    run(store.apply(desired)).unwrap();
    assert_eq!(
        store
            .resolve(&target("example", None), None)
            .unwrap()
            .release,
        first
    );
    assert_code(
        denied.resolve(&target("example", None), None),
        Code::PermissionDenied,
    );
}
