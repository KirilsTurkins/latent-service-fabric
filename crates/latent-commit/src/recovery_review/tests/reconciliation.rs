//! Selected-engine staged-row schedules. The archive receipt and current
//! permission callbacks are controlled fixtures, not Fresh destination,
//! authenticated Wire, protected checkpoint or remote-provider qualification.
use super::*;
use crate::atomic::{AdmissionDecision, CommandAccess, PreparedAdmission};
use latent_core::TenantId;
use latent_effects::{
    dispatch::{effect_record_version, AttemptIdentity, AttemptReceipt, Disposition, EffectRecord},
    dispatch_store::{
        effect_management::{
            EffectManagementAction, EffectManagementCatalog, EffectManagementEvidence,
            EffectManagementInput, EffectManagementPlan, EffectManagementRequest,
        },
        effect_row_key, DispatchEpoch, EFFECT_PREFIX,
    },
};
use latent_state::{
    embedded::ExpectedRow,
    namespace::history::history_key,
    recovery::{guard_key, snapshot::visit_view},
    tenant,
};

fn workload() -> (Fixture, DispatchEpoch) {
    let fixture = Fixture::new(true);
    for key in [
        "pending-at-backup",
        "old-known-failed",
        "lost-provider-response",
    ] {
        fixture.command(key, None, b"count".to_vec(), false);
    }
    fixture.command("original-rejection", None, b"never-written".to_vec(), true);
    let epoch =
        DispatchCatalog::begin_exclusive_epoch(&fixture.store, fixture::effect_time(102), None)
            .unwrap();
    complete_due(&fixture, epoch, Disposition::Uncertain, 103);
    complete_due(&fixture, epoch, Disposition::KnownFailed, 106);
    (fixture, epoch)
}

fn complete_due(
    fixture: &Fixture,
    epoch: DispatchEpoch,
    disposition: Disposition,
    at: u64,
) -> AttemptIdentity {
    let view = fixture.store.snapshot().unwrap();
    let candidate = DispatchCatalog::due_page(&view, at, None, 1, 16 * 1024)
        .unwrap()
        .rows
        .pop()
        .unwrap();
    drop(view);
    let claim = DispatchCatalog::claim(&fixture.store, epoch, &candidate, fixture::effect_time(at))
        .unwrap();
    if disposition != Disposition::KnownFailed {
        DispatchCatalog::begin_send(
            &fixture.store,
            epoch,
            &claim.attempt,
            fixture::effect_time(at + 1),
        )
        .unwrap();
    }
    DispatchCatalog::complete(
        &fixture.store,
        epoch,
        &claim.attempt,
        AttemptReceipt {
            disposition,
            reason: "original-provider-retired".into(),
            provider_receipt: (disposition == Disposition::ProviderAcknowledged)
                .then(|| "controlled-original-provider-receipt".into()),
            observed_at_millis: at + 2,
        },
        None,
        fixture::effect_time(at + 2),
    )
    .unwrap();
    claim.attempt
}

fn effects(fixture: &Fixture) -> Vec<EffectRecord> {
    fixture
        .store
        .snapshot()
        .unwrap()
        .scan_after(Family::Outbox, EFFECT_PREFIX, None, 16, 1024 * 1024)
        .unwrap()
        .rows
        .into_iter()
        .map(|(_, bytes)| EffectRecord::decode(&bytes).unwrap())
        .collect()
}

fn operator_plan(
    fixture: &Fixture,
    epoch: DispatchEpoch,
    record: &EffectRecord,
    operation: &str,
    at: u64,
) -> EffectManagementPlan {
    let authority = record.authority().unwrap();
    let link = authority.link();
    let scope = authority.scope();
    let view = fixture.store.snapshot().unwrap();
    let bytes = view
        .get(&effect_row_key(&link.effect).unwrap())
        .unwrap()
        .unwrap();
    let request = EffectManagementRequest::new(EffectManagementInput {
        actor_tenant: scope.tenant.clone(),
        actor_subject: "original-operator".into(),
        namespace: scope.namespace.clone(),
        incarnation: scope.incarnation,
        caller_scope: link.caller_scope.clone(),
        command: link.command.clone(),
        command_attempt: link.attempt,
        effect: link.effect.clone(),
        operation_id: operation.into(),
        action: EffectManagementAction::Terminate,
        expected_version: effect_record_version(&bytes).unwrap(),
        expected_policy_digest: "controlled-current-policy".into(),
        original_request_digest: [51; 32],
        reason: "declared-original-unknown-work".into(),
        retry_delay_millis: 0,
    })
    .unwrap();
    let (batch, plan, replayed) = EffectManagementCatalog::prepare_plan(
        &view,
        epoch,
        request,
        fixture::effect_time(at),
        None,
    )
    .unwrap()
    .into_parts();
    assert!(!replayed);
    drop(view);
    fixture.store.apply(batch).unwrap();
    plan
}

fn terminate(fixture: &Fixture, epoch: DispatchEpoch, plan: EffectManagementPlan, at: u64) {
    let view = fixture.store.snapshot().unwrap();
    let (batch, receipt, replayed) = EffectManagementCatalog::prepare_mutation(
        &view,
        epoch,
        plan,
        EffectManagementEvidence::Administrator,
        fixture::effect_time(at),
    )
    .unwrap()
    .into_parts();
    assert!(!replayed);
    assert_eq!(receipt.after(), Disposition::DeadLettered);
    assert!(receipt.provider_receipt().is_none());
    drop(view);
    fixture.store.apply(batch).unwrap();
}

fn replace_history(fixture: &Fixture, tenant: &TenantId, key: RowKey, value: Vec<u8>) {
    let view = fixture.store.snapshot().unwrap();
    let mut batch = AtomicBatch {
        expectations: vec![ExpectedRow {
            value: view.get(&key).unwrap(),
            key: key.clone(),
        }],
        mutations: vec![RowMutation {
            key,
            value: Some(value),
        }],
    };
    tenant::prepare_metadata_update(&view, tenant, &batch)
        .unwrap()
        .append_to(&mut batch)
        .unwrap();
    drop(view);
    fixture.store.apply(batch).unwrap();
}

fn replace_row(fixture: &Fixture, key: RowKey, value: Option<Vec<u8>>) {
    let view = fixture.store.snapshot().unwrap();
    let batch = AtomicBatch {
        expectations: vec![ExpectedRow {
            value: view.get(&key).unwrap(),
            key: key.clone(),
        }],
        mutations: vec![RowMutation { key, value }],
    };
    drop(view);
    fixture.store.apply(batch).unwrap();
}

/// Persist actual paused history with exact tenant charges. This is a same
/// engine controlled staged fixture; it supplies no destination Fresh witness.
fn stage(fixture: &Fixture, metadata: &SnapshotMetadata) -> ReviewedRestoreInput {
    let snapshot = restore::receipt(fixture, metadata);
    let operation = restore::operation(fixture, &snapshot);
    let view = fixture.store.snapshot().unwrap();
    let input = review_restore_input(
        &view,
        &snapshot,
        &operation,
        restore::request(fixture, metadata),
        &mut Owners::new(),
        |_| Ok(()),
        || Ok(()),
    )
    .unwrap();
    drop(view);
    let guard = RecoveryGuard::staging(
        input.operation_digest(),
        input.window().snapshot_digest(),
        input.window().digest().unwrap(),
    )
    .unwrap();
    fixture
        .store
        .apply(guard.prepare_staging().unwrap())
        .unwrap();
    for window in input.window().namespaces() {
        let (record, _) = window.snapshot().decode().unwrap();
        let key = history_key(&record.tenant, &record.id, record.version.incarnation).unwrap();
        replace_history(
            fixture,
            &record.tenant,
            key,
            window.proposed_history().unwrap().encode().unwrap(),
        );
    }
    fixture
        .store
        .apply(guard.prepare_completed().unwrap())
        .unwrap();
    input
}

fn capture(
    fixture: &Fixture,
    view: &ReadView,
    input: &ReviewedRestoreInput,
    metadata: &SnapshotMetadata,
) -> RestoreReconciliationPlan {
    RestoreReconciliationPlan::capture(
        view,
        input,
        restore::request(fixture, metadata),
        &mut Owners::new(),
        || Ok(()),
    )
    .unwrap()
}

#[test]
fn pending_and_old_known_failed_remain_unknown_with_exact_original_attempts_and_no_send() {
    let (fixture, _) = workload();
    fixture.quiesce();
    let metadata = fixture.metadata();
    let input = stage(&fixture, &metadata);
    let view = fixture.store.snapshot().unwrap();
    let before = visit_view(&view, restore::deadline(), |_, _, _| Ok(())).unwrap();
    let plan = capture(&fixture, &view, &input, &metadata);
    let counts = plan.counts();
    assert_eq!(counts.namespaces, 2);
    assert_eq!(counts.nonterminal_effects, 3);
    assert_eq!(counts.pending_without_attempt, 1);
    assert_eq!(counts.known_failed, 1);
    assert_eq!(counts.uncertain, 1);
    assert_eq!(counts.terminal_commands, 4);
    assert_eq!(counts.inbox_rows, 4);
    let page = plan
        .effect_page(&view, None, 128, 1024 * 1024, || Ok(()))
        .unwrap();
    assert_eq!(page.rows().len(), 3);
    for row in page.rows() {
        assert_eq!(row.fact(), RestoreEffectFact::UnknownSinceSnapshot);
        let original =
            DispatchCatalog::last_completed_attempt(&view, &row.authority().link().effect).unwrap();
        assert_eq!(row.original_attempt(), original.as_ref());
        if row.disposition() == Disposition::Pending {
            assert!(row.original_attempt().is_none());
        } else {
            assert!(row.original_attempt().is_some());
        }
    }
    assert!(!serde_json::to_string(&page)
        .unwrap()
        .contains("original effect payload"));
    assert!(matches!(
        plan.require_terminal_review(&view, || Ok(())),
        Err(RecoveryReviewError::Review(StoreError::Conflict))
    ));
    let after = visit_view(&view, restore::deadline(), |_, _, _| Ok(())).unwrap();
    assert_eq!(before.digest, after.digest);
    assert_eq!(plan.rows_digest(), before.digest);
    assert_eq!(
        latent_state::recovery::require_ready(&view),
        Err(StoreError::Unavailable)
    );
}

#[test]
fn original_native_pages_preserve_resume_and_refuse_foreign_view_or_cursor() {
    let (fixture, _) = workload();
    fixture.quiesce();
    let metadata = fixture.metadata();
    let input = stage(&fixture, &metadata);
    let view = fixture.store.snapshot().unwrap();
    let plan = capture(&fixture, &view, &input, &metadata);
    let (first, cursor) = plan
        .effect_page(&view, None, 1, 1024 * 1024, || Ok(()))
        .unwrap()
        .into_parts();
    assert_eq!(first.len(), 1);
    assert!(cursor.is_some());
    let (second, cursor) = plan
        .effect_page(&view, cursor, 1, 1024 * 1024, || Ok(()))
        .unwrap()
        .into_parts();
    assert_eq!(second.len(), 1);
    assert_ne!(
        first[0].authority().link().effect,
        second[0].authority().link().effect
    );
    assert!(cursor.is_some());
    let (third, cursor) = plan
        .effect_page(&view, cursor, 1, 1024 * 1024, || Ok(()))
        .unwrap()
        .into_parts();
    assert_eq!(third.len(), 1);
    assert!(cursor.is_none());
    let (_, original_cursor) = plan
        .effect_page(&view, None, 1, 1024 * 1024, || Ok(()))
        .unwrap()
        .into_parts();
    let foreign = fixture.store.snapshot().unwrap();
    assert!(matches!(
        plan.effect_page(&foreign, None, 1, 1024 * 1024, || Ok(())),
        Err(RecoveryReviewError::Review(StoreError::Conflict))
    ));
    let foreign_plan = capture(&fixture, &foreign, &input, &metadata);
    assert_eq!(plan.digest().unwrap(), foreign_plan.digest().unwrap());
    assert!(matches!(
        foreign_plan.effect_page(&foreign, original_cursor, 1, 1024 * 1024, || Ok(())),
        Err(RecoveryReviewError::Review(StoreError::Conflict))
    ));
    for (rows, bytes) in [(0, 4096), (129, 4096), (1, 0), (1, 1024 * 1024 + 1)] {
        assert!(matches!(
            plan.effect_page(&view, None, rows, bytes, || Ok(())),
            Err(RecoveryReviewError::Review(StoreError::Invalid))
        ));
    }
    assert!(matches!(
        plan.effect_page(&view, None, 1, 1, || Ok(())),
        Err(RecoveryReviewError::Capacity)
    ));
}

#[test]
fn original_guard_window_history_and_runtime_changes_refuse_without_refresh() {
    let (fixture, _) = workload();
    fixture.quiesce();
    let metadata = fixture.metadata();
    let input = stage(&fixture, &metadata);
    let view = fixture.store.snapshot().unwrap();
    let guard = RecoveryGuard::capture(&view).unwrap().unwrap();
    drop(view);
    for (operation, snapshot, window) in [
        (input.operation_digest(), guard.snapshot_digest(), [81; 32]),
        ([82; 32], guard.snapshot_digest(), guard.window_digest()),
        (input.operation_digest(), [83; 32], guard.window_digest()),
    ] {
        let wrong = RecoveryGuard::staging(operation, snapshot, window).unwrap();
        let bytes = wrong
            .prepare_completed()
            .unwrap()
            .mutations
            .pop()
            .unwrap()
            .value
            .unwrap();
        replace_row(&fixture, guard_key(), Some(bytes));
        let view = fixture.store.snapshot().unwrap();
        assert!(matches!(
            RestoreReconciliationPlan::capture(
                &view,
                &input,
                restore::request(&fixture, &metadata),
                &mut Owners::new(),
                || Ok(())
            ),
            Err(RecoveryReviewError::Review(StoreError::Conflict))
        ));
    }
    replace_row(&fixture, guard_key(), Some(guard.encode().unwrap()));
    let window = &input.window().namespaces()[0];
    let (record, _) = window.snapshot().decode().unwrap();
    let key = history_key(&record.tenant, &record.id, record.version.incarnation).unwrap();
    replace_history(
        &fixture,
        &record.tenant,
        key.clone(),
        window.snapshot().history.clone(),
    );
    let view = fixture.store.snapshot().unwrap();
    assert!(matches!(
        RestoreReconciliationPlan::capture(
            &view,
            &input,
            restore::request(&fixture, &metadata),
            &mut Owners::new(),
            || Ok(())
        ),
        Err(RecoveryReviewError::Review(StoreError::Conflict))
    ));
    drop(view);
    replace_history(
        &fixture,
        &record.tenant,
        key,
        window.proposed_history().unwrap().encode().unwrap(),
    );
    let view = fixture.store.snapshot().unwrap();
    let mut replacement = metadata.clone();
    replacement.runtime_digest = [82; 32];
    assert!(matches!(
        RestoreReconciliationPlan::capture(
            &view,
            &input,
            restore::request(&fixture, &replacement),
            &mut Owners::new(),
            || Ok(())
        ),
        Err(RecoveryReviewError::Review(StoreError::Conflict))
    ));
    capture(&fixture, &view, &input, &metadata);
}

#[test]
fn pending_commands_and_expired_unfinished_operator_plans_remain_protective() {
    let (fixture, epoch) = workload();
    let view = fixture.store.snapshot().unwrap();
    let AdmissionDecision::New(pending) = PreparedAdmission::prepare(
        &view,
        fixture::input("original-pending-command", None),
        fixture::time(109),
        |_, _| Ok(()),
    )
    .unwrap() else {
        panic!("expected original pending claim")
    };
    drop(view);
    let pending = pending.publish(&fixture.store, || Ok(())).unwrap();
    assert_eq!(pending.record().outcome(), Outcome::Pending);
    let record = effects(&fixture)
        .into_iter()
        .find(|record| record.disposition() == Disposition::Pending)
        .unwrap();
    let original = operator_plan(
        &fixture,
        epoch,
        &record,
        "lost-original-terminal-response",
        110,
    );
    let expired = fixture::effect_time(original.expires_at_millis() + 1);
    assert!(EffectManagementCatalog::prepare_mutation(
        &fixture.store.snapshot().unwrap(),
        epoch,
        original.clone(),
        EffectManagementEvidence::Administrator,
        expired
    )
    .is_err());
    fixture.quiesce();
    let metadata = fixture.metadata();
    let input = stage(&fixture, &metadata);
    let view = fixture.store.snapshot().unwrap();
    let plan = capture(&fixture, &view, &input, &metadata);
    assert_eq!(plan.counts().pending_commands, 1);
    assert_eq!(plan.counts().unfinished_management_plans, 1);
    assert!(EffectManagementCatalog::lookup(&view, &original)
        .unwrap()
        .is_none());
    let mut unsupported = Owners::new();
    unsupported.formats.remove(&RetainedFormat {
        kind: RetainedKind::EffectEnvelope,
        identity: "latent.effect-management-plan.v1/1".into(),
    });
    assert!(matches!(
        RestoreReconciliationPlan::capture(
            &view,
            &input,
            restore::request(&fixture, &metadata),
            &mut unsupported,
            || Ok(())
        ),
        Err(RecoveryReviewError::Review(StoreError::UnsupportedFormat))
    ));
    assert!(matches!(
        plan.require_terminal_review(&view, || Ok(())),
        Err(RecoveryReviewError::Review(StoreError::Conflict))
    ));
    let expected_key = fixture::input("original-pending-command", None).key;
    let (record, result) =
        atomic::inspect(&view, &expected_key, fixture::time(111), |access, _| {
            assert!(matches!(access, CommandAccess::Replay));
            Ok(())
        })
        .unwrap();
    assert_eq!(record.outcome(), Outcome::Pending);
    assert!(result.is_none());
}

#[test]
fn actual_administrator_disposition_is_separate_from_provider_fact_and_never_resumes() {
    let fixture = Fixture::new(false);
    fixture.command("acknowledged", None, b"count".to_vec(), false);
    fixture.command("administrator", None, b"count".to_vec(), false);
    let epoch =
        DispatchCatalog::begin_exclusive_epoch(&fixture.store, fixture::effect_time(102), None)
            .unwrap();
    complete_due(&fixture, epoch, Disposition::ProviderAcknowledged, 103);
    let record = effects(&fixture)
        .into_iter()
        .find(|record| record.disposition() == Disposition::Pending)
        .unwrap();
    let original = operator_plan(&fixture, epoch, &record, "original-declared-terminal", 106);
    terminate(&fixture, epoch, original, 107);
    fixture.quiesce();
    let metadata = fixture.metadata();
    let input = stage(&fixture, &metadata);
    let view = fixture.store.snapshot().unwrap();
    let plan = capture(&fixture, &view, &input, &metadata);
    assert_eq!(plan.counts().terminal_effects, 2);
    assert_eq!(plan.counts().provider_acknowledged, 1);
    assert_eq!(plan.counts().administrator_terminated, 1);
    assert_eq!(plan.counts().provider_confirmed, 0);
    assert_eq!(plan.counts().nonterminal_effects, 0);
    assert_eq!(plan.counts().unfinished_management_plans, 0);
    plan.require_terminal_review(&view, || Ok(())).unwrap();
    let page = plan
        .effect_page(&view, None, 16, 1024 * 1024, || Ok(()))
        .unwrap();
    assert!(page
        .rows()
        .iter()
        .any(|row| row.fact() == RestoreEffectFact::ProviderAcknowledged));
    let administrator = page
        .rows()
        .iter()
        .find(|row| row.fact() == RestoreEffectFact::AdministratorTerminated)
        .unwrap();
    assert!(administrator.original_attempt().is_none());
    assert_eq!(
        RecoveryGuard::capture(&view).unwrap().unwrap().status(),
        RecoveryStatus::ReconciliationRequired
    );
    assert_eq!(
        latent_state::recovery::require_ready(&view),
        Err(StoreError::Unavailable)
    );
    for window in input.window().namespaces() {
        assert_eq!(
            window.proposed_history().unwrap().status,
            latent_state::namespace::history::HistoryStatus::ReconciliationRequired
        );
    }
}

#[test]
fn original_current_refusal_and_expired_deadline_leave_reviewable_rows_unchanged() {
    let (fixture, _) = workload();
    fixture.quiesce();
    let metadata = fixture.metadata();
    let input = stage(&fixture, &metadata);
    let view = fixture.store.snapshot().unwrap();
    let before = visit_view(&view, restore::deadline(), |_, _, _| Ok(())).unwrap();
    let mut calls = 0;
    assert!(matches!(
        RestoreReconciliationPlan::capture(
            &view,
            &input,
            restore::request(&fixture, &metadata),
            &mut Owners::new(),
            || {
                calls += 1;
                if calls >= 4 {
                    Err(StoreError::Unavailable)
                } else {
                    Ok(())
                }
            }
        ),
        Err(RecoveryReviewError::Review(StoreError::Unavailable))
    ));
    let mut expired = restore::request(&fixture, &metadata);
    expired.deadline = Instant::now();
    let original_deadline = expired.deadline;
    assert!(matches!(
        RestoreReconciliationPlan::capture(&view, &input, expired, &mut Owners::new(), || Ok(())),
        Err(RecoveryReviewError::Deadline)
    ));
    assert_eq!(expired.deadline, original_deadline);
    let plan = capture(&fixture, &view, &input, &metadata);
    assert!(matches!(
        plan.effect_page(&view, None, 1, 1024 * 1024, || Err(StoreError::Unavailable)),
        Err(RecoveryReviewError::Review(StoreError::Unavailable))
    ));
    let after = visit_view(&view, restore::deadline(), |_, _, _| Ok(())).unwrap();
    assert_eq!(before.digest, after.digest);
    fixture.review(&metadata, &mut Owners::new()).unwrap();
}

#[test]
fn missing_payload_and_corrupt_guard_are_not_absent_effects() {
    let (fixture, _) = workload();
    fixture.quiesce();
    let metadata = fixture.metadata();
    let input = stage(&fixture, &metadata);
    let view = fixture.store.snapshot().unwrap();
    let payload = view
        .scan_after(Family::PayloadReference, b"", None, 1, 64 * 1024)
        .unwrap()
        .rows
        .pop()
        .unwrap();
    let original_guard = view.get(&guard_key()).unwrap().unwrap();
    drop(view);
    replace_row(&fixture, payload.0.clone(), None);
    let view = fixture.store.snapshot().unwrap();
    assert!(matches!(
        RestoreReconciliationPlan::capture(
            &view,
            &input,
            restore::request(&fixture, &metadata),
            &mut Owners::new(),
            || Ok(())
        ),
        Err(RecoveryReviewError::Source(StoreError::Corrupt))
    ));
    drop(view);
    replace_row(&fixture, payload.0, Some(payload.1));
    let mut corrupt = original_guard.clone();
    corrupt.truncate(132);
    replace_row(&fixture, guard_key(), Some(corrupt));
    let view = fixture.store.snapshot().unwrap();
    assert!(matches!(
        RestoreReconciliationPlan::capture(
            &view,
            &input,
            restore::request(&fixture, &metadata),
            &mut Owners::new(),
            || Ok(())
        ),
        Err(RecoveryReviewError::Source(StoreError::Corrupt))
    ));
    drop(view);
    replace_row(&fixture, guard_key(), Some(original_guard));
    capture(
        &fixture,
        &fixture.store.snapshot().unwrap(),
        &input,
        &metadata,
    );
}
