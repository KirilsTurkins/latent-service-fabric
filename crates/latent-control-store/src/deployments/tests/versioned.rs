use std::sync::atomic::Ordering;
use std::sync::Arc;

use latent_core::{DeploymentId, PlatformError, RouteGeneration, TenantId};
use latent_routing::{RouteCompiler, RouteResolver, RouteSnapshotPublisher};

use super::super::deployment_revision_id;
use super::fixtures::*;
use crate::{DeploymentStore, VersionedDeployment};

mod persistence;
mod races;

fn alice() -> TenantId {
    TenantId("alice".to_owned())
}

fn record(store: &Store, id: &str) -> VersionedDeployment {
    run(store.get_versioned(&alice(), &DeploymentId(id.to_owned())))
        .unwrap()
        .expect("versioned deployment exists")
}

fn assert_conflict<T>(result: Result<T, PlatformError>, reason: &str) {
    let failure = result.err().expect("concurrent/stale mutation must fail");
    assert_eq!(failure.code, Code::StateConflict);
    assert_eq!(failure.message, reason);
}

#[test]
fn versioned_apply_compares_caller_preconditions_and_returns_normalized_committed_state() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let one = releases.add("first");
    let two = releases.add("second");
    let store = open(&root, &releases);
    let expected = deployment("blue", "alice", &one);
    let mut supplied = expected.clone();
    supplied.release.0 = format!("sha256:{}", supplied.release.0[7..].to_ascii_uppercase());
    let created = run(store.apply_versioned(&alice(), supplied, Some(0))).unwrap();
    assert_eq!(created.deployment.manifest, expected);
    assert_eq!(created.deployment.generation, 1);
    assert_eq!(created.catalog_generation, RouteGeneration(1));
    assert_eq!(record(&store, "blue"), created.deployment);
    let content_revision = deployment_revision_id(&expected).unwrap();

    let unchanged = run(store.apply_versioned(&alice(), expected.clone(), Some(1))).unwrap();
    assert_eq!(unchanged.deployment.generation, 2);
    assert_eq!(unchanged.catalog_generation, RouteGeneration(2));
    assert_eq!(
        deployment_revision_id(&unchanged.deployment.manifest).unwrap(),
        content_revision
    );
    for expected_generation in [Some(0), Some(1), Some(3)] {
        assert_conflict(
            run(store.apply_versioned(&alice(), expected.clone(), expected_generation)),
            "deployment-generation-conflict",
        );
        assert_eq!(record(&store, "blue"), unchanged.deployment);
        assert_eq!(store.generation(), RouteGeneration(2));
    }
    let unrelated =
        run(store.apply_versioned(&alice(), deployment("green", "alice", &one), Some(0))).unwrap();
    assert_eq!(unrelated.deployment.generation, 3);
    assert_eq!(record(&store, "blue").generation, 2);
    let changed = deployment("blue", "alice", &two);
    let committed = run(store.apply_versioned(&alice(), changed.clone(), Some(2))).unwrap();
    assert_eq!(committed.deployment.manifest, changed);
    assert_eq!(committed.deployment.generation, 4);
    assert_eq!(committed.catalog_generation, RouteGeneration(4));
    let unconditional = run(store.apply_versioned(&alice(), expected, None)).unwrap();
    assert_eq!(unconditional.deployment.generation, 5);
    assert_eq!(unconditional.catalog_generation, RouteGeneration(5));
    assert_eq!(record(&store, "green"), unrelated.deployment);
    drop(store);
    let restarted = open(&root, &releases);
    assert_eq!(record(&restarted, "blue"), unconditional.deployment);
    assert_eq!(record(&restarted, "green"), unrelated.deployment);
    assert_eq!(restarted.generation(), RouteGeneration(5));
}

#[test]
fn delete_receipts_preserve_removed_versions_and_recreation_never_reuses_a_stamp() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let one = releases.add("one");
    let store = open(&root, &releases);
    let manifest = deployment("blue", "alice", &one);
    let id = manifest.id.clone();
    for expected in [None, Some(0)] {
        assert_code(
            run(store.delete_versioned(&alice(), &id, expected)),
            Code::NotFound,
        );
    }
    assert_conflict(
        run(store.apply_versioned(&alice(), manifest.clone(), Some(1))),
        "deployment-generation-conflict",
    );
    let created = run(store.apply_versioned(&alice(), manifest.clone(), None)).unwrap();
    for expected in [Some(0), Some(2)] {
        assert_conflict(
            run(store.delete_versioned(&alice(), &id, expected)),
            "deployment-generation-conflict",
        );
    }
    let deleted = run(store.delete_versioned(&alice(), &id, Some(1))).unwrap();
    assert_eq!(deleted.deleted, created.deployment);
    assert_eq!(deleted.catalog_generation, RouteGeneration(2));
    assert!(run(store.get_versioned(&alice(), &id)).unwrap().is_none());
    assert_conflict(
        run(store.apply_versioned(&alice(), manifest.clone(), Some(1))),
        "deployment-generation-conflict",
    );
    drop(store);
    let restarted = open(&root, &releases);
    let recreated = run(restarted.apply_versioned(&alice(), manifest, Some(0))).unwrap();
    assert_eq!(recreated.deployment.generation, 3);
    assert_eq!(recreated.catalog_generation, RouteGeneration(3));
    assert_conflict(
        run(restarted.delete_versioned(&alice(), &id, Some(created.deployment.generation))),
        "deployment-generation-conflict",
    );
    let deleted_again = run(restarted.delete_versioned(&alice(), &id, None)).unwrap();
    assert_eq!(deleted_again.deleted, recreated.deployment);
    assert_eq!(deleted_again.catalog_generation, RouteGeneration(4));
}

#[test]
fn legacy_batch_and_snapshot_writers_preserve_consistent_object_stamps() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let one = releases.add("one");
    let store = open(&root, &releases);
    let blue = deployment("blue", "alice", &one);
    let green = deployment("green", "alice", &one);
    run(store.apply(blue.clone())).unwrap();
    assert_eq!(record(&store, "blue").generation, 1);
    assert_eq!(
        run(store.apply_many(vec![blue.clone(), green.clone()])).unwrap(),
        RouteGeneration(2)
    );
    assert_eq!(record(&store, "blue").generation, 2);
    assert_eq!(record(&store, "green").generation, 2);
    run(store.apply(blue.clone())).unwrap();
    assert_eq!(record(&store, "blue").generation, 3);
    assert_eq!(record(&store, "green").generation, 2);
    let current = snapshot(&store);
    let next = run(RouteCompiler::compile(&store, Some(&current))).unwrap();
    run(RouteSnapshotPublisher::publish(&store, next)).unwrap();
    assert_eq!(store.generation(), RouteGeneration(4));
    assert_eq!(record(&store, "blue").generation, 3);
    assert_eq!(record(&store, "green").generation, 2);
    assert_eq!(
        run(DeploymentStore::get(&store, &blue.id)).unwrap(),
        Some(blue)
    );
    run(store.delete(&green.id)).unwrap();
    assert!(run(store.get_versioned(&alice(), &green.id))
        .unwrap()
        .is_none());
    assert_eq!(record(&store, "blue").generation, 3);
    assert_eq!(store.generation(), RouteGeneration(5));
    drop(store);
    let restarted = open(&root, &releases);
    assert_eq!(record(&restarted, "blue").generation, 3);
    assert_eq!(restarted.generation(), RouteGeneration(5));
}

#[test]
fn tenant_scope_is_checked_independently_of_object_identity_and_generation() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let one = releases.add("one");
    let store = open(&root, &releases);
    let owned = deployment("blue", "alice", &one);
    let committed = run(store.apply_versioned(&alice(), owned.clone(), None)).unwrap();
    let bob = TenantId("bob".to_owned());
    let fetches = releases.fetches.load(Ordering::Relaxed);
    assert!(run(store.get_versioned(&bob, &owned.id)).unwrap().is_none());
    for expected in [None, Some(0), Some(1)] {
        assert_code(
            run(store.delete_versioned(&bob, &owned.id, expected)),
            Code::NotFound,
        );
        assert_code(
            run(store.apply_versioned(&bob, owned.clone(), expected)),
            Code::PermissionDenied,
        );
        assert_code(
            run(store.apply_versioned(&bob, deployment("blue", "bob", &one), expected)),
            Code::PermissionDenied,
        );
    }
    assert_eq!(releases.fetches.load(Ordering::Relaxed), fetches);
    assert_eq!(record(&store, "blue"), committed.deployment);
    assert_eq!(store.generation(), RouteGeneration(1));
}
