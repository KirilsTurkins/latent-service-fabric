use std::sync::Arc;

use latent_core::TenantId;
use latent_manifest::{RuntimeCompatibilityProfile, RuntimeRequirement};
use latent_routing::RouteResolver;

use super::fixtures::*;
use crate::DeploymentStore;

fn profile(version: &str) -> Arc<RuntimeCompatibilityProfile> {
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

fn require(releases: &Releases, digest: &latent_core::ReleaseDigest, version: &str) {
    releases
        .values
        .write()
        .unwrap()
        .get_mut(digest)
        .unwrap()
        .manifest
        .runtime_requirements
        .runtime = Some(RuntimeRequirement {
        engine: "wasmtime".into(),
        minimum_version: version.into(),
    });
}

#[test]
fn default_constructor_cannot_stage_explicit_host_requirements() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let digest = releases.add("explicit-host");
    require(&releases, &digest, "47.0.3");
    let store = open(&root, &releases);
    let before = std::fs::read(root.0.join("catalog.json")).unwrap();
    assert_code(
        run(store.apply(deployment("blue", "alice", &digest))),
        Code::IncompatibleContract,
    );
    assert_eq!(store.generation().0, 0);
    assert_eq!(std::fs::read(root.0.join("catalog.json")).unwrap(), before);
    assert!(!root.0.join(".catalog.pending").exists());
}

#[test]
fn current_requirements_are_checked_before_reusing_unchanged_deployment_metadata() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let digest = releases.add("host-policy-change");
    require(&releases, &digest, "47.0.3");
    let store = run(Store::open_with_runtime(
        root.0.clone(),
        releases.clone(),
        Limits::default(),
        profile("47.0.3"),
    ))
    .unwrap();
    let desired = deployment("blue", "alice", &digest);
    run(store.apply(desired.clone())).unwrap();
    let before = std::fs::read(root.0.join("catalog.json")).unwrap();
    require(&releases, &digest, "47.0.4");
    assert_code(
        run(store.apply_versioned(&TenantId("alice".into()), desired, Some(1))),
        Code::IncompatibleContract,
    );
    assert_eq!(store.generation().0, 1);
    assert_eq!(std::fs::read(root.0.join("catalog.json")).unwrap(), before);
    assert!(!root.0.join(".catalog.pending").exists());
}

#[test]
fn reopen_requires_the_current_host_to_satisfy_retained_release_requirements() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let digest = releases.add("host-reopen");
    require(&releases, &digest, "47.0.3");
    let store = run(Store::open_with_runtime(
        root.0.clone(),
        releases.clone(),
        Limits::default(),
        profile("47.0.3"),
    ))
    .unwrap();
    run(store.apply(deployment("blue", "alice", &digest))).unwrap();
    drop(store);
    let before = std::fs::read(root.0.join("catalog.json")).unwrap();
    assert_code(
        run(Store::open(
            root.0.clone(),
            releases.clone(),
            Limits::default(),
        )),
        Code::IncompatibleContract,
    );
    assert_code(
        run(Store::open_with_runtime(
            root.0.clone(),
            releases.clone(),
            Limits::default(),
            profile("47.0.2"),
        )),
        Code::IncompatibleContract,
    );
    assert_eq!(std::fs::read(root.0.join("catalog.json")).unwrap(), before);
    let restored = run(Store::open_with_runtime(
        root.0.clone(),
        releases,
        Limits::default(),
        profile("47.0.4"),
    ))
    .unwrap();
    assert_eq!(restored.generation().0, 1);
}
