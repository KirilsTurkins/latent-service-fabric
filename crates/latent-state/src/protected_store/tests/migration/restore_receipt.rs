//! Actual sealed root/checkpoint observations. Controlled owner callbacks do
//! not qualify authenticated management, a new boot or external reconciliation.
use super::*;
use crate::protected_store::{RestoreStageError, RestoreStageOwners, RestoreStageRequest};
use fixture::StageOwners;

fn review(
    setup: &Setup,
    snapshot: ProtectedSnapshot,
    expected: RestoreInputPrecondition,
    owners: &Arc<StageOwners>,
) -> (ProtectedSnapshot, ProtectedRestoreInput) {
    let (snapshot, input) = wait(
        setup
            .owner
            .review_restore_window(snapshot, expected, owners.input_owners())
            .unwrap(),
    )
    .unwrap();
    (snapshot, input.unwrap().unwrap())
}

fn recover(
    setup: &Setup,
    snapshot: ProtectedSnapshot,
    input: ProtectedRestoreInput,
    request: RestoreStageRequest,
    owners: &Arc<StageOwners>,
) -> (
    ProtectedSnapshot,
    Result<RestoreStageReceipt, RestoreStageError>,
) {
    let (snapshot, result) = wait(
        setup
            .owner
            .recover_restore_receipt(
                snapshot,
                input,
                request,
                Arc::clone(owners) as Arc<dyn RestoreStageOwners>,
            )
            .unwrap(),
    )
    .unwrap();
    (snapshot, result.unwrap())
}

fn expected(input: &ProtectedRestoreInput) -> RestoreInputPrecondition {
    RestoreInputPrecondition {
        snapshot_digest: input.snapshot().snapshot_digest,
        manifest_digest: input.snapshot().manifest_digest,
    }
}

#[test]
fn lost_stage_receipt_is_recovered_without_reimport_or_checkpoint_advance_and_retains_original() {
    let mut setup = Setup::with_restore_destination();
    let (root, _) = super::super::fixture();
    let (checkpoint, _) = super::super::fixture();
    let (snapshot, input, owners, request) = restore_stage::prepare(
        &setup,
        restore_stage::destination(root.path(), checkpoint.path(), 4 * 1024 * 1024),
    );
    let (snapshot, staged) = wait(restore_stage::job(
        &setup,
        snapshot,
        input,
        &owners,
        request.clone(),
    ))
    .unwrap();
    let staged = staged.unwrap().unwrap();
    let original_checkpoint = staged.checkpoint().clone();
    let original_rows = staged.imported_rows();
    let original_operation = staged.operation_digest();
    let expected = expected(staged.input());
    let writes = owners.writes.load(Ordering::SeqCst);
    let source_before = fs::read(setup.source_path()).unwrap();
    let archive_before = fs::read(setup.checkpoint_path()).unwrap();
    let checkpoint_before = fs::read(checkpoint.path().join("transaction-checkpoint.v1")).unwrap();
    drop(staged); // The service still owns the original physical custody.
    let (snapshot, input) = review(&setup, snapshot, expected, &owners);
    let (snapshot, receipt) = recover(&setup, snapshot, input, request, &owners);
    let receipt = receipt.unwrap();
    assert_eq!(receipt.checkpoint(), &original_checkpoint);
    assert_eq!(receipt.imported_rows(), original_rows);
    assert_eq!(receipt.operation_digest(), original_operation);
    assert_eq!(owners.writes.load(Ordering::SeqCst), writes);
    assert_eq!(fs::read(setup.source_path()).unwrap(), source_before);
    assert_eq!(fs::read(setup.checkpoint_path()).unwrap(), archive_before);
    assert_eq!(
        fs::read(checkpoint.path().join("transaction-checkpoint.v1")).unwrap(),
        checkpoint_before
    );
    assert_eq!(setup.owner.failure(), None);
    let original = Arc::downgrade(setup.original());
    setup.release_original();
    drop(owners);
    setup.retire(snapshot);
    assert!(original.upgrade().is_some());
    assert_eq!(setup.native.snapshot().unwrap().recovery.slots, 1);
    receipt.check().unwrap();
    drop(receipt);
    assert!(original.upgrade().is_none());
    assert_eq!(setup.native.snapshot().unwrap().recovery.slots, 0);
    assert!(finish(&setup.owner).clean);
}

#[test]
fn recovered_stage_receipt_requires_exact_original_operation_operator_and_loss_window() {
    let setup = Setup::with_restore_destination();
    let (root, _) = super::super::fixture();
    let (checkpoint, _) = super::super::fixture();
    let (snapshot, input, owners, request) = restore_stage::prepare(
        &setup,
        restore_stage::destination(root.path(), checkpoint.path(), 4 * 1024 * 1024),
    );
    let (mut snapshot, staged) = wait(restore_stage::job(
        &setup,
        snapshot,
        input,
        &owners,
        request.clone(),
    ))
    .unwrap();
    let staged = staged.unwrap().unwrap();
    let snapshot_digest = staged.input().snapshot().snapshot_digest;
    let manifest_digest = staged.input().snapshot().manifest_digest;
    let checkpoint_before = fs::read(checkpoint.path().join("transaction-checkpoint.v1")).unwrap();
    let writes = owners.writes.load(Ordering::SeqCst);
    drop(staged);
    for mismatch in 0..3 {
        let (current, input) = review(
            &setup,
            snapshot,
            RestoreInputPrecondition {
                snapshot_digest,
                manifest_digest,
            },
            &owners,
        );
        let mut changed = request.clone();
        match mismatch {
            0 => changed.operation_id = "different-restore-operation".into(),
            1 => changed.operator_id = "different-operator".into(),
            _ => changed.loss_window_acknowledgement = [99; 32],
        }
        let (current, refused) = recover(&setup, current, input, changed, &owners);
        assert_eq!(
            refused.err(),
            Some(RestoreStageError::Review(StoreError::Conflict))
        );
        assert_eq!(owners.writes.load(Ordering::SeqCst), writes);
        assert_eq!(
            fs::read(checkpoint.path().join("transaction-checkpoint.v1")).unwrap(),
            checkpoint_before
        );
        assert_eq!(setup.owner.failure(), None);
        snapshot = current;
    }
    setup.retire(snapshot);
    setup.require_census();
    assert!(finish(&setup.owner).clean);
}

#[test]
fn recovered_stage_receipt_rechecks_each_current_owner_without_mutation() {
    let setup = Setup::with_restore_destination();
    let (root, _) = super::super::fixture();
    let (checkpoint, _) = super::super::fixture();
    let (snapshot, input, owners, request) = restore_stage::prepare(
        &setup,
        restore_stage::destination(root.path(), checkpoint.path(), 4 * 1024 * 1024),
    );
    let (mut snapshot, staged) = wait(restore_stage::job(
        &setup,
        snapshot,
        input,
        &owners,
        request.clone(),
    ))
    .unwrap();
    let staged = staged.unwrap().unwrap();
    let snapshot_digest = staged.input().snapshot().snapshot_digest;
    let manifest_digest = staged.input().snapshot().manifest_digest;
    let checkpoint_before = fs::read(checkpoint.path().join("transaction-checkpoint.v1")).unwrap();
    let writes = owners.writes.load(Ordering::SeqCst);
    drop(staged);
    for owner in 1..=4 {
        let (current, input) = review(
            &setup,
            snapshot,
            RestoreInputPrecondition {
                snapshot_digest,
                manifest_digest,
            },
            &owners,
        );
        owners.revoked.store(owner, Ordering::SeqCst);
        let (current, refused) = recover(&setup, current, input, request.clone(), &owners);
        assert_eq!(
            refused.err(),
            Some(RestoreStageError::Review(StoreError::Unavailable))
        );
        assert_eq!(owners.writes.load(Ordering::SeqCst), writes);
        assert_eq!(
            fs::read(checkpoint.path().join("transaction-checkpoint.v1")).unwrap(),
            checkpoint_before
        );
        assert_eq!(setup.owner.failure(), None);
        owners.revoked.store(0, Ordering::SeqCst);
        snapshot = current;
    }
    setup.retire(snapshot);
    setup.require_census();
    assert!(finish(&setup.owner).clean);
}

#[test]
fn incomplete_stage_cannot_recover_a_receipt_or_seal_an_interrupted_checkpoint() {
    let setup = Setup::with_restore_destination();
    let (root, _) = super::super::fixture();
    let (checkpoint, _) = super::super::fixture();
    let (snapshot, input, owners, request) = restore_stage::prepare(
        &setup,
        restore_stage::destination(root.path(), checkpoint.path(), 4 * 1024 * 1024),
    );
    let expected = expected(&input);
    let (gates, receiver) =
        owners.pause_kind(crate::protected_store::RestoreWriteKind::SealCheckpoint);
    let work = restore_stage::job(&setup, snapshot, input, &owners, request.clone());
    let ticket = receiver.recv_timeout(WATCHDOG).unwrap();
    owners.revoked.store(1, Ordering::SeqCst);
    gates.release(ticket).unwrap();
    let (snapshot, staged) = wait(work).unwrap();
    assert_eq!(
        staged.unwrap().err(),
        Some(RestoreStageError::Checkpoint(StoreError::Unavailable))
    );
    owners.revoked.store(0, Ordering::SeqCst);
    let writes = owners.writes.load(Ordering::SeqCst);
    let (snapshot, input) = review(&setup, snapshot, expected, &owners);
    let (snapshot, refused) = recover(&setup, snapshot, input, request, &owners);
    assert_eq!(
        refused.err(),
        Some(RestoreStageError::Review(StoreError::Conflict))
    );
    assert_eq!(owners.writes.load(Ordering::SeqCst), writes);
    assert_eq!(
        fs::read(checkpoint.path().join("transaction-checkpoint.v1")).unwrap(),
        b""
    );
    assert_eq!(setup.owner.failure(), None);
    setup.retire(snapshot);
    setup.require_census();
    assert!(finish(&setup.owner).clean);
}

#[test]
fn recovered_stage_receipt_rereads_actual_checkpoint_and_refuses_corruption() {
    let setup = Setup::with_restore_destination();
    let (root, _) = super::super::fixture();
    let (checkpoint, _) = super::super::fixture();
    let (snapshot, input, owners, request) = restore_stage::prepare(
        &setup,
        restore_stage::destination(root.path(), checkpoint.path(), 4 * 1024 * 1024),
    );
    let (snapshot, staged) = wait(restore_stage::job(
        &setup,
        snapshot,
        input,
        &owners,
        request.clone(),
    ))
    .unwrap();
    let staged = staged.unwrap().unwrap();
    let expected = expected(staged.input());
    drop(staged);
    let (snapshot, input) = review(&setup, snapshot, expected, &owners);
    let path = checkpoint.path().join("transaction-checkpoint.v1");
    let mut actual = fs::read(&path).unwrap();
    *actual.last_mut().unwrap() ^= 1; // Controlled corruption of the owned file.
    fs::write(&path, &actual).unwrap();
    let writes = owners.writes.load(Ordering::SeqCst);
    let (snapshot, refused) = recover(&setup, snapshot, input, request, &owners);
    assert_eq!(
        refused.err(),
        Some(RestoreStageError::Checkpoint(StoreError::Corrupt))
    );
    assert_eq!(owners.writes.load(Ordering::SeqCst), writes);
    assert_eq!(fs::read(&path).unwrap(), actual);
    setup.retire(snapshot);
    setup.require_census();
    assert!(finish(&setup.owner).clean);
}

#[test]
fn recovered_stage_receipt_requires_original_read_fence_consumption_and_same_installed_owner() {
    let setup = Setup::with_restore_destination();
    let (root, _) = super::super::fixture();
    let (checkpoint, _) = super::super::fixture();
    let (snapshot, input, owners, request) = restore_stage::prepare(
        &setup,
        restore_stage::destination(root.path(), checkpoint.path(), 4 * 1024 * 1024),
    );
    let (snapshot, staged) = wait(restore_stage::job(
        &setup,
        snapshot,
        input,
        &owners,
        request.clone(),
    ))
    .unwrap();
    let staged = staged.unwrap().unwrap();
    let snapshot_digest = staged.input().snapshot().snapshot_digest;
    let manifest_digest = staged.input().snapshot().manifest_digest;
    drop(staged);
    let checkpoint_before = fs::read(checkpoint.path().join("transaction-checkpoint.v1")).unwrap();
    let writes = owners.writes.load(Ordering::SeqCst);
    let (snapshot, input) = review(
        &setup,
        snapshot,
        RestoreInputPrecondition {
            snapshot_digest,
            manifest_digest,
        },
        &owners,
    );
    let replacement = Arc::new(StageOwners::new(&setup, &owners.input_owners()));
    let (snapshot, refused) = recover(&setup, snapshot, input, request.clone(), &replacement);
    assert_eq!(
        refused.err(),
        Some(RestoreStageError::Review(StoreError::Conflict))
    );
    drop(replacement);
    let (snapshot, input) = review(
        &setup,
        snapshot,
        RestoreInputPrecondition {
            snapshot_digest,
            manifest_digest,
        },
        &owners,
    );
    owners.input_owners().accept_mode.store(2, Ordering::SeqCst);
    let (snapshot, refused) = recover(&setup, snapshot, input, request, &owners);
    assert_eq!(
        refused.err(),
        Some(RestoreStageError::Review(StoreError::Invalid))
    );
    owners.input_owners().accept_mode.store(0, Ordering::SeqCst);
    assert_eq!(owners.writes.load(Ordering::SeqCst), writes);
    assert_eq!(
        fs::read(checkpoint.path().join("transaction-checkpoint.v1")).unwrap(),
        checkpoint_before
    );
    assert_eq!(setup.owner.failure(), None);
    setup.retire(snapshot);
    setup.require_census();
    assert!(finish(&setup.owner).clean);
}

#[test]
fn detached_receipt_reader_keeps_real_views_custody_and_original_capacity_until_retirement() {
    let mut setup = Setup::with_restore_destination();
    let (root, _) = super::super::fixture();
    let (checkpoint, _) = super::super::fixture();
    let (snapshot, input, owners, request) = restore_stage::prepare(
        &setup,
        restore_stage::destination(root.path(), checkpoint.path(), 4 * 1024 * 1024),
    );
    let (snapshot, staged) = wait(restore_stage::job(
        &setup,
        snapshot,
        input,
        &owners,
        request.clone(),
    ))
    .unwrap();
    let staged = staged.unwrap().unwrap();
    let expected = expected(staged.input());
    drop(staged);
    let (snapshot, input) = review(&setup, snapshot, expected, &owners);
    let checkpoint_before = fs::read(checkpoint.path().join("transaction-checkpoint.v1")).unwrap();
    let (gates, receiver) = owners.pause_receipt_review();
    let original = Arc::downgrade(setup.original());
    let installed = Arc::downgrade(&owners);
    let work = setup
        .owner
        .recover_restore_receipt(
            snapshot,
            input,
            request,
            Arc::clone(&owners) as Arc<dyn RestoreStageOwners>,
        )
        .unwrap();
    let ticket = receiver.recv_timeout(WATCHDOG).unwrap();
    drop(work); // Accepted worker still holds actual source and staged views.
    drop(owners);
    setup.release_original();
    setup.owner.close();
    let mut drain = Box::pin(
        setup
            .owner
            .drain_async(Instant::now() + WATCHDOG, std::future::pending())
            .unwrap(),
    );
    PollProbe::default().pending(drain.as_mut());
    assert!(original.upgrade().is_some());
    assert!(installed.upgrade().is_some());
    assert!(setup.owner.snapshot().unwrap().custody_active);
    assert_eq!(setup.native.snapshot().unwrap().recovery.slots, 1);
    assert!(root.path().join("transaction-state.redb").exists());
    assert_eq!(
        fs::read(checkpoint.path().join("transaction-checkpoint.v1")).unwrap(),
        checkpoint_before
    );
    gates.release(ticket).unwrap();
    let shutdown = wait(drain);
    assert!(shutdown.clean);
    assert!(shutdown.snapshot.physically_retired());
    assert!(original.upgrade().is_none());
    assert!(installed.upgrade().is_none());
    assert_eq!(setup.native.snapshot().unwrap().recovery.slots, 0);
    assert_eq!(
        fs::read(checkpoint.path().join("transaction-checkpoint.v1")).unwrap(),
        checkpoint_before
    );
}
