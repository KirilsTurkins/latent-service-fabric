use std::sync::atomic::Ordering;
use std::sync::Arc;

use latent_core::{FunctionId, RouteGeneration, TenantId};
use latent_routing::{RevisionPolicySource, RouteResolver};

use super::fixtures::*;
use crate::DeploymentStore;

#[test]
fn updating_one_release_still_rejects_corruption_in_an_unchanged_release() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let one = releases.add("unchanged-release");
    let two = releases.add("updated-release");
    let store = open(&root, &releases);
    let blue = deployment("blue", "alice", &one);
    let mut green = deployment("green", "alice", &two);
    run(store.apply_many(vec![blue, green.clone()])).unwrap();
    let pinned = store.pin().unwrap();
    let request = target("alice", Some("blue"));
    let original_route = pinned.resolve(&request, None).unwrap();
    let original = snapshot(&store);
    let durable = std::fs::read(root.0.join("catalog.json")).unwrap();

    releases
        .values
        .write()
        .unwrap()
        .get_mut(&one)
        .unwrap()
        .component_bytes[0] ^= 1;
    green.route_weight = 2;
    assert_code(
        run(store.apply_versioned(&TenantId("alice".into()), green, Some(1))),
        Code::CorruptArtifact,
    );
    assert_eq!(snapshot(&store), original);
    assert_eq!(std::fs::read(root.0.join("catalog.json")).unwrap(), durable);
    assert_eq!(pinned.resolve(&request, None).unwrap(), original_route);
    assert!(pinned.admission_policy(&original_route).is_ok());
}

#[test]
fn unchanged_component_bytes_do_not_cache_changed_execution_policy() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let digest = releases.add("policy-metadata");
    let store = open(&root, &releases);
    let manifest = deployment("blue", "alice", &digest);
    run(store.apply(manifest.clone())).unwrap();
    let pinned = store.pin().unwrap();
    let request = target("alice", Some("blue"));
    let old = pinned.resolve(&request, None).unwrap();
    let old_policy = pinned.admission_policy(&old).unwrap();
    assert_eq!(old_policy.execution.host_call_depth_maximum, 1);
    {
        let mut values = releases.values.write().unwrap();
        let execution = &mut values.get_mut(&digest).unwrap().manifest.execution;
        execution.host_call_depth_maximum = 2;
        execution.component_call_depth_maximum = 3;
    }
    let receipt = run(store.apply_versioned(&TenantId("alice".into()), manifest, Some(1))).unwrap();
    assert_eq!(receipt.catalog_generation, RouteGeneration(2));
    let current = store.pin().unwrap();
    let resolved = current.resolve(&request, None).unwrap();
    let policy = current.admission_policy(&resolved).unwrap();
    assert_eq!(policy.execution.host_call_depth_maximum, 2);
    assert_eq!(policy.execution.component_call_depth_maximum, 3);
    assert_eq!(pinned.admission_policy(&old).unwrap(), old_policy);
    assert_code(current.admission_policy(&old), Code::RouteUnavailable);
    drop(current);
    drop(store);
    let reopened = open(&root, &releases);
    let current = reopened.pin().unwrap();
    let resolved = current.resolve(&request, None).unwrap();
    assert_eq!(current.admission_policy(&resolved).unwrap(), policy);
    assert_eq!(releases.fetches.load(Ordering::Relaxed), 3);
}

#[test]
fn complete_contract_content_invalidates_reuse_even_with_unchanged_declared_digests() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let digest = releases.add("contract-metadata");
    let store = open(&root, &releases);
    let manifest = deployment("blue", "alice", &digest);
    run(store.apply(manifest.clone())).unwrap();
    let old = store.pin().unwrap();
    let mut added = target("alice", Some("blue"));
    added.function = FunctionId("second".into());
    assert_code(old.resolve(&added, None), Code::IncompatibleContract);
    {
        let mut values = releases.values.write().unwrap();
        let interface = &mut values.get_mut(&digest).unwrap().contracts[0].interfaces[0];
        let mut function = interface.functions[0].clone();
        function.id = FunctionId("second".into());
        function.name = "second".into();
        interface.functions.push(function);
    }
    run(store.apply_versioned(&TenantId("alice".into()), manifest, Some(1))).unwrap();
    let current = store.pin().unwrap();
    let resolved = current.resolve(&added, None).unwrap();
    assert_eq!(resolved.release, digest);
    assert!(current.admission_policy(&resolved).is_ok());
    assert_code(old.resolve(&added, None), Code::IncompatibleContract);
    drop(current);
    drop(store);
    let reopened = open(&root, &releases);
    assert_eq!(reopened.resolve(&added, None).unwrap().release, digest);
}

#[test]
fn metadata_above_the_optional_stamp_limit_remains_valid_through_update_and_reopen() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let digest = releases.add("large-metadata");
    releases
        .values
        .write()
        .unwrap()
        .get_mut(&digest)
        .unwrap()
        .contracts[0]
        .interfaces[0]
        .documentation = Some("d".repeat(600 * 1024));
    let limits = Limits {
        max_state_bytes: 512 * 1024,
        ..Limits::default()
    };
    let store = run(Store::open(root.0.clone(), releases.clone(), limits)).unwrap();
    let mut manifest = deployment("blue", "alice", &digest);
    run(store.apply(manifest.clone())).unwrap();
    manifest.route_weight = 2;
    let receipt = run(store.apply_versioned(&TenantId("alice".into()), manifest, Some(1))).unwrap();
    assert_eq!(receipt.catalog_generation, RouteGeneration(2));
    let expected = snapshot(&store);
    assert!(
        std::fs::metadata(root.0.join("catalog.json"))
            .unwrap()
            .len()
            < 512 * 1024
    );
    drop(store);
    let reopened = run(Store::open(root.0.clone(), releases.clone(), limits)).unwrap();
    assert_eq!(snapshot(&reopened), expected);
    assert_eq!(releases.fetches.load(Ordering::Relaxed), 3);
}
