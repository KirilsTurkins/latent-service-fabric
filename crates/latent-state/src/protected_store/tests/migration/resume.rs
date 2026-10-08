//! Actual rooted file/engine/Recovery custody and response retirement schedules.
//! Reviewer decisions remain controlled fixtures, not authenticated Node proof.
use super::*;
use crate::recovery::{
    migration::{AggregateMigrationProgress, AggregateMigrationRequest},
    resume::{MigrationResumeAction, MigrationResumeRequest},
};

fn completed(setup: &Setup) -> (ProtectedSnapshot, Arc<Owners>, MigrationResumeRequest) {
    let (snapshot, owners, request) = setup.checkpoint();
    let (snapshot, staged) = setup.migrate(snapshot, &owners, &request, MigrationPhase::Stage);
    drop(staged.unwrap().unwrap());
    let (snapshot, complete) = setup.migrate(snapshot, &owners, &request, MigrationPhase::Complete);
    let complete = complete.unwrap().unwrap();
    let resume = resume_request(&request, complete.progress());
    (snapshot, owners, resume)
}

fn resume_request(
    migration: &AggregateMigrationRequest,
    progress: &AggregateMigrationProgress,
) -> MigrationResumeRequest {
    let namespace = progress.result_namespace().unwrap();
    MigrationResumeRequest {
        scope: crate::session::StateScope {
            tenant: namespace.tenant,
            namespace: namespace.id,
            incarnation: namespace.version.incarnation,
            state_schema: namespace.state_schema,
            entity: None,
            mode: crate::session::StateMode::Command,
        },
        operation_id: "activate-fixed-format".into(),
        operator_id: "operator".into(),
        expected_view: progress.result_view_token().unwrap(),
        migration: migration.clone(),
        review_digest: [91; 32],
    }
}

#[test]
fn real_completed_migration_activates_once_and_recovers_exact_receipt_after_restart() {
    let setup = Setup::new();
    let (snapshot, owners, request) = completed(&setup);
    let archive = fs::read(setup.checkpoint_path()).unwrap();
    let (snapshot, outcome) = wait(setup.resume_job(snapshot, &owners, request.clone())).unwrap();
    let outcome = outcome.unwrap().unwrap();
    assert_eq!(outcome.action(), MigrationResumeAction::Activate);
    let receipt = outcome.receipt().encode().unwrap();
    assert_eq!(fs::read(setup.checkpoint_path()).unwrap(), archive);
    drop(outcome);
    setup.retire(snapshot);
    assert_eq!(setup.observe().status, NamespaceStatus::Active);
    assert_eq!(setup.observe().history, HistoryStatus::Ready);
    let value = setup.observe().value;
    let progress = setup.observe().progress;
    setup.require_census();
    let reopened = setup.restart();
    let snapshot = reopened.open_checkpoint().unwrap();
    let owners = Arc::new(Owners::new(Arc::clone(&reopened.seed)));
    let (snapshot, replay) = wait(reopened.resume_job(snapshot, &owners, request)).unwrap();
    let replay = replay.unwrap().unwrap();
    assert_eq!(replay.action(), MigrationResumeAction::Replay);
    assert_eq!(replay.receipt().encode().unwrap(), receipt);
    drop(replay);
    reopened.retire(snapshot);
    assert_eq!(reopened.observe().value, value);
    assert_eq!(reopened.observe().progress, progress);
    assert_eq!(reopened.observe().status, NamespaceStatus::Active);
    reopened.require_census();
    assert!(finish(&reopened.owner).clean);
}

#[test]
fn resume_response_keeps_original_prepaid_capacity_after_positive_file_retirement() {
    let mut setup = Setup::new();
    let (snapshot, owners, request) = completed(&setup);
    let weak_original = Arc::downgrade(setup.original());
    let (snapshot, response) = wait(setup.resume_job(snapshot, &owners, request)).unwrap();
    let response = response.unwrap().unwrap();
    setup.release_original();
    setup.retire(snapshot);
    assert!(!setup.owner.snapshot().unwrap().custody_active);
    assert_eq!(setup.native.snapshot().unwrap().recovery.slots, 1);
    assert!(weak_original.upgrade().is_some());
    assert_eq!(
        response.receipt().namespace().unwrap().status,
        NamespaceStatus::Active
    );
    drop(response);
    assert!(weak_original.upgrade().is_none());
    assert_eq!(setup.native.snapshot().unwrap().recovery.slots, 0);
    setup.require_census();
    assert!(finish(&setup.owner).clean);
}

#[test]
fn held_resume_review_revocation_and_ignored_final_gate_leave_healthy_paused_source() {
    let setup = Setup::new();
    let (snapshot, owners, request) = completed(&setup);
    let (gates, receiver) = owners.pause_review();
    let job = setup.resume_job(snapshot, &owners, request.clone());
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
    owners.accept_mode.store(2, Ordering::SeqCst);
    let (snapshot, ignored) = wait(setup.resume_job(snapshot, &owners, request.clone())).unwrap();
    assert!(matches!(
        ignored.unwrap(),
        Err(MigrationError::Review(StoreError::Invalid))
    ));
    let foreign = Arc::new(Owners::new(Arc::clone(&setup.seed)));
    let (snapshot, denied) = wait(setup.resume_job(snapshot, &foreign, request.clone())).unwrap();
    assert!(matches!(
        denied.unwrap(),
        Err(MigrationError::Review(StoreError::Conflict))
    ));
    assert_eq!(setup.owner.failure(), None);
    setup.retire(snapshot);
    assert_eq!(setup.observe().status, NamespaceStatus::Quiescing);
    assert_eq!(
        setup.observe().history,
        HistoryStatus::ReconciliationRequired
    );
    setup.require_census();
    assert!(finish(&setup.owner).clean);
}

#[test]
fn detached_resume_waiter_preserves_native_file_and_receipt_until_actual_worker_cleanup() {
    let mut setup = Setup::new();
    let (snapshot, owners, request) = completed(&setup);
    let (gates, receiver) = owners.pause_review();
    let weak_original = Arc::downgrade(setup.original());
    let weak_owners = Arc::downgrade(&owners);
    let job = setup.resume_job(snapshot, &owners, request);
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
    assert_eq!(setup.native.snapshot().unwrap().recovery.slots, 1);
    gates.release(ticket).unwrap();
    let retired = wait(drain);
    assert!(retired.clean);
    assert!(retired.snapshot.physically_retired());
    assert!(weak_original.upgrade().is_none());
    assert!(weak_owners.upgrade().is_none());
    assert_eq!(setup.native.snapshot().unwrap().recovery.slots, 0);
    let reopened = setup.restart_retired();
    assert_eq!(reopened.observe().status, NamespaceStatus::Active);
    assert_eq!(reopened.observe().history, HistoryStatus::Ready);
    assert_eq!(reopened.observe().value.len(), 12);
    reopened.require_census();
    assert!(finish(&reopened.owner).clean);
}

#[test]
fn original_resume_deadline_during_native_review_cannot_renew_or_activate() {
    let clock = TestClock::new(1000, Instant::now(), 1);
    let setup = Setup::with_clock(Arc::new(clock.clone()));
    let (snapshot, owners, request) = completed(&setup);
    let original_deadline = setup.original().original_deadline();
    let (gates, receiver) = owners.pause_review();
    let job = setup.resume_job(snapshot, &owners, request);
    let ticket = receiver.recv_timeout(WATCHDOG).unwrap();
    clock.advance(std::time::Duration::from_secs(31));
    assert!(setup.original().with_live(|| ()).is_err());
    assert_eq!(setup.original().original_deadline(), original_deadline);
    gates.release(ticket).unwrap();
    let (snapshot, refused) = wait(job).unwrap();
    assert!(matches!(
        refused.unwrap(),
        Err(MigrationError::Deadline | MigrationError::Review(StoreError::Unavailable))
    ));
    assert_eq!(setup.owner.failure(), None);
    setup.retire(snapshot);
    assert_eq!(setup.observe().status, NamespaceStatus::Quiescing);
    assert_eq!(
        setup.observe().history,
        HistoryStatus::ReconciliationRequired
    );
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
fn corrupt_resume_checkpoint_refuses_healthy_source_but_source_uncertainty_quarantines() {
    let setup = Setup::new();
    let (snapshot, owners, request) = completed(&setup);
    let original = fs::read(setup.checkpoint_path()).unwrap();
    fs::write(setup.checkpoint_path(), &original[..original.len() / 2]).unwrap();
    let (snapshot, corrupt) = wait(setup.resume_job(snapshot, &owners, request.clone())).unwrap();
    assert!(matches!(corrupt.unwrap(), Err(MigrationError::Review(_))));
    assert_eq!(setup.owner.failure(), None);
    fs::write(setup.checkpoint_path(), original).unwrap();
    owners.source_fault.store(true, Ordering::SeqCst);
    let (mut snapshot, uncertain) = wait(setup.resume_job(snapshot, &owners, request)).unwrap();
    assert!(matches!(
        uncertain,
        Err(ProtectedStoreError::Store(StoreError::CommitUncertain))
    ));
    assert_eq!(
        setup.owner.failure(),
        Some(ProtectedStoreError::Store(StoreError::CommitUncertain))
    );
    let witness = snapshot.retirement_witness().unwrap();
    assert!(!witness.has_retired());
    assert_eq!(setup.native.snapshot().unwrap().recovery.slots, 1);
    setup.retire_with_witness(snapshot, &witness);
    assert!(witness.has_retired());
    let report = finish(&setup.owner);
    assert!(!report.clean);
    assert!(report.snapshot.physically_retired());
    // Controlled typed source uncertainty is not device-fault/nonexecution proof.
}
