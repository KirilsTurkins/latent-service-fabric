use std::sync::atomic::Ordering;
use std::sync::Arc;

use latent_core::{DeploymentId, PlatformErrorCode};

use super::super::DirectoryDeploymentRepositoryConfig;
use super::fixtures::*;

#[test]
fn canonical_records_share_routes_and_equal_reapply_without_sharing_object_versions() {
    let releases = Releases::default();
    let digest = releases.add("one");
    let mut desired = deployment("blue", "alice", &digest);
    desired
        .metadata
        .annotations
        .insert("large".to_owned(), "context".repeat(128));
    let old = compile(&releases, vec![desired.clone()], 9, None).unwrap();
    let new = compile(&releases, vec![desired], 10, Some(&old)).unwrap();
    assert_eq!(
        releases.fetches.load(Ordering::Relaxed),
        2,
        "reuse follows fresh verification"
    );
    assert!(Arc::ptr_eq(&old.records[0], &new.records[0]));
    let id = DeploymentId("blue".to_owned());
    assert!(Arc::ptr_eq(
        &new.deployments[&id],
        &new.records[0].deployment
    ));
    assert!(Arc::ptr_eq(&old.deployments[&id], &new.deployments[&id]));
    assert_eq!(old.versions[&id], 9);
    assert_eq!(new.versions[&id], 10);
    for route in new.route_views() {
        assert_eq!(route.revisions().len(), 1);
        assert!(std::ptr::eq(
            route.revisions().next().unwrap(),
            new.records[0].as_ref()
        ));
    }
}

#[test]
fn changed_weight_and_inserted_position_preserve_old_pin_and_retire_only_old_payload() {
    let releases = Releases::default();
    let digest = releases.add("one");
    let blue = deployment("blue", "alice", &digest);
    let green = deployment("green", "alice", &digest);
    let old = Arc::new(compile(&releases, vec![blue.clone(), green.clone()], 1, None).unwrap());
    let pin = Arc::clone(&old);
    let retired = Arc::downgrade(&old.records[0]);
    let pinned_result = pin
        .resolve(
            &target("alice", Some("blue")),
            Some("key"),
            DirectoryDeploymentRepositoryConfig::default(),
        )
        .unwrap();
    let mut changed = blue;
    changed.route_weight = 5;
    let new = compile(
        &releases,
        vec![deployment("alpha", "alice", &digest), changed, green],
        2,
        Some(&old),
    )
    .unwrap();
    assert_eq!(new.records[0].deployment.id.0, "alpha");
    assert_eq!(new.records[1].deployment.id.0, "blue");
    assert_eq!(old.records[0].revision, new.records[1].revision);
    assert_ne!(old.records[0].attributes, new.records[1].attributes);
    assert!(!Arc::ptr_eq(&old.records[0], &new.records[1]));
    assert!(Arc::ptr_eq(&old.records[1], &new.records[2]));
    drop(old);
    assert!(retired.upgrade().is_some());
    assert_eq!(
        pin.resolve(
            &target("alice", Some("blue")),
            Some("key"),
            DirectoryDeploymentRepositoryConfig::default()
        )
        .unwrap(),
        pinned_result
    );
    drop(pin);
    assert!(retired.upgrade().is_none());
    assert_eq!(
        new.resolve(
            &target("alice", Some("blue")),
            Some("key"),
            DirectoryDeploymentRepositoryConfig::default()
        )
        .unwrap()
        .release,
        digest
    );
}

#[test]
fn freshly_changed_execution_or_export_metadata_prevents_reuse() {
    let releases = Releases::default();
    let digest = releases.add("one");
    let desired = deployment("blue", "alice", &digest);
    let first = compile(&releases, vec![desired.clone()], 1, None).unwrap();
    releases
        .values
        .write()
        .unwrap()
        .get_mut(&digest)
        .unwrap()
        .manifest
        .execution
        .host_call_depth_maximum = 2;
    let second = compile(&releases, vec![desired.clone()], 2, Some(&first)).unwrap();
    assert!(!Arc::ptr_eq(&first.records[0], &second.records[0]));
    assert_eq!(first.records[0].attributes, second.records[0].attributes);
    assert_ne!(first.records[0].execution, second.records[0].execution);
    releases
        .values
        .write()
        .unwrap()
        .get_mut(&digest)
        .unwrap()
        .contracts[0]
        .interfaces[0]
        .functions[0]
        .documentation = Some("new documentation".to_owned());
    let third = compile(&releases, vec![desired], 3, Some(&second)).unwrap();
    assert!(!Arc::ptr_eq(&second.records[0], &third.records[0]));
    assert_ne!(
        second.records[0].attributes["lsf.exports"],
        third.records[0].attributes["lsf.exports"]
    );
    assert_eq!(releases.fetches.load(Ordering::Relaxed), 3);
}

#[test]
fn changed_corrupt_bytes_fail_before_any_prior_record_is_reused_or_mutated() {
    let releases = Releases::default();
    let digest = releases.add("one");
    let desired = deployment("blue", "alice", &digest);
    let prior = compile(&releases, vec![desired.clone()], 1, None).unwrap();
    let record = Arc::clone(&prior.records[0]);
    let expected = prior
        .resolve(
            &target("alice", None),
            None,
            DirectoryDeploymentRepositoryConfig::default(),
        )
        .unwrap();
    releases
        .values
        .write()
        .unwrap()
        .get_mut(&digest)
        .unwrap()
        .component_bytes[0] ^= 1;
    let error = compile(&releases, vec![desired], 2, Some(&prior))
        .err()
        .expect("fresh digest verification");
    assert_eq!(error.code, PlatformErrorCode::CorruptArtifact);
    assert!(Arc::ptr_eq(&prior.records[0], &record));
    assert_eq!(
        prior
            .resolve(
                &target("alice", None),
                None,
                DirectoryDeploymentRepositoryConfig::default()
            )
            .unwrap(),
        expected
    );
    assert_eq!(releases.fetches.load(Ordering::Relaxed), 2);
}
