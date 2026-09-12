use super::*;

mod recovery;
mod trust;

fn request(operation: &str, revision: u64) -> RolloutRequest {
    change(
        operation,
        revision,
        RolloutCommand::Rollback {
            target_generation: RouteGeneration(1),
        },
    )
}

#[test]
fn completed_rollback_restores_exact_original_manifest_with_new_generation_and_retained_pins() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let store = open(&root, &releases);
    let start = setup(&store, &releases);
    let original = run(DeploymentStore::get(&store, &DeploymentId("base".into())))
        .unwrap()
        .unwrap();
    execute(&store, start);
    execute(
        &store,
        change("advance", 1, RolloutCommand::Advance { next_step: 1 }),
    );
    execute(
        &store,
        change("complete", 2, RolloutCommand::Advance { next_step: 2 }),
    );
    let old_pin = store.pin().unwrap();
    let old_selection = old_pin
        .resolve(&target("alice", None), Some("held-call"))
        .unwrap();
    let old_policy = old_pin.admission_policy(&old_selection).unwrap();
    let rollback = request("restore", 3);
    let result = execute(&store, rollback.clone());
    assert_eq!(result.receipt.action, RolloutAction::Rollback);
    assert_eq!(result.receipt.state, RolloutState::RolledBack);
    assert_eq!(result.receipt.reason, RolloutReason::RollbackApplied);
    assert_eq!(result.receipt.route_generation, RouteGeneration(5));
    assert_eq!(
        result
            .receipt
            .rollback_target
            .as_ref()
            .unwrap()
            .historical_route_generation,
        RouteGeneration(1)
    );
    assert_eq!(run(store.list()).unwrap(), vec![original.clone()]);
    assert_eq!(
        old_pin
            .resolve(&target("alice", None), Some("held-call"))
            .unwrap(),
        old_selection
    );
    assert_eq!(
        old_pin.admission_policy(&old_selection).unwrap(),
        old_policy
    );
    let current = store
        .pin()
        .unwrap()
        .resolve(&target("alice", None), Some("held-call"))
        .unwrap();
    assert_eq!(current.release, original.release);
    assert_ne!(current.release, old_selection.release);
    assert!(current.route_generation > old_selection.route_generation);
    let status = store.get_rollout(&alice(), &id()).unwrap().unwrap();
    assert_eq!(status.current_step, 2); // Historical progress, not restored route weights.
    assert_eq!(status.objects.len(), 1);
    assert_eq!(status.objects[0].generation, 5);
    let fetches = releases.fetches.load(Ordering::Relaxed);
    assert_eq!(execute(&store, rollback.clone()).receipt, result.receipt);
    assert_eq!(releases.fetches.load(Ordering::Relaxed), fetches);
    assert_code(
        run(store.prepare_rollout(request("repeat", 4))),
        Code::StateConflict,
    );
    drop(store);
    let store = open(&root, &releases);
    assert_eq!(run(store.list()).unwrap(), vec![original]);
    assert_eq!(execute(&store, rollback).receipt, result.receipt);
}

#[test]
fn running_paused_and_aborted_rows_restore_without_resetting_historical_steps() {
    for action in [
        None,
        Some(RolloutCommand::Pause),
        Some(RolloutCommand::Abort),
    ] {
        let root = TempRoot::new();
        let releases = Arc::new(Releases::default());
        let store = open(&root, &releases);
        let start = setup(&store, &releases);
        execute(&store, start);
        let revision = if let Some(action) = action {
            execute(&store, change("stop", 1, action));
            2
        } else {
            1
        };
        let result = execute(&store, request("restore", revision));
        assert_eq!(result.receipt.state, RolloutState::RolledBack);
        assert_eq!(result.receipt.step, 0);
        let routes = run(store.list()).unwrap();
        assert_eq!(routes.len(), 1);
        assert_eq!(routes[0].id.0, "base");
        assert_eq!(routes[0].route_weight, 1);
    }
}

#[test]
fn selector_scope_revision_capacity_and_missing_target_leave_no_receipt_or_route_change() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let mut store = open(&root, &releases);
    let start = setup(&store, &releases);
    execute(&store, start);
    let before = std::fs::read(root.0.join("catalog.json")).unwrap();
    assert_code(
        run(store.prepare_rollout(request("stale", 2))),
        Code::StateConflict,
    );
    assert_code(
        run(store.prepare_rollout(change(
            "selector",
            1,
            RolloutCommand::Rollback {
                target_generation: RouteGeneration(2),
            },
        ))),
        Code::StateConflict,
    );
    let mut foreign = request("foreign", 1);
    let RolloutRequest::Change { context, .. } = &mut foreign else {
        unreachable!()
    };
    context.tenant = TenantId("bob".into());
    assert_code(run(store.prepare_rollout(foreign)), Code::NotFound);
    let base = store
        .get_rollout(&alice(), &id())
        .unwrap()
        .unwrap()
        .base
        .component;
    let original = releases.values.write().unwrap().remove(&base).unwrap();
    assert_code(
        run(store.prepare_rollout(request("missing", 1))),
        Code::NotFound,
    );
    releases.values.write().unwrap().insert(base, original);
    let maximum = store.config.max_state_bytes;
    store.config.max_state_bytes = 1;
    assert_code(
        run(store.prepare_rollout(request("capacity", 1))),
        Code::ResourceExhausted,
    );
    store.config.max_state_bytes = maximum;
    assert_eq!(std::fs::read(root.0.join("catalog.json")).unwrap(), before);
    for operation in ["stale", "selector", "foreign", "missing", "capacity"] {
        assert_eq!(
            store
                .get_rollout_operation(&alice(), &id(), operation)
                .unwrap(),
            RolloutOperationLookup::Unknown
        );
    }
    execute(&store, request("restore", 1));
}

#[test]
fn reverse_comparison_rejects_lost_candidate_functions_and_corrupt_source() {
    for corrupt in [false, true] {
        let root = TempRoot::new();
        let releases = Arc::new(Releases::default());
        let store = open(&root, &releases);
        let start = setup(&store, &releases);
        execute(&store, start);
        let candidate = store
            .get_rollout(&alice(), &id())
            .unwrap()
            .unwrap()
            .candidate
            .component;
        let mut values = releases.values.write().unwrap();
        let artifact = values.get_mut(&candidate).unwrap();
        if corrupt {
            artifact.component_bytes.push(0);
        } else {
            let interface = &mut artifact.contracts[0].interfaces[0];
            let mut added = interface.functions[0].clone();
            added.id.0 = "new-function".into();
            added.name = "new-function".into();
            interface.functions.push(added);
        }
        drop(values);
        let before = std::fs::read(root.0.join("catalog.json")).unwrap();
        assert_code(
            run(store.prepare_rollout(request("restore", 1))),
            if corrupt {
                Code::CorruptArtifact
            } else {
                Code::IncompatibleContract
            },
        );
        assert_eq!(std::fs::read(root.0.join("catalog.json")).unwrap(), before);
        assert_eq!(
            store
                .get_rollout_operation(&alice(), &id(), "restore")
                .unwrap(),
            RolloutOperationLookup::Unknown
        );
    }
}

#[test]
fn prepared_rollback_loses_to_manual_cas_and_parallel_control_uses_one_work_slot() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let store = open(&root, &releases);
    let start = setup(&store, &releases);
    execute(&store, start);
    let prepared = run(store.prepare_rollout(request("restore", 1))).unwrap();
    assert_code(
        run(store.prepare_rollout(change(
            "advance",
            1,
            RolloutCommand::Advance { next_step: 1 },
        ))),
        Code::ResourceExhausted,
    );
    let mut candidate = run(DeploymentStore::get(
        &store,
        &DeploymentId("candidate".into()),
    ))
    .unwrap()
    .unwrap();
    candidate.route_weight = 1234;
    run(store.apply(candidate.clone())).unwrap();
    assert_code(store.commit_rollout(prepared), Code::StateConflict);
    assert_eq!(
        run(DeploymentStore::get(&store, &candidate.id)).unwrap(),
        Some(candidate)
    );
    assert_eq!(
        store.get_rollout(&alice(), &id()).unwrap().unwrap().state,
        RolloutState::Conflicted
    );
    assert_code(
        run(store.prepare_rollout(request("restore-fresh", 1))),
        Code::StateConflict,
    );
    assert_eq!(
        store
            .get_rollout_operation(&alice(), &id(), "restore")
            .unwrap(),
        RolloutOperationLookup::Unknown
    );
}
