use super::*;
use crate::journal::{JournalOwner, LocalActivationJournal, LocalActivationJournalConfig};
use latent_activation::ActivationEnvelope;
use latent_capabilities::namespace::{CallerScope, RecoverySelection};
use latent_commit::atomic::CommandRecord;
use latent_core::{
    ActivationBudget, ActivationPhase, ActivationTerminalState, PlatformError, PlatformErrorCode,
    SystemActivationClock,
};
use latent_executor::transaction::{Intent, TransactionHost};
use std::{sync::atomic::Ordering, time::Instant};

struct Original {
    admission: Arc<NativeTransactionAdmission>,
    envelope: ActivationEnvelope,
    budget: ActivationBudget,
    journal: LocalActivationJournal,
    _owner: JournalOwner,
    host: Arc<dyn TransactionHost>,
    native: Arc<StateTransactionHost>,
    record: CommandRecord,
}
async fn original(f: &Fixture, key: &str, grants: bool, slot_free: bool) -> Original {
    let (admission, envelope, budget) = if grants {
        f.invocation_with_external_grants(key, 1, 1)
    } else {
        f.invocation(false, key)
    };
    let host = admission.admit(&envelope, &budget).await.unwrap();
    let association = admission.original_command_cancellation().unwrap().unwrap();
    let native = admission.original_host_for_native_test();
    let association = if slot_free {
        association.without_abort_slot_for_test()
    } else {
        association
    };
    let journal = LocalActivationJournal::new(
        LocalActivationJournalConfig::default(),
        Arc::new(SystemActivationClock),
    )
    .unwrap();
    let mut owner = journal.begin(&envelope).unwrap();
    owner
        .advance(ActivationPhase::Resolved, Metadata::new())
        .unwrap();
    owner
        .advance(ActivationPhase::Admitted, Metadata::new())
        .unwrap();
    owner.record_grant(&budget);
    owner
        .bind_original_command_cancellation(association, f.original_cancellation_owner(&envelope))
        .unwrap();
    host.acquire(Mode::Command).unwrap();
    let caller =
        CallerScope::derive(&envelope.principal, &RecoverySelection::OriginalCaller).unwrap();
    let record = f
        .inspect(latent_core::transaction_contract::CommandKey {
            tenant: "a".into(),
            namespace: "orders".into(),
            incarnation: "1".into(),
            recovery_scope: caller.scope,
            operation: "update".into(),
            entity: None,
            client_key: key.into(),
        })
        .await
        .0;
    host.put(b"counter".to_vec(), value(b"discard actual staging"))
        .await
        .unwrap();
    host.stage(Intent {
        binding: "approved-event".into(),
        operation: "event".into(),
        payload: value(b"discard actual intent"),
        expires_at_unix_millis: None,
    })
    .await
    .unwrap();
    Original {
        admission,
        envelope,
        budget,
        journal,
        _owner: owner,
        host,
        native,
        record,
    }
}
fn failure(original: &Original) -> ActivationOutcome {
    let consumption = original
        .budget
        .finalize_at(None, Instant::now())
        .consumption()
        .clone();
    assert_eq!(consumption.effect_count, 1);
    assert!(consumption.state_write_bytes > 16384);
    ActivationOutcome::Failed {
        terminal_state: ActivationTerminalState::Cancelled,
        error: PlatformError {
            code: PlatformErrorCode::Cancelled,
            message: "actual original cancel".into(),
            retryable: false,
            details: vec![],
        },
        consumption,
    }
}
async fn authorize(f: &Fixture, o: &Original) -> Arc<fixture::CancellationAuthority> {
    f.cancellation_authority(
        &o.envelope,
        &o.record,
        "cancel-command",
        o.budget.deadline().monotonic().unwrap(),
    )
    .await
}
fn request(
    f: &Fixture,
    o: &Original,
    a: Arc<fixture::CancellationAuthority>,
) -> Result<OriginalCommandCancelDisposition, PlatformError> {
    o.journal.cancel_original_command_authorized(
        &o.envelope.target.tenant,
        &o.record,
        f.protected_store(),
        "first current management request",
        a,
        || Ok(()),
    )
}
async fn complete(f: &Fixture, o: &Original, closed: bool) -> TransactionCompletionResult {
    if closed {
        o.host.finish_guest_access();
    }
    let observed = o
        .admission
        .complete(failure(o), f.commit_control(&o.envelope, &o.budget))
        .await;
    assert!(matches!(observed, ActivationOutcome::Failed { .. }));
    o.admission.take_completion().unwrap().unwrap()
}
fn unknown(result: &TransactionCompletionResult, original: &CommandRecord) {
    let TransactionCompletionResult::Command(CommandCompletionDisposition::RecoveryRequired {
        command,
        ..
    }) = result
    else {
        panic!("unqualified cancel must remain recovery-required");
    };
    assert_eq!(command, original);
    assert_eq!(command.outcome(), Outcome::Pending);
    assert!(command.abort_proof().is_none());
}
async fn unchanged(f: &Fixture, o: &Original) {
    let (stored, result) = f.inspect(o.record.key().clone()).await;
    assert_eq!(stored, o.record);
    assert!(result.is_none() && stored.abort_proof().is_none());
    assert_eq!(f.rows(Family::State).await, 0);
    assert_eq!(f.rows(Family::Outbox).await, 0);
}

#[tokio::test]
async fn actual_authorized_cancel_retirement_publishes_only_original_metadata_abort() {
    let f = Fixture::with_staging().await;
    let o = original(&f, "managed-abort", false, false).await;
    let authority = authorize(&f, &o).await;
    assert_eq!(
        request(&f, &o, authority.clone()).unwrap(),
        OriginalCommandCancelDisposition::Requested
    );
    assert!(o.budget.retained_authority_is_cancelled_at(Instant::now()));
    o.host.finish_guest_access();
    let expected = failure(&o);
    let observed = o
        .admission
        .complete(expected.clone(), f.commit_control(&o.envelope, &o.budget))
        .await;
    assert_eq!(observed, expected);
    let response = o.admission.take_owned_completion().unwrap().unwrap();
    let TransactionCompletionResult::Command(CommandCompletionDisposition::Durable {
        command,
        result,
        cleanup_failure,
        ..
    }) = &response.result
    else {
        panic!("original authorized cancellation lacks durable abort");
    };
    assert_eq!(command.id(), o.record.id());
    assert_eq!(command.attempt(), o.record.attempt());
    assert_eq!(command.transaction_id(), o.record.transaction_id());
    assert_eq!(command.key(), o.record.key());
    assert_eq!(command.source(), o.record.source());
    assert_eq!(command.outcome(), Outcome::Aborted);
    assert!(command.abort_proof().is_some());
    assert_eq!(result.code(), Some("cancelled"));
    assert!(result.value().unwrap().bytes.is_empty());
    assert!(cleanup_failure.is_none());
    response.authority.with_current(&mut || {}).unwrap();
    authority.refused.store(true, Ordering::SeqCst);
    assert!(response.authority.with_current(&mut || {}).is_err());
    assert_eq!(f.rows(Family::State).await, 0);
    assert_eq!(f.rows(Family::Outbox).await, 0);
    drop((response, authority, o));
    f.shutdown().await;
}

#[tokio::test]
async fn actual_cancel_request_without_original_guest_retirement_cannot_publish_abort() {
    let f = Fixture::with_staging().await;
    let o = original(&f, "no-retirement", false, false).await;
    assert_eq!(
        request(&f, &o, authorize(&f, &o).await).unwrap(),
        OriginalCommandCancelDisposition::Requested
    );
    let result = complete(&f, &o, false).await;
    unknown(&result, &o.record);
    unchanged(&f, &o).await;
    o.host.finish_guest_access();
    o.native.retire().await.unwrap();
    o.native.retire_command_role().unwrap();
    drop((result, o));
    f.shutdown().await;
}

#[tokio::test]
async fn actual_generic_cancellation_cannot_be_upgraded_by_later_management_request() {
    let f = Fixture::with_staging().await;
    let o = original(&f, "generic-first", false, false).await;
    f.cancel_original(&o.envelope);
    assert_eq!(
        request(&f, &o, authorize(&f, &o).await).unwrap(),
        OriginalCommandCancelDisposition::Requested
    );
    let result = complete(&f, &o, true).await;
    unknown(&result, &o.record);
    unchanged(&f, &o).await;
    drop((result, o));
    f.shutdown().await;
}

#[tokio::test]
async fn actual_repeated_request_cannot_replace_first_metadata_authority() {
    let f = Fixture::with_staging().await;
    let o = original(&f, "first-owner", false, false).await;
    let first = authorize(&f, &o).await;
    assert_eq!(
        request(&f, &o, first.clone()).unwrap(),
        OriginalCommandCancelDisposition::Requested
    );
    let later = authorize(&f, &o).await;
    assert_eq!(
        request(&f, &o, later.clone()).unwrap(),
        OriginalCommandCancelDisposition::Requested
    );
    first.refused.store(true, Ordering::SeqCst);
    let result = complete(&f, &o, true).await;
    unknown(&result, &o.record);
    unchanged(&f, &o).await;
    drop((first, later, result, o));
    f.shutdown().await;
}

#[tokio::test]
async fn actual_current_cancel_purpose_revocation_preserves_original_pending() {
    let f = Fixture::with_staging().await;
    let o = original(&f, "revoked-owner", false, false).await;
    assert_eq!(
        request(&f, &o, authorize(&f, &o).await).unwrap(),
        OriginalCommandCancelDisposition::Requested
    );
    f.revoke();
    let result = complete(&f, &o, true).await;
    unknown(&result, &o.record);
    assert_eq!(f.rows(Family::State).await, 0);
    assert_eq!(f.rows(Family::Outbox).await, 0);
    drop((result, o));
    f.shutdown().await;
}

#[tokio::test]
async fn original_nonzero_external_grant_and_slot_free_cancellation_keep_ordinary_semantics() {
    for (key, grants, slot_free) in [("nonzero-grants", true, false), ("slot-free", false, true)] {
        let f = Fixture::with_staging().await;
        let o = original(&f, key, grants, slot_free).await;
        if grants {
            assert_eq!(o.budget.granted().child_calls, 1);
            assert_eq!(o.budget.granted().outbound_requests, 1);
        }
        assert_eq!(
            request(&f, &o, authorize(&f, &o).await).unwrap(),
            OriginalCommandCancelDisposition::Requested
        );
        let result = complete(&f, &o, true).await;
        unknown(&result, &o.record);
        unchanged(&f, &o).await;
        drop((result, o));
        f.shutdown().await;
    }
}

#[tokio::test]
async fn actual_read_purpose_cannot_construct_cancel_metadata_or_request_original_owner() {
    let f = Fixture::with_staging().await;
    let o = original(&f, "wrong-purpose", false, false).await;
    let read = f
        .cancellation_authority(
            &o.envelope,
            &o.record,
            "read-result",
            o.budget.deadline().monotonic().unwrap(),
        )
        .await;
    assert_eq!(
        request(&f, &o, read).unwrap_err().code,
        PlatformErrorCode::PermissionDenied
    );
    assert!(!o.budget.retained_authority_is_cancelled_at(Instant::now()));
    unchanged(&f, &o).await;
    o.host.finish_guest_access();
    o.native.retire().await.unwrap();
    drop(o.admission.take_result().unwrap());
    o.native.retire_command_role().unwrap();
    drop(o);
    f.shutdown().await;
}

async fn original_proof(
    f: &Fixture,
    o: &Original,
    control: crate::TransactionCommitControl,
) -> Box<latent_commit::atomic::RetiredAttempt> {
    let TransactionAdmissionResult::Command { claim, host } =
        o.admission.take_result().unwrap().unwrap()
    else {
        panic!("real original claim absent");
    };
    o.host.finish_guest_access();
    let disposition =
        CommandCompletion::new(claim, host, f.effects.clone(), f.time.clone(), control)
            .unwrap()
            .finish(failure(o))
            .await;
    let CommandCompletionDisposition::Retired { proof, .. } = disposition else {
        panic!("actual affine original retirement absent");
    };
    proof
}

#[tokio::test]
async fn actual_transport_stop_after_original_candidate_take_denies_promotion() {
    let f = Fixture::with_staging().await;
    let o = original(&f, "late-original-transport", false, false).await;
    assert_eq!(
        request(&f, &o, authorize(&f, &o).await).unwrap(),
        OriginalCommandCancelDisposition::Requested
    );
    let control = f.commit_control(&o.envelope, &o.budget);
    let candidate = o
        .admission
        .take_cancel_candidate_for_native_test(&o.record, &o.native, &control);
    control.stop_transport_for_native_test();
    let proof = original_proof(&f, &o, control).await;
    let original = o.record.clone();
    let time = f.time.sample();
    let promoted = f
        .protected_store()
        .with_store(
            latent_state::store_io::StoreIoKind::Read,
            262_144,
            move |store| {
                let view = store.snapshot()?;
                let envelope = latent_commit::atomic::CompleteEnvelope::technical_abort(
                    &view,
                    *proof,
                    "cancelled".into(),
                    time,
                )
                .unwrap();
                Ok(candidate.promote(&original, envelope.command()).map(|_| ()))
            },
        )
        .unwrap()
        .await
        .unwrap()
        .unwrap();
    assert_eq!(
        promoted.unwrap_err().code,
        PlatformErrorCode::PermissionDenied
    );
    unchanged(&f, &o).await;
    drop(o);
    f.shutdown().await;
}

#[tokio::test]
async fn actual_transport_stop_after_promotion_denies_final_native_publication() {
    let f = Fixture::with_staging().await;
    let o = original(&f, "late-final-transport", false, false).await;
    assert_eq!(
        request(&f, &o, authorize(&f, &o).await).unwrap(),
        OriginalCommandCancelDisposition::Requested
    );
    let control = f.commit_control(&o.envelope, &o.budget);
    let candidate = o
        .admission
        .take_cancel_candidate_for_native_test(&o.record, &o.native, &control);
    let proof = original_proof(&f, &o, control.clone()).await;
    let original = o.record.clone();
    let time = f.time.sample();
    let permit = f
        .protected_store()
        .with_store(
            latent_state::store_io::StoreIoKind::Read,
            262_144,
            move |store| {
                let view = store.snapshot()?;
                let envelope = latent_commit::atomic::CompleteEnvelope::technical_abort(
                    &view,
                    *proof,
                    "cancelled".into(),
                    time,
                )
                .unwrap();
                Ok(candidate.promote(&original, envelope.command()).unwrap())
            },
        )
        .unwrap()
        .await
        .unwrap()
        .unwrap();
    let mut published = false;
    let retention = o.native.authorization.retention.as_ref().unwrap();
    permit
        .with_native_pair(retention.native(), &mut || published = true)
        .unwrap();
    assert!(published);
    control.stop_transport_for_native_test();
    published = false;
    assert_eq!(
        permit
            .with_native_pair(retention.native(), &mut || published = true)
            .unwrap_err()
            .code,
        PlatformErrorCode::PermissionDenied
    );
    assert!(!published);
    unchanged(&f, &o).await;
    drop((permit, control, o));
    f.shutdown().await;
}

#[tokio::test]
async fn actual_original_transport_stop_after_durable_abort_refuses_receipt_release() {
    let f = Fixture::with_staging().await;
    let o = original(&f, "late-response-transport", false, false).await;
    assert_eq!(
        request(&f, &o, authorize(&f, &o).await).unwrap(),
        OriginalCommandCancelDisposition::Requested
    );
    let control = f.commit_control(&o.envelope, &o.budget);
    o.host.finish_guest_access();
    o.admission.complete(failure(&o), control.clone()).await;
    let response = o.admission.take_owned_completion().unwrap().unwrap();
    let TransactionCompletionResult::Command(CommandCompletionDisposition::Durable {
        command, ..
    }) = &response.result
    else {
        panic!("durable actual abort absent");
    };
    assert_eq!(command.outcome(), Outcome::Aborted);
    assert!(command.abort_proof().is_some());
    response.authority.with_current(&mut || {}).unwrap();
    control.stop_transport_for_native_test();
    let mut published = false;
    assert_eq!(
        response
            .authority
            .with_current(&mut || published = true)
            .unwrap_err()
            .code,
        PlatformErrorCode::PermissionDenied
    );
    assert!(!published);
    let (stored, result) = f.inspect(o.record.key().clone()).await;
    assert_eq!(&stored, command);
    assert!(result.is_some());
    assert_eq!(f.rows(Family::State).await, 0);
    assert_eq!(f.rows(Family::Outbox).await, 0);
    drop((response, control, o));
    f.shutdown().await;
}

#[tokio::test]
async fn actual_original_identity_expiry_cannot_publish_cancel_metadata() {
    let f = Fixture::with_staging().await;
    let o = original(&f, "expired-original", false, false).await;
    assert_eq!(
        request(&f, &o, authorize(&f, &o).await).unwrap(),
        OriginalCommandCancelDisposition::Requested
    );
    f.set_result_time(o.record.identity_expires(), true);
    let result = complete(&f, &o, true).await;
    unknown(&result, &o.record);
    assert_eq!(f.rows(Family::State).await, 0);
    assert_eq!(f.rows(Family::Outbox).await, 0);
    drop((result, o));
    f.shutdown().await;
}
