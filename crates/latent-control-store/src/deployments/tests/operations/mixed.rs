use super::*;
use crate::rollouts::{
    DeploymentExpectation, RolloutCommand, RolloutContext, RolloutId, RolloutOperationPrecondition,
    RolloutRequest, StartRolloutSpec,
};
use latent_routing::{RouteCompiler, RouteSnapshotPublisher};

fn rollout_context(operation: &str, revision: u64) -> RolloutContext {
    RolloutContext {
        tenant: alice(),
        actor: context("unused", 0).actor,
        operation: RolloutOperationPrecondition {
            operation_id: operation.into(),
            expected_revision: revision,
        },
    }
}
fn change(store: &Store, operation: &str, revision: u64, command: RolloutCommand) {
    let prepared = run(store.prepare_rollout(RolloutRequest::Change {
        context: rollout_context(operation, revision),
        id: RolloutId("upgrade".into()),
        command,
    }))
    .unwrap();
    store.commit_rollout(prepared).unwrap().durability.unwrap();
}
fn start(store: &Store, release: &ReleaseDigest) {
    let mut candidate = deployment("candidate", "alice", release);
    candidate.route_weight = 2500;
    let prepared = run(store.prepare_rollout(RolloutRequest::Start {
        context: rollout_context("start", 0),
        spec: StartRolloutSpec {
            id: RolloutId("upgrade".into()),
            base: DeploymentExpectation {
                id: DeploymentId("base".into()),
                generation: 1,
            },
            candidate,
            candidate_weights: vec![2500, 10000],
            canary_policy: None,
        },
    }))
    .unwrap();
    store.commit_rollout(prepared).unwrap().durability.unwrap();
}

#[test]
fn v3_upgrade_and_every_legacy_writer_preserve_both_committed_histories() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let old = releases.add("mixed-base");
    let candidate = releases.add("mixed-candidate");
    let unrelated = releases.add("mixed-other-service");
    releases
        .values
        .write()
        .unwrap()
        .get_mut(&unrelated)
        .unwrap()
        .manifest
        .metadata
        .name = "other-service".into();
    let mut green = deployment("green", "alice", &unrelated);
    green.service.0 = "other-service".into();
    let managed_request =
        |operation, state, expected_generation| DeploymentOperationRequest::Apply {
            context: context(operation, state),
            manifest: green.clone(),
            expected_generation,
        };
    let store = open(&root, &releases);
    run(store.apply(deployment("base", "alice", &old))).unwrap();
    start(&store, &candidate);
    assert_eq!(stored(&root)["format_version"], 3);
    let rollout_before = stored(&root)["payload"]["control"]["rollouts"].clone();
    let managed = execute(&store, managed_request("managed", 2, 0));
    let receipt = managed.value().receipt.clone();
    drop(managed);
    assert_eq!(stored(&root)["format_version"], 4);
    assert_eq!(
        stored(&root)["payload"]["control"]["rollouts"],
        rollout_before
    );
    let operations_before = stored(&root)["payload"]["control"]["deployment_operations"].clone();
    change(&store, "pause", 1, RolloutCommand::Pause);
    let coherent =
        run(store.get_operation_snapshot(&alice(), &DeploymentId("green".into()))).unwrap();
    assert_eq!(coherent.value().state_version, 4);
    assert_eq!(coherent.value().route_generation, RouteGeneration(3));
    drop(coherent);
    assert_code(
        run(store.prepare_operation(managed_request("stale-after-pause", 3, 3))),
        Code::StateConflict,
    );
    run(store.apply(green.clone())).unwrap();
    change(&store, "resume", 2, RolloutCommand::Resume);
    change(&store, "abort", 3, RolloutCommand::Abort);
    let pinned = snapshot(&store);
    let next = run(RouteCompiler::compile(&store, Some(&pinned))).unwrap();
    run(RouteSnapshotPublisher::publish(&store, next)).unwrap();
    run(store.apply_many(vec![green])).unwrap();
    run(store.delete(&DeploymentId("green".into()))).unwrap();
    assert_eq!(stored(&root)["format_version"], 4);
    assert_eq!(
        stored(&root)["payload"]["control"]["deployment_operations"],
        operations_before
    );
    assert_eq!(
        lookup(&store, "managed").value(),
        &DeploymentOperationLookup::Found(receipt.clone())
    );
    let final_bytes = bytes(&root);
    drop(store);
    let reopened = open(&root, &releases);
    assert_eq!(bytes(&root), final_bytes);
    assert_eq!(
        lookup(&reopened, "managed").value(),
        &DeploymentOperationLookup::Found(receipt)
    );
    assert_eq!(
        reopened
            .get_rollout(&alice(), &RolloutId("upgrade".into()))
            .unwrap()
            .unwrap()
            .revision,
        4
    );
}

#[test]
fn intervening_legacy_publication_invalidates_sealed_managed_commit() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let one = releases.add("concurrent");
    let store = open(&root, &releases);
    let prepared = run(store.prepare_operation(apply("stale", 0, "blue", 0, &one))).unwrap();
    run(store.apply(deployment("green", "alice", &one))).unwrap();
    let before = bytes(&root);
    assert_code(store.commit_operation(prepared), Code::StateConflict);
    assert_eq!(bytes(&root), before);
    assert_eq!(stored(&root)["format_version"], 2);
    assert!(matches!(
        lookup(&store, "stale").value(),
        DeploymentOperationLookup::Unknown { .. }
    ));
    drop(execute(&store, apply("fresh", 1, "blue", 0, &one)));
}

#[test]
fn managed_commit_requires_live_release_but_historical_replay_never_reauthorizes_it() {
    use latent_artifacts::{
        ArtifactRepository, DirectoryArtifactRepository, DirectoryArtifactRepositoryConfig,
    };
    let roots = [TempRoot::new(), TempRoot::new()];
    let releases = Arc::new(
        DirectoryArtifactRepository::open(
            &roots[0].0,
            DirectoryArtifactRepositoryConfig::default(),
        )
        .unwrap(),
    );
    let first = run(releases.publish(artifact("managed-lifecycle-first")))
        .unwrap()
        .release_digest;
    let second = run(releases.publish(artifact("managed-lifecycle-second")))
        .unwrap()
        .release_digest;
    let store = run(Store::open_with_catalog(
        &roots[1].0,
        releases.clone(),
        Limits::default(),
        releases.lifecycle_authority(),
        super::super::lifecycle::profile("47.0.3"),
    ))
    .unwrap();
    let first_request = apply("first", 0, "blue", 0, &first);
    let committed = execute(&store, first_request.clone());
    let receipt = committed.value().receipt.clone();
    drop(committed);
    let prepared = run(store.prepare_operation(apply("second", 1, "green", 0, &second))).unwrap();
    super::super::lifecycle::revoke(&releases, &second);
    let before = bytes(&roots[1]);
    assert_code(store.commit_operation(prepared), Code::PermissionDenied);
    assert_eq!(bytes(&roots[1]), before);
    assert!(matches!(
        lookup(&store, "second").value(),
        DeploymentOperationLookup::Unknown { .. }
    ));
    run(releases.change_release_lifecycle(
        latent_artifacts::ReleaseMutationContext {
            scope: latent_artifacts::LifecycleScope::LocalUnscoped,
            actor: context("unused", 0).actor,
            operation: Some(latent_artifacts::ReleaseOperationPrecondition {
                operation_id: "revoke-original".into(),
                expected_generation: 1,
            }),
        },
        &first,
        latent_artifacts::ReleaseLifecycleAction::Revoke,
        latent_artifacts::ReleaseLifecycleReason::OperatorRevocation,
        &mut |_| Ok(()),
    ))
    .unwrap();
    let replay = execute(&store, first_request);
    assert_eq!(replay.value().receipt, receipt);
    assert!(replay.value().replayed);
    assert_code(
        store.resolve(&target("alice", Some("blue")), None),
        Code::PermissionDenied,
    );
    assert_eq!(bytes(&roots[1]), before);
}
