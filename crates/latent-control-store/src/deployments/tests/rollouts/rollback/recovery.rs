use super::*;
use sha2::{Digest, Sha256};

fn rewrite(
    root: &TempRoot,
    change: impl FnOnce(&mut crate::deployments::rollouts::table::TableData),
) {
    let path = root.0.join("catalog.json");
    let mut record: crate::deployments::persistence::Record =
        json::from_slice(&std::fs::read(&path).unwrap()).unwrap();
    change(&mut record.payload.control.as_mut().unwrap().rollouts);
    record.checksum = format!(
        "sha256:{:x}",
        Sha256::digest(json::to_vec(&record.payload).unwrap())
    );
    std::fs::write(path, json::to_vec(&record).unwrap()).unwrap();
}

#[test]
fn rollback_stage_and_rename_cutpoints_recover_one_whole_catalog_and_exact_receipt() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let store = open(&root, &releases);
    let start = setup(&store, &releases);
    execute(&store, start);
    let before = std::fs::read(root.0.join("catalog.json")).unwrap();
    let rollback = request("restore", 1);
    let prepared = run(store.prepare_rollout(rollback.clone())).unwrap();
    store.fail_before_rename.store(true, Ordering::SeqCst);
    assert_code(store.commit_rollout(prepared), Code::Unavailable);
    assert_eq!(std::fs::read(root.0.join("catalog.json")).unwrap(), before);
    drop(store);
    let store = open(&root, &releases);
    assert_eq!(
        store.get_rollout(&alice(), &id()).unwrap().unwrap().state,
        RolloutState::Running
    );
    assert_eq!(run(store.list()).unwrap().len(), 2);
    let prepared = run(store.prepare_rollout(rollback.clone())).unwrap();
    store.fail_parent_sync.store(true, Ordering::SeqCst);
    let uncertain = store.commit_rollout(prepared).unwrap();
    assert!(uncertain.durability.is_err());
    assert_eq!(uncertain.receipt.state, RolloutState::RolledBack);
    assert_eq!(run(store.list()).unwrap().len(), 1);
    assert_eq!(run(store.list()).unwrap()[0].id.0, "base");
    assert_eq!(
        store
            .get_rollout_operation(&alice(), &id(), "restore")
            .unwrap(),
        RolloutOperationLookup::Uncertain
    );
    assert_code(
        run(store.prepare_rollout(rollback.clone())),
        Code::Unavailable,
    );
    drop(store);
    let store = open(&root, &releases);
    assert_eq!(
        store.get_rollout(&alice(), &id()).unwrap().unwrap().state,
        RolloutState::RolledBack
    );
    assert_eq!(execute(&store, rollback).receipt, uncertain.receipt);
    assert_eq!(store.generation(), RouteGeneration(3));
}

#[test]
fn old_rows_without_target_preserve_encoding_and_replay_but_cannot_restore() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let store = open(&root, &releases);
    let start = setup(&store, &releases);
    execute(&store, start.clone());
    drop(store);
    rewrite(&root, |data| {
        let row = &mut data.rows[0];
        row.status.rollback_target = None;
        row.status.plan_digest = crate::deployments::rollouts::table::plan_hash(row).unwrap();
        for stored in &mut data.receipts {
            stored.receipt.plan_digest = row.status.plan_digest.clone();
            stored.receipt.receipt_digest =
                crate::deployments::rollouts::table::receipt_hash(&stored.receipt).unwrap();
        }
    });
    let before = std::fs::read(root.0.join("catalog.json")).unwrap();
    let store = open(&root, &releases);
    let status = store.get_rollout(&alice(), &id()).unwrap().unwrap();
    assert!(status.rollback_target.is_none());
    assert!(json::to_value(&status)
        .unwrap()
        .get("rollbackTarget")
        .is_none());
    assert!(execute(&store, start).replayed);
    let failure = run(store.prepare_rollout(request("restore", 1)))
        .err()
        .unwrap();
    assert_eq!(failure.code, Code::Unavailable);
    assert_eq!(failure.message, "rollout-rollback-target-unavailable");
    assert_eq!(std::fs::read(root.0.join("catalog.json")).unwrap(), before);
    assert_eq!(
        store
            .get_rollout_operation(&alice(), &id(), "restore")
            .unwrap(),
        RolloutOperationLookup::Unknown
    );
}

#[test]
fn target_and_terminal_cohort_corruption_fail_even_with_recomputed_outer_checksum() {
    for mutation in 0..3 {
        let root = TempRoot::new();
        let releases = Arc::new(Releases::default());
        let store = open(&root, &releases);
        let start = setup(&store, &releases);
        execute(&store, start);
        execute(&store, request("restore", 1));
        drop(store);
        rewrite(&root, |data| match mutation {
            0 => {
                data.rows[0]
                    .status
                    .rollback_target
                    .as_mut()
                    .unwrap()
                    .historical_route_generation = RouteGeneration(3);
            }
            1 => data.rows[0].cohort[0].id = "candidate".into(),
            2 => data.receipts.last_mut().unwrap().receipt.rollback_target = None,
            _ => unreachable!(),
        });
        assert_code(
            run(Store::open(&root.0, releases, Limits::default())),
            Code::CorruptArtifact,
        );
    }
}
