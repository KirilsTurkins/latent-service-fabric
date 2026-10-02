//! Real rooted engine/file/Recovery custody schedules. The installed review and
//! mutation callbacks below are controlled fixtures, not authenticated RPC,
//! deployment, provider retirement or external anti-rollback qualification.
use super::*;
use crate::{
    namespace::{history::HistoryStatus, NamespaceStatus},
    recovery::{
        migration::{MigrationAction, MigrationError, MigrationPhase},
        snapshot::SnapshotError,
    },
};
use fixture::{Owners, Setup};
use std::sync::atomic::Ordering;

mod fixture;

#[test]
fn original_protected_file_stages_completes_and_replays_without_releasing_custody() {
    let setup = Setup::new();
    let (snapshot, owners, request) = setup.checkpoint();
    let (snapshot, staged) = setup.migrate(snapshot, &owners, &request, MigrationPhase::Stage);
    let staged = staged.unwrap().unwrap();
    assert_eq!(staged.action(), MigrationAction::Stage);
    assert!(!staged.progress().completed());
    let original_progress = staged.progress().encode().unwrap();
    assert!(setup.owner.snapshot().unwrap().custody_active);
    assert_eq!(setup.native.snapshot().unwrap().recovery.slots, 1);
    assert!(matches!(
        setup
            .owner
            .with_store(StoreIoKind::RecoveryRead, 0, |_| Ok(())),
        Err(ProtectedStoreError::Io(StoreIoError::CustodyBusy))
    ));
    let (snapshot, replay) = setup.migrate(snapshot, &owners, &request, MigrationPhase::Stage);
    let replay = replay.unwrap().unwrap();
    assert_eq!(replay.action(), MigrationAction::Replay);
    assert_eq!(replay.progress().encode().unwrap(), original_progress);
    let (snapshot, completed) =
        setup.migrate(snapshot, &owners, &request, MigrationPhase::Complete);
    let completed = completed.unwrap().unwrap();
    assert_eq!(completed.action(), MigrationAction::Complete);
    assert!(completed.progress().completed());
    let exact_receipt = completed.progress().encode().unwrap();
    let (snapshot, replay) = setup.migrate(snapshot, &owners, &request, MigrationPhase::Complete);
    assert_eq!(
        replay.as_ref().unwrap().as_ref().unwrap().action(),
        MigrationAction::Replay
    );
    assert_eq!(
        replay.unwrap().unwrap().progress().encode().unwrap(),
        exact_receipt
    );
    setup.retire(snapshot);
    let observed = setup.observe();
    assert_eq!(observed.progress.unwrap(), exact_receipt);
    assert_eq!(observed.value.len(), 12);
    assert_eq!(&observed.value[..4], b"AG\x02\0");
    assert_eq!(observed.status, NamespaceStatus::Quiescing);
    assert_eq!(observed.history, HistoryStatus::ReconciliationRequired);
    setup.require_census();
    assert!(finish(&setup.owner).clean);
}

#[test]
fn reopened_original_checkpoint_completes_only_exact_persisted_incomplete_operation() {
    let setup = Setup::new();
    let (snapshot, owners, request) = setup.checkpoint();
    let (snapshot, stage) = setup.migrate(snapshot, &owners, &request, MigrationPhase::Stage);
    let staged_bytes = stage.unwrap().unwrap().progress().encode().unwrap();
    let checkpoint_bytes = fs::read(setup.checkpoint_path()).unwrap();
    setup.retire(snapshot);
    assert_eq!(setup.observe().progress.unwrap(), staged_bytes);
    let reopened = setup.restart();
    let snapshot = reopened.open_checkpoint().unwrap();
    assert_eq!(
        fs::read(reopened.checkpoint_path()).unwrap(),
        checkpoint_bytes
    );
    let owners = Arc::new(Owners::new(Arc::clone(&reopened.seed)));
    let (snapshot, completed) =
        reopened.migrate(snapshot, &owners, &request, MigrationPhase::Complete);
    assert_eq!(
        completed.unwrap().unwrap().action(),
        MigrationAction::Complete
    );
    reopened.retire(snapshot);
    assert_eq!(reopened.observe().value.len(), 12);
    reopened.require_census();
    assert!(finish(&reopened.owner).clean);
}

#[test]
fn original_current_refusal_ignored_native_fence_and_foreign_owner_never_publish_progress() {
    let setup = Setup::new();
    let (snapshot, owners, request) = setup.checkpoint();
    owners.accept_mode.store(1, Ordering::SeqCst);
    let (snapshot, denied) = setup.migrate(snapshot, &owners, &request, MigrationPhase::Stage);
    assert!(matches!(
        denied.unwrap(),
        Err(MigrationError::Review(StoreError::Unavailable))
    ));
    owners.accept_mode.store(2, Ordering::SeqCst);
    let (snapshot, ignored) = setup.migrate(snapshot, &owners, &request, MigrationPhase::Stage);
    assert!(matches!(
        ignored.unwrap(),
        Err(MigrationError::Review(StoreError::Invalid))
    ));
    owners.accept_mode.store(0, Ordering::SeqCst);
    let foreign = Arc::new(Owners::new(Arc::clone(&setup.seed)));
    let (snapshot, foreign) = setup.migrate(snapshot, &foreign, &request, MigrationPhase::Stage);
    assert!(matches!(
        foreign.unwrap(),
        Err(MigrationError::Review(StoreError::Conflict))
    ));
    setup.retire(snapshot);
    let observed = setup.observe();
    assert!(observed.progress.is_none());
    assert_eq!(observed.value, u64::MAX.to_le_bytes());
    assert_eq!(observed.history, HistoryStatus::Ready);
    assert_eq!(setup.owner.failure(), None);
    setup.require_census();
    assert!(finish(&setup.owner).clean);
}

#[test]
fn held_physical_review_observes_final_current_revocation_without_publishing_a_marker() {
    let setup = Setup::new();
    let (snapshot, owners, request) = setup.checkpoint();
    let (gates, receiver) = owners.pause_review();
    let job = setup.job(snapshot, &owners, &request, MigrationPhase::Stage);
    let ticket = receiver.recv_timeout(WATCHDOG).unwrap();
    assert!(setup.owner.snapshot().unwrap().custody_active);
    assert_eq!(setup.native.snapshot().unwrap().recovery.slots, 1);
    owners.accept_mode.store(1, Ordering::SeqCst);
    gates.release(ticket).unwrap();
    let (snapshot, denied) = wait(job).unwrap();
    assert!(matches!(
        denied.unwrap(),
        Err(MigrationError::Review(StoreError::Unavailable))
    ));
    setup.retire(snapshot);
    assert!(setup.observe().progress.is_none());
    assert_eq!(setup.observe().value, u64::MAX.to_le_bytes());
    assert_eq!(setup.owner.failure(), None);
    setup.require_census();
    assert!(finish(&setup.owner).clean);
}

#[test]
fn detached_migration_waiter_retains_original_native_and_file_until_actual_worker_retirement() {
    let mut setup = Setup::new();
    let (snapshot, owners, request) = setup.checkpoint();
    let (gates, receiver) = owners.pause_review();
    let weak_original = Arc::downgrade(setup.original());
    let weak_owners = Arc::downgrade(&owners);
    let job = setup.job(snapshot, &owners, &request, MigrationPhase::Stage);
    let ticket = receiver.recv_timeout(WATCHDOG).unwrap();
    drop(job);
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
    assert!(weak_original.upgrade().is_some());
    assert!(weak_owners.upgrade().is_some());
    assert!(setup.owner.snapshot().unwrap().custody_active);
    assert_eq!(setup.native.snapshot().unwrap().recovery.slots, 1);
    gates.release(ticket).unwrap();
    let outcome = wait(drain);
    assert!(outcome.clean);
    assert!(outcome.snapshot.physically_retired());
    assert!(weak_owners.upgrade().is_none());
    assert!(weak_original.upgrade().is_none());
    assert_eq!(setup.native.snapshot().unwrap().recovery.slots, 0);
    let reopened = setup.restart_retired();
    assert!(reopened.observe().progress.is_some());
    assert_eq!(reopened.observe().value.len(), 8);
    assert_eq!(
        reopened.observe().history,
        HistoryStatus::ReconciliationRequired
    );
    assert!(finish(&reopened.owner).clean);
}

#[test]
fn original_deadline_elapsed_during_physical_review_cannot_commit_or_renew() {
    let clock = TestClock::new(1000, Instant::now(), 1);
    let setup = Setup::with_clock(Arc::new(clock.clone()));
    let (snapshot, owners, request) = setup.checkpoint();
    let deadline = setup.original().original_deadline();
    let (gates, receiver) = owners.pause_review();
    let job = setup.job(snapshot, &owners, &request, MigrationPhase::Stage);
    let ticket = receiver.recv_timeout(WATCHDOG).unwrap();
    clock.advance(std::time::Duration::from_secs(31));
    assert!(setup.original().with_live(|| ()).is_err());
    assert_eq!(setup.original().original_deadline(), deadline);
    assert_eq!(setup.native.snapshot().unwrap().recovery.slots, 1);
    gates.release(ticket).unwrap();
    let (snapshot, refused) = wait(job).unwrap();
    assert!(matches!(
        refused.unwrap(),
        Err(MigrationError::Review(StoreError::Unavailable) | MigrationError::Deadline)
    ));
    assert_eq!(setup.owner.failure(), None);
    setup.retire(snapshot);
    assert!(setup.observe().progress.is_none());
    assert_eq!(setup.observe().value.len(), 8);
    assert!(
        wait(
            setup
                .owner
                .drain_async(clock.monotonic_now() + WATCHDOG, std::future::pending())
                .unwrap()
        )
        .clean
    );
}

#[test]
fn partial_or_missing_existing_checkpoint_refuses_without_recreation_or_source_quarantine() {
    let setup = Setup::new();
    let (snapshot, _owners, _request) = setup.checkpoint();
    setup.retire(snapshot);
    let path = setup.checkpoint_path();
    let original = fs::read(&path).unwrap();
    let partial = &original[..original.len() / 2];
    fs::write(&path, partial).unwrap(); // Explicit operator-input fault fixture.
    assert!(setup.open_checkpoint().is_err());
    assert_eq!(fs::read(&path).unwrap(), partial);
    assert_eq!(setup.owner.failure(), None);
    fs::remove_file(&path).unwrap();
    assert!(setup.open_checkpoint().is_err());
    assert!(!path.exists());
    assert!(setup.observe().progress.is_none());
    assert!(finish(&setup.owner).clean);
}

#[test]
fn actual_source_uncertainty_uses_original_quarantine_and_positive_resource_cleanup() {
    let setup = Setup::new();
    let (snapshot, owners, request) = setup.checkpoint();
    owners.source_fault.store(true, Ordering::SeqCst);
    let (mut snapshot, refused) = setup.migrate(snapshot, &owners, &request, MigrationPhase::Stage);
    assert!(matches!(
        refused,
        Err(ProtectedStoreError::Store(StoreError::CommitUncertain))
    ));
    assert_eq!(
        setup.owner.failure(),
        Some(ProtectedStoreError::Store(StoreError::CommitUncertain))
    );
    let witness = snapshot.retirement_witness().unwrap();
    assert!(!witness.has_retired());
    assert_eq!(setup.native.snapshot().unwrap().recovery.slots, 1);
    setup.retire(snapshot);
    assert!(witness.has_retired());
    let report = finish(&setup.owner);
    assert!(!report.clean);
    assert!(report.snapshot.physically_retired());
    // A typed controlled source-I/O injection is not real device-fault or
    // proven-abort evidence and never authorizes an automatic retry.
}
