use std::collections::BTreeMap;
use std::fs;
use std::sync::atomic::Ordering;
use std::sync::Arc;

use latent_artifacts::{
    content_digest, ArtifactRepository, DirectoryArtifactRepository,
    DirectoryArtifactRepositoryConfig,
};
use latent_core::{DeploymentId, RouteGeneration};
use latent_manifest::__serde_json as json;
use latent_routing::{RouteCompiler, RouteResolver};

use super::super::{compiler, persistence};
use super::fixtures::*;
use crate::DeploymentStore;

#[test]
fn real_release_and_deployment_catalogs_restore_exact_routes_and_deletions() {
    let artifacts_root = TempRoot::new();
    let deployments_root = TempRoot::new();
    let open_artifacts = || {
        Arc::new(
            DirectoryArtifactRepository::open(
                artifacts_root.0.clone(),
                DirectoryArtifactRepositoryConfig::default(),
            )
            .unwrap(),
        )
    };
    let releases = open_artifacts();
    let descriptor = run(releases.publish(artifact("persistent"))).unwrap();
    let store = run(Store::open(
        deployments_root.0.clone(),
        releases.clone(),
        Limits::default(),
    ))
    .unwrap();
    let deployment = deployment("blue", "alice", &descriptor.release_digest);
    run(store.apply(deployment.clone())).unwrap();
    let expected_snapshot = snapshot(&store);
    let expected_route = store
        .resolve(&target("alice", None), Some("stable"))
        .unwrap();
    drop(store);
    drop(releases);

    let releases = open_artifacts();
    let store = run(Store::open(
        deployments_root.0.clone(),
        releases.clone(),
        Limits::default(),
    ))
    .unwrap();
    assert_eq!(snapshot(&store), expected_snapshot);
    let restored = store
        .resolve(&target("alice", None), Some("stable"))
        .unwrap();
    assert_eq!(restored, expected_route);
    assert_eq!(run(store.list()).unwrap(), vec![deployment.clone()]);
    run(store.delete(&deployment.id)).unwrap();
    drop(store);
    drop(releases);

    let store = run(Store::open(
        deployments_root.0.clone(),
        open_artifacts(),
        Limits::default(),
    ))
    .unwrap();
    assert_eq!(store.generation(), RouteGeneration(2));
    assert!(run(store.list()).unwrap().is_empty());
    assert_code(
        store.resolve(&target("alice", None), None),
        Code::RouteUnavailable,
    );
}

#[test]
fn restart_ignores_pending_but_rejects_corrupt_or_missing_complete_state() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let one = releases.add("one");
    let store = open(&root, &releases);
    run(store.apply(deployment("blue", "alice", &one))).unwrap();
    let expected = snapshot(&store);
    drop(store);
    fs::write(root.0.join(".catalog.pending"), b"incomplete").unwrap();
    let store = open(&root, &releases);
    assert_eq!(snapshot(&store), expected);
    assert!(!root.0.join(".catalog.pending").exists());
    drop(store);
    let state = root.0.join(persistence::STATE_FILE);
    fs::write(&state, b"broken").unwrap();
    assert_code(
        run(Store::open(
            root.0.clone(),
            releases.clone(),
            Limits::default(),
        )),
        Code::CorruptArtifact,
    );
    fs::remove_file(&state).unwrap();
    assert_code(
        run(Store::open(root.0.clone(), releases, Limits::default())),
        Code::CorruptArtifact,
    );
}

#[test]
fn crash_boundaries_keep_disk_and_memory_on_complete_snapshots() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let one = releases.add("one");
    let two = releases.add("two");
    let store = open(&root, &releases);
    run(store.apply(deployment("blue", "alice", &one))).unwrap();
    store.fail_before_rename.store(true, Ordering::SeqCst);
    assert_code(
        run(store.apply(deployment("blue", "alice", &two))),
        Code::Unavailable,
    );
    assert_eq!(
        store.resolve(&target("alice", None), None).unwrap().release,
        one
    );
    drop(store);
    let store = open(&root, &releases);
    assert_eq!(
        store.resolve(&target("alice", None), None).unwrap().release,
        one
    );
    store.fail_parent_sync.store(true, Ordering::SeqCst);
    let failure = run(store.apply(deployment("blue", "alice", &two))).unwrap_err();
    assert_eq!(failure.message, "commit-durability-uncertain");
    assert_eq!(
        store.resolve(&target("alice", None), None).unwrap().release,
        two
    );
    drop(store);
    let store = open(&root, &releases);
    assert_eq!(
        store.resolve(&target("alice", None), None).unwrap().release,
        two
    );
    assert_eq!(store.generation(), RouteGeneration(2));
}

#[test]
fn interrupted_initialization_restores_the_missing_marker() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    drop(open(&root, &releases));
    fs::remove_file(root.0.join("INITIALIZED")).unwrap();
    drop(open(&root, &releases));
    assert!(root.0.join("INITIALIZED").is_file());
    fs::remove_file(root.0.join(persistence::STATE_FILE)).unwrap();
    assert_code(
        run(Store::open(root.0.clone(), releases, Limits::default())),
        Code::CorruptArtifact,
    );
}

#[test]
fn valid_checksum_does_not_hide_a_mismatched_compiled_snapshot() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let one = releases.add("one");
    let store = open(&root, &releases);
    run(store.apply(deployment("blue", "alice", &one))).unwrap();
    drop(store);
    let path = root.0.join(persistence::STATE_FILE);
    let mut record: persistence::Record = json::from_slice(&fs::read(&path).unwrap()).unwrap();
    record.payload.snapshot["services"] = json::json!([]);
    record.checksum = content_digest(&json::to_vec(&record.payload).unwrap()).0;
    fs::write(path, json::to_vec(&record).unwrap()).unwrap();
    let failure = run(Store::open(root.0.clone(), releases, Limits::default()))
        .err()
        .unwrap();
    assert_eq!(failure.code, Code::CorruptArtifact);
    assert_eq!(failure.message, "persisted-route-mismatch");
}

#[test]
fn recovery_never_silently_drops_a_missing_release_or_changed_contract() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let one = releases.add("one");
    let store = open(&root, &releases);
    run(store.apply(deployment("blue", "alice", &one))).unwrap();
    drop(store);
    let original = fs::read(root.0.join(persistence::STATE_FILE)).unwrap();
    releases.values.write().unwrap().remove(&one);
    assert_code(
        run(Store::open(
            root.0.clone(),
            releases.clone(),
            Limits::default(),
        )),
        Code::NotFound,
    );
    assert_eq!(
        fs::read(root.0.join(persistence::STATE_FILE)).unwrap(),
        original
    );
    releases.add("one");
    {
        let mut values = releases.values.write().unwrap();
        let function = &mut values.get_mut(&one).unwrap().contracts[0].interfaces[0].functions[0];
        function.name = "changed-metadata".to_owned();
    }
    let failure = run(Store::open(root.0.clone(), releases, Limits::default()))
        .err()
        .unwrap();
    assert_eq!(failure.code, Code::CorruptArtifact);
    assert_eq!(failure.message, "persisted-route-mismatch");
}

#[test]
fn staging_io_failure_does_not_publish_any_desired_state() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let one = releases.add("one");
    let store = open(&root, &releases);
    let before = fs::read(root.0.join(persistence::STATE_FILE)).unwrap();
    fs::create_dir(root.0.join(".catalog.pending")).unwrap();
    assert_code(
        run(store.apply(deployment("blue", "alice", &one))),
        Code::Unavailable,
    );
    assert_eq!(store.generation(), RouteGeneration(0));
    assert_eq!(
        fs::read(root.0.join(persistence::STATE_FILE)).unwrap(),
        before
    );
    fs::remove_dir(root.0.join(".catalog.pending")).unwrap();
    drop(store);
    assert!(run(open(&root, &releases).list()).unwrap().is_empty());
}

#[test]
fn generation_exhaustion_never_wraps_to_zero() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let store = open(&root, &releases);
    let exhausted = run(compiler::compile(
        BTreeMap::new(),
        RouteGeneration(u64::MAX),
        0,
        releases.as_ref(),
        Limits::default(),
    ))
    .unwrap();
    store
        .commit(
            RouteGeneration(0),
            exhausted,
            &mut super::super::observation::Work::default(),
        )
        .unwrap();
    let current = snapshot(&store);
    assert_code(
        run(RouteCompiler::compile(&store, None)),
        Code::StateConflict,
    );
    assert_code(
        run(RouteCompiler::compile(&store, Some(&current))),
        Code::ResourceExhausted,
    );
    assert_code(
        run(store.delete(&DeploymentId("missing".to_owned()))),
        Code::NotFound,
    );
    assert_eq!(store.generation(), RouteGeneration(u64::MAX));
}
