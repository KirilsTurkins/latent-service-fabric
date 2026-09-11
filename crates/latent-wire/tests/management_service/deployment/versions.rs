use std::sync::atomic::Ordering;

use latent_artifacts::ArtifactRepository;
use latent_control_store::CompiledRouteStore;
use latent_wire::management::{proto, ManagementLimits};
use tonic::Code;

use super::super::support::{artifact, deployment, request, Harness};
use super::{apply, delete, get};

#[tokio::test]
async fn versioned_rpc_round_trip_preserves_fields_and_delete_recreate_stamps() {
    let harness = Harness::new(ManagementLimits::default()).await;
    let release = harness
        .artifacts
        .publish(artifact("acme", "echo", "round-trip"))
        .await
        .unwrap();
    let mut desired = deployment("ship", "acme", "echo", &release.release_digest);
    desired.generation = u64::MAX;
    let created = apply(&harness, "alice", desired.clone(), Some(0))
        .await
        .unwrap();
    assert!(created.generation > 0 && created.generation < u64::MAX);
    desired.generation = created.generation;
    assert_eq!(created, desired);
    assert_eq!(get(&harness, "alice", "ship").await.unwrap(), created);
    apply(
        &harness,
        "alice",
        deployment("other", "acme", "echo", &release.release_digest),
        None,
    )
    .await
    .unwrap();
    let mut update = created.clone();
    update.route_weight = 2;
    let updated = apply(&harness, "alice", update, Some(created.generation))
        .await
        .unwrap();
    assert!(updated.generation > created.generation);
    for expected in [created.generation, 0] {
        assert_eq!(
            delete(&harness, "alice", "ship", Some(expected))
                .await
                .unwrap_err()
                .code(),
            Code::Aborted
        );
    }
    delete(&harness, "alice", "ship", Some(updated.generation))
        .await
        .unwrap();
    assert!(get(&harness, "alice", "ship").await.is_none());
    assert_eq!(
        delete(&harness, "alice", "ship", Some(0))
            .await
            .unwrap_err()
            .code(),
        Code::NotFound
    );
    let recreated = apply(&harness, "alice", created.clone(), Some(0))
        .await
        .unwrap();
    assert!(recreated.generation > updated.generation);
    assert_eq!(
        apply(&harness, "alice", created.clone(), Some(created.generation))
            .await
            .unwrap_err()
            .code(),
        Code::Aborted
    );
    assert_eq!(harness.inventory.snapshots.load(Ordering::Relaxed), 0);
    harness.shutdown().await;
}

#[tokio::test]
async fn competing_rpc_versions_have_one_winner_and_return_its_exact_record() {
    let harness = Harness::new(ManagementLimits::default()).await;
    let release = harness
        .artifacts
        .publish(artifact("acme", "echo", "race"))
        .await
        .unwrap();
    let created = apply(
        &harness,
        "alice",
        deployment("ship", "acme", "echo", &release.release_digest),
        Some(0),
    )
    .await
    .unwrap();
    let mut left = created.clone();
    left.route_weight = 2;
    let mut right = created.clone();
    right.route_weight = 3;
    let (left, right) = tokio::join!(
        apply(&harness, "alice", left, Some(created.generation)),
        apply(&harness, "alice", right, Some(created.generation)),
    );
    let mut successes = Vec::new();
    let mut conflicts = 0;
    for result in [left, right] {
        match result {
            Ok(response) => successes.push(response),
            Err(error) => {
                assert_eq!(error.code(), Code::Aborted);
                conflicts += 1;
            }
        }
    }
    assert_eq!(successes.len(), 1);
    assert_eq!(conflicts, 1);
    assert_eq!(get(&harness, "alice", "ship").await.unwrap(), successes[0]);
    harness.shutdown().await;
}

#[tokio::test]
async fn deployment_watch_is_explicitly_unimplemented() {
    let harness = Harness::new(ManagementLimits::default()).await;
    assert_eq!(
        harness
            .deployments_client()
            .watch_deployment(request(
                "alice",
                proto::WatchDeploymentRequest {
                    id: "ship".to_owned(),
                    after_generation: 0,
                }
            ))
            .await
            .unwrap_err()
            .code(),
        Code::Unimplemented
    );
    assert_eq!(harness.deployments.current().await.unwrap().generation.0, 0);
    harness.shutdown().await;
}
