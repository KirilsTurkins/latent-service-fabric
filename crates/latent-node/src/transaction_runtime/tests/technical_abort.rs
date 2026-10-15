use super::*;
use latent_activation::ActivationEnvelope;
use latent_capabilities::namespace::{CallerScope, RecoverySelection};
use latent_commit::atomic::CommandRecord;
use latent_core::transaction_contract::CommandKey;
use latent_core::{
    ActivationBudget, ActivationTerminalState, BudgetDimension, ErrorDetail, PlatformError,
    PlatformErrorCode,
};
use latent_executor::transaction::Intent;

struct StagedOriginal {
    host: Arc<dyn TransactionHost>,
    record: CommandRecord,
}

#[tokio::test]
async fn native_staged_trap_publishes_original_abort_proof_and_fault() {
    staged_abort(
        ActivationTerminalState::GuestTrap,
        PlatformErrorCode::GuestTrap,
        "unreachable",
    )
    .await;
}

#[tokio::test]
async fn native_staged_fuel_abort_keeps_original_fault_and_accounting() {
    staged_abort(
        ActivationTerminalState::ResourceExhausted,
        PlatformErrorCode::ResourceExhausted,
        "fuel",
    )
    .await;
}

#[tokio::test]
async fn native_staged_memory_abort_keeps_original_fault_and_accounting() {
    staged_abort(
        ActivationTerminalState::ResourceExhausted,
        PlatformErrorCode::ResourceExhausted,
        "memory",
    )
    .await;
}

#[tokio::test]
async fn native_staged_cancel_fault_keeps_original_fault_and_accounting() {
    staged_abort(
        ActivationTerminalState::Cancelled,
        PlatformErrorCode::Cancelled,
        "cancelled",
    )
    .await;
}

async fn stage_original(
    fixture: &Fixture,
    admission: &Arc<NativeTransactionAdmission>,
    envelope: &ActivationEnvelope,
    budget: &ActivationBudget,
    key: &str,
) -> StagedOriginal {
    let host = admission.admit(envelope, budget).await.unwrap();
    host.acquire(Mode::Command).unwrap();
    let original = host.command_info().unwrap();
    let caller =
        CallerScope::derive(&envelope.principal, &RecoverySelection::OriginalCaller).unwrap();
    let original_record = fixture
        .inspect(CommandKey {
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
    host.put(b"counter".to_vec(), value(b"must not commit"))
        .await
        .unwrap();
    assert_eq!(
        host.stage(Intent {
            binding: "approved-event".into(),
            operation: "event".into(),
            payload: value(b"must not dispatch"),
            expires_at_unix_millis: None,
        })
        .await
        .unwrap(),
        0
    );
    budget
        .reserve(BudgetDimension::CpuFuel, 17)
        .unwrap()
        .commit()
        .unwrap();
    assert_eq!(original.command_id, original_record.id().hex());
    assert_eq!(original.attempt_id, original_record.attempt().to_string());
    StagedOriginal {
        host,
        record: original_record,
    }
}

fn original_failure(
    budget: &ActivationBudget,
    terminal_state: ActivationTerminalState,
    code: PlatformErrorCode,
    reason: &str,
) -> ActivationOutcome {
    let finalized = budget.finalize_at(None, std::time::Instant::now());
    let consumption = finalized.consumption().clone();
    assert_eq!(consumption.effect_count, 1);
    assert!(consumption.state_write_bytes > 16_384);
    ActivationOutcome::Failed {
        terminal_state,
        error: PlatformError {
            code,
            message: "original staged fault".into(),
            retryable: false,
            details: vec![ErrorDetail {
                kind: "original-execution-fault".into(),
                fields: Metadata::from([("reason".into(), reason.into())]),
            }],
        },
        consumption,
    }
}

async fn staged_abort(
    terminal_state: ActivationTerminalState,
    code: PlatformErrorCode,
    reason: &str,
) {
    let fixture = Fixture::with_staging().await;
    let (admission, envelope, budget) = fixture.invocation(false, "staged-original-fault");
    let original = stage_original(
        &fixture,
        &admission,
        &envelope,
        &budget,
        "staged-original-fault",
    )
    .await;
    original.host.finish_guest_access();
    let failure = original_failure(&budget, terminal_state, code, reason);
    let observed = admission
        .complete(failure.clone(), fixture.commit_control(&envelope, &budget))
        .await;
    let response = admission.take_owned_completion().unwrap().unwrap();
    let TransactionCompletionResult::Command(CommandCompletionDisposition::Durable {
        command,
        result,
        cleanup_failure,
        ..
    }) = &response.result
    else {
        panic!("physically retired staged trap lacks its durable abort");
    };
    assert_eq!(command.outcome(), Outcome::Aborted);
    assert_eq!(command.id(), original.record.id());
    assert_eq!(command.attempt(), original.record.attempt());
    assert!(command.abort_proof().is_some());
    assert_eq!(command.transaction_id(), original.record.transaction_id());
    assert_eq!(command.key(), original.record.key());
    assert_eq!(command.source(), original.record.source());
    assert_eq!(result.code(), Some(code.wire_code()));
    assert!(result.value().unwrap().bytes.is_empty());
    assert!(cleanup_failure.is_none());
    assert_eq!(observed, failure);
    assert_eq!(fixture.rows(Family::State).await, 0);
    assert_eq!(fixture.rows(Family::Outbox).await, 0);
    response.authority.with_current(&mut || {}).unwrap();
    let (stored, retained) = fixture.inspect(command.key().clone()).await;
    assert_eq!(&stored, command);
    assert_eq!(retained.unwrap(), **result);
    drop((response, original, admission));
    assert!(fixture.native.snapshot().unwrap().physically_retired());
    fixture.shutdown().await;
}

#[tokio::test]
async fn staged_failure_without_guest_retirement_cannot_issue_abort_proof() {
    let fixture = Fixture::with_staging().await;
    let (admission, envelope, budget) = fixture.invocation(false, "live-original");
    let original = stage_original(&fixture, &admission, &envelope, &budget, "live-original").await;
    let TransactionAdmissionResult::Command { claim, host } =
        admission.take_result().unwrap().unwrap()
    else {
        panic!("original command host absent");
    };
    let retirement = claim.retirement();
    let failure = original_failure(
        &budget,
        ActivationTerminalState::GuestTrap,
        PlatformErrorCode::GuestTrap,
        "unreachable",
    );
    let result = CommandCompletion::new(
        claim,
        host.clone(),
        fixture.effects.clone(),
        fixture.time.clone(),
        fixture.commit_control(&envelope, &budget),
    )
    .unwrap()
    .finish(failure)
    .await;
    assert!(matches!(
        &result,
        CommandCompletionDisposition::RecoveryRequired {
            cleanup_failure: Some(StateFailure::HandleClosed),
            ..
        }
    ));
    assert!(retirement.proven_noncommit().is_err());
    let (stored, retained) = fixture.inspect(original.record.key().clone()).await;
    assert_eq!(stored.outcome(), Outcome::Pending);
    assert!(stored.abort_proof().is_none());
    assert!(retained.is_none());
    assert_eq!(fixture.rows(Family::State).await, 0);
    assert_eq!(fixture.rows(Family::Outbox).await, 0);
    host.finish_guest_access();
    host.retire().await.unwrap();
    host.retire_command_role().unwrap();
    drop((result, host, original, admission));
    assert!(fixture.native.snapshot().unwrap().physically_retired());
    fixture.shutdown().await;
}

#[tokio::test]
async fn fresh_abort_policy_denial_keeps_original_pending_and_no_business_rows() {
    denied_abort(false).await;
}

#[tokio::test]
async fn cancelled_original_authority_cannot_publish_an_abort() {
    denied_abort(true).await;
}

async fn denied_abort(cancel: bool) {
    let fixture = Fixture::with_staging().await;
    let (admission, envelope, budget) = fixture.invocation(false, "denied-original");
    let original =
        stage_original(&fixture, &admission, &envelope, &budget, "denied-original").await;
    let reserved_results = fixture.rows(Family::Result).await;
    original.host.finish_guest_access();
    if cancel {
        fixture.cancel_original(&envelope);
    } else {
        fixture.revoke();
    }
    let failure = original_failure(
        &budget,
        ActivationTerminalState::GuestTrap,
        PlatformErrorCode::GuestTrap,
        "unreachable",
    );
    let observed = admission
        .complete(failure, fixture.commit_control(&envelope, &budget))
        .await;
    assert!(matches!(observed, ActivationOutcome::Failed { .. }));
    let result = admission.take_completion().unwrap().unwrap();
    let TransactionCompletionResult::Command(CommandCompletionDisposition::RecoveryRequired {
        command,
        ..
    }) = &result
    else {
        panic!("fresh abort denial must remain recovery-required");
    };
    assert_eq!(command.id(), original.record.id());
    assert_eq!(command.attempt(), original.record.attempt());
    assert_eq!(command, &original.record);
    assert_eq!(command.outcome(), Outcome::Pending);
    assert!(command.abort_proof().is_none());
    assert_eq!(fixture.rows(Family::State).await, 0);
    assert_eq!(fixture.rows(Family::Outbox).await, 0);
    assert_eq!(fixture.rows(Family::Result).await, reserved_results);
    drop((result, original, admission));
    assert!(fixture.native.snapshot().unwrap().physically_retired());
    fixture.shutdown().await;
}
