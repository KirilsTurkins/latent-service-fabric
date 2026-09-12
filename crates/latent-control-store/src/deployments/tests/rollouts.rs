use std::sync::{atomic::Ordering, Arc};

use latent_artifacts::{ReleaseActor, ReleaseActorKind};
use latent_core::{DeploymentId, RouteGeneration, TenantId};
use latent_manifest::__serde_json as json;
use latent_routing::{RevisionPolicySource, RouteResolver};

use super::fixtures::*;
use crate::{rollouts::*, DeploymentStore};

mod canary;
mod compatibility;
mod recovery;

fn alice() -> TenantId {
    TenantId("alice".into())
}
fn id() -> RolloutId {
    RolloutId("echo-upgrade".into())
}
fn context(operation: &str, revision: u64) -> RolloutContext {
    RolloutContext {
        tenant: alice(),
        actor: ReleaseActor {
            kind: ReleaseActorKind::Host,
            subject: "rollout-test".into(),
        },
        operation: RolloutOperationPrecondition {
            operation_id: operation.into(),
            expected_revision: revision,
        },
    }
}
fn change(operation: &str, revision: u64, command: RolloutCommand) -> RolloutRequest {
    RolloutRequest::Change {
        context: context(operation, revision),
        id: id(),
        command,
    }
}
fn setup(store: &Store, releases: &Releases) -> RolloutRequest {
    let old = releases.add("rollout-old");
    let new = releases.add("rollout-new");
    run(store.apply(deployment("base", "alice", &old))).unwrap();
    let mut candidate = deployment("candidate", "alice", &new);
    candidate.route_weight = 2500;
    RolloutRequest::Start {
        context: context("start", 0),
        spec: StartRolloutSpec {
            id: id(),
            base: DeploymentExpectation {
                id: DeploymentId("base".into()),
                generation: 1,
            },
            candidate,
            candidate_weights: vec![2500, 5000, 10000],
            canary_policy: None,
        },
    }
}
fn execute(store: &Store, request: RolloutRequest) -> RolloutCommitResult {
    let prepared = run(store.prepare_rollout(request)).unwrap();
    let preview = prepared.preview().clone();
    let result = store.commit_rollout(prepared).unwrap();
    assert_eq!(result.receipt, preview);
    result.durability.as_ref().unwrap();
    result
}
fn persisted(root: &TempRoot) -> json::Value {
    json::from_slice(&std::fs::read(root.0.join("catalog.json")).unwrap()).unwrap()
}

#[test]
fn stages_commit_one_combined_catalog_and_replay_exact_history_after_restart() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let store = open(&root, &releases);
    let request = setup(&store, &releases);
    assert_eq!(persisted(&root)["format_version"], 2);
    let original_pin = store.pin().unwrap();
    let original = original_pin
        .resolve(&target("alice", None), Some("pinned-activation"))
        .unwrap();
    let original_policy = original_pin.admission_policy(&original).unwrap();
    let first = execute(&store, request.clone());
    assert_eq!(first.receipt.revision, 1);
    assert_eq!(first.receipt.route_generation, RouteGeneration(2));
    let values = run(store.list()).unwrap();
    assert_eq!(
        values
            .iter()
            .find(|v| v.id.0 == "base")
            .unwrap()
            .route_weight,
        7500
    );
    assert_eq!(
        values
            .iter()
            .find(|v| v.id.0 == "candidate")
            .unwrap()
            .route_weight,
        2500
    );
    let encoded = persisted(&root);
    assert_eq!(encoded["format_version"], 3);
    assert_eq!(
        encoded["payload"]["control"]["transaction_version"],
        first.receipt.state_version
    );
    let advance = execute(
        &store,
        change("advance", 1, RolloutCommand::Advance { next_step: 1 }),
    );
    assert_eq!(advance.receipt.step, 1);
    let replay = execute(&store, request.clone());
    assert!(replay.replayed);
    assert_eq!(replay.receipt, first.receipt);
    assert_eq!(
        store
            .get_rollout(&alice(), &id())
            .unwrap()
            .unwrap()
            .revision,
        2
    );
    let complete = execute(
        &store,
        change("complete", 2, RolloutCommand::Advance { next_step: 2 }),
    );
    assert_eq!(complete.receipt.state, RolloutState::Completed);
    let values = run(store.list()).unwrap();
    assert_eq!(values.len(), 1);
    assert_eq!(values[0].id.0, "candidate");
    assert_eq!(values[0].route_weight, 10000);
    assert_eq!(
        original_pin
            .resolve(&target("alice", None), Some("pinned-activation"))
            .unwrap(),
        original
    );
    assert_eq!(
        original_pin.admission_policy(&original).unwrap(),
        original_policy
    );
    let fresh_pin = store.pin().unwrap();
    let fresh = fresh_pin
        .resolve(&target("alice", None), Some("pinned-activation"))
        .unwrap();
    assert_eq!(fresh.release, values[0].release);
    assert_ne!(fresh.release, original.release);
    assert!(fresh.route_generation > original.route_generation);
    drop(store);
    let store = open(&root, &releases);
    assert_eq!(
        store.get_rollout(&alice(), &id()).unwrap().unwrap().state,
        RolloutState::Completed
    );
    assert_eq!(execute(&store, request).receipt, first.receipt);
    assert_code(
        run(store.prepare_rollout(change("too-late", 3, RolloutCommand::Resume))),
        Code::StateConflict,
    );
    assert_eq!(persisted(&root)["format_version"], 3);
}

#[test]
fn pause_and_abort_keep_route_arc_and_never_fetch_or_refresh_grants() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let store = open(&root, &releases);
    let request = setup(&store, &releases);
    execute(&store, request);
    let before = store.read_publication();
    let fetches = releases.fetches.load(Ordering::Relaxed);
    releases.values.write().unwrap().clear();
    let pause = execute(&store, change("pause", 1, RolloutCommand::Pause));
    let paused = store.read_publication();
    assert!(Arc::ptr_eq(&before.routes, &paused.routes));
    assert_eq!(before.transaction + 1, paused.transaction);
    assert_eq!(pause.receipt.route_generation, before.routes.generation);
    assert_code(
        run(store.prepare_rollout(change("resume-denied", 2, RolloutCommand::Resume))),
        Code::NotFound,
    );
    let after_failed_resume = releases.fetches.load(Ordering::Relaxed);
    assert!(after_failed_resume > fetches);
    execute(&store, change("abort", 2, RolloutCommand::Abort));
    assert!(Arc::ptr_eq(
        &before.routes,
        &store.read_publication().routes
    ));
    assert_eq!(
        releases.fetches.load(Ordering::Relaxed),
        after_failed_resume
    );
    assert_eq!(
        store
            .get_rollout_operation(&alice(), &id(), "resume-denied")
            .unwrap(),
        RolloutOperationLookup::Unknown
    );
}

#[test]
fn prepared_drop_has_no_content_side_effect_and_releases_the_one_work_slot() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let store = open(&root, &releases);
    let request = setup(&store, &releases);
    let before = std::fs::read(root.0.join("catalog.json")).unwrap();
    let prepared = run(store.prepare_rollout(request.clone())).unwrap();
    assert_code(
        run(store.prepare_rollout(request.clone())),
        Code::ResourceExhausted,
    );
    assert_eq!(std::fs::read(root.0.join("catalog.json")).unwrap(), before);
    assert!(!root.0.join(".catalog.pending").exists());
    assert!(store.get_rollout(&alice(), &id()).unwrap().is_none());
    drop(prepared);
    execute(&store, request);
}

#[test]
fn stale_ordinary_writer_cannot_erase_state_only_commit_and_manual_drift_conflicts() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let store = open(&root, &releases);
    let request = setup(&store, &releases);
    execute(&store, request);
    let previous = store.read_publication();
    let generation = RouteGeneration(previous.routes.generation.0 + 1);
    let encoded = run(super::super::compiler::compile_versioned_with_runtime(
        previous.routes.deployments.clone(),
        previous.routes.versions.clone(),
        generation,
        10,
        releases.as_ref(),
        Limits::default(),
        Some(&previous.routes),
        &mut super::super::observation::Work::default(),
        None,
        None,
    ))
    .unwrap();
    execute(&store, change("pause", 1, RolloutCommand::Pause));
    assert_code(
        store.commit_versioned(
            previous.routes.generation,
            previous.transaction,
            encoded,
            &mut super::super::observation::Work::default(),
        ),
        Code::StateConflict,
    );
    execute(&store, change("resume", 2, RolloutCommand::Resume));
    let mut candidate = run(DeploymentStore::get(
        &store,
        &DeploymentId("candidate".into()),
    ))
    .unwrap()
    .unwrap();
    candidate.route_weight = 1234;
    run(store.apply(candidate)).unwrap();
    assert_eq!(
        store.get_rollout(&alice(), &id()).unwrap().unwrap().state,
        RolloutState::Conflicted
    );
    assert_code(
        run(store.prepare_rollout(change(
            "drift-advance",
            3,
            RolloutCommand::Advance { next_step: 1 },
        ))),
        Code::StateConflict,
    );
    execute(&store, change("stop-drift", 3, RolloutCommand::Abort));
    assert_eq!(
        store.get_rollout(&alice(), &id()).unwrap().unwrap().state,
        RolloutState::Aborted
    );
}

#[test]
fn staged_cutpoint_recovers_old_whole_state_and_rename_uncertainty_is_explicit() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let store = open(&root, &releases);
    let request = setup(&store, &releases);
    let prepared = run(store.prepare_rollout(request.clone())).unwrap();
    store.fail_before_rename.store(true, Ordering::SeqCst);
    assert_code(store.commit_rollout(prepared), Code::Unavailable);
    assert!(store.get_rollout(&alice(), &id()).unwrap().is_none());
    drop(store);
    let store = open(&root, &releases);
    assert!(store.get_rollout(&alice(), &id()).unwrap().is_none());
    let prepared = run(store.prepare_rollout(request.clone())).unwrap();
    store.fail_parent_sync.store(true, Ordering::SeqCst);
    let uncertain = store.commit_rollout(prepared).unwrap();
    assert!(uncertain.durability.is_err());
    assert_eq!(
        store
            .get_rollout_operation(&alice(), &id(), "start")
            .unwrap(),
        RolloutOperationLookup::Uncertain
    );
    assert_code(
        run(store.prepare_rollout(request.clone())),
        Code::Unavailable,
    );
    store.confirm_rollout_durability().unwrap();
    assert_eq!(execute(&store, request).receipt, uncertain.receipt);
    drop(store);
    let store = open(&root, &releases);
    assert_eq!(
        store
            .get_rollout(&alice(), &id())
            .unwrap()
            .unwrap()
            .revision,
        1
    );
}

#[test]
fn scopes_and_exact_operation_payload_are_checked_before_replay_or_new_reads() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let store = open(&root, &releases);
    let request = setup(&store, &releases);
    execute(&store, request.clone());
    let mut conflicting = request;
    let RolloutRequest::Start { spec, .. } = &mut conflicting else {
        unreachable!()
    };
    spec.candidate_weights[1] = 6000;
    let fetches = releases.fetches.load(Ordering::Relaxed);
    assert_code(run(store.prepare_rollout(conflicting)), Code::StateConflict);
    assert_eq!(releases.fetches.load(Ordering::Relaxed), fetches);
    let bob = TenantId("bob".into());
    assert!(store.get_rollout(&bob, &id()).unwrap().is_none());
    assert_eq!(
        store.get_rollout_operation(&bob, &id(), "start").unwrap(),
        RolloutOperationLookup::Unknown
    );
    let mut skipped = change("skip", 1, RolloutCommand::Advance { next_step: 2 });
    assert_code(
        run(store.prepare_rollout(skipped.clone())),
        Code::StateConflict,
    );
    let RolloutRequest::Change { context, .. } = &mut skipped else {
        unreachable!()
    };
    context.tenant = bob;
    assert_code(run(store.prepare_rollout(skipped)), Code::NotFound);
}

#[test]
fn receipt_ring_evicts_only_history_and_reopens_under_higher_recovery_ceiling() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let limits = RolloutLimits {
        maximum_receipts: 2,
        ..RolloutLimits::default()
    };
    let store = run(Store::open_inner_with_limits(
        &root.0,
        releases.clone(),
        Limits::default(),
        super::super::Source::default(),
        None,
        None,
        None,
        limits,
    ))
    .unwrap();
    let request = setup(&store, &releases);
    execute(&store, request.clone());
    execute(&store, change("pause", 1, RolloutCommand::Pause));
    execute(&store, change("resume", 2, RolloutCommand::Resume));
    assert_eq!(
        store
            .get_rollout_operation(&alice(), &id(), "start")
            .unwrap(),
        RolloutOperationLookup::Unknown
    );
    assert_eq!(
        store
            .get_rollout(&alice(), &id())
            .unwrap()
            .unwrap()
            .retained_operation_floor,
        2
    );
    assert_code(run(store.prepare_rollout(request)), Code::StateConflict);
    let page = store
        .list_rollouts(RolloutPageRequest {
            tenant: alice(),
            service: None,
            state: None,
            cursor: None,
            limit: 1,
            maximum_bytes: MAX_PAGE_BYTES,
        })
        .unwrap();
    assert_eq!(page.rollouts.len(), 1);
    assert_eq!(page.rollouts[0].retained_operation_floor, 2);
    assert!(page.next_cursor.is_none());
    drop(store);
    let store = run(Store::open_inner_with_limits(
        &root.0,
        releases,
        Limits::default(),
        super::super::Source::default(),
        None,
        None,
        None,
        RolloutLimits::recovery_maximum(),
    ))
    .unwrap();
    assert_eq!(
        store
            .get_rollout(&alice(), &id())
            .unwrap()
            .unwrap()
            .revision,
        3
    );
    assert_eq!(store.read_publication().rollouts.data.receipt_slots, 2);
    execute(
        &store,
        change("pause-after-recovery", 3, RolloutCommand::Pause),
    );
    assert_eq!(store.read_publication().rollouts.data.receipts.len(), 2);
    assert_eq!(
        store
            .get_rollout_operation(&alice(), &id(), "pause")
            .unwrap(),
        RolloutOperationLookup::Unknown
    );
}
