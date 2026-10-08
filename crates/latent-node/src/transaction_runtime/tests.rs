//! Real protected-engine/policy tests through the current affine command/query hooks.
//! These native host tests do not execute an authored guest; that campaign stays separate.
mod capacity;
mod fixture;
mod history;
use super::*;
use fixture::*;
use latent_activation::{ActivationOutcome, ActivationSuccess};
use latent_commit::atomic::Outcome;
use latent_core::{BudgetConsumption, DeclaredError, Metadata};
use latent_executor::transaction::{Mode, StateFailure};
use latent_state::embedded::Family;

#[tokio::test]
async fn native_admission_persists_pending_before_host_and_success_commits_once() {
    let fixture = Fixture::new().await;
    let (admission, envelope, budget) = fixture.invocation(false, "one");
    let execution = execute(admission.admit(&envelope, &budget).await.unwrap());
    let host = execution.host.clone();
    assert!(host.budget().is_same_instance(&budget));
    assert_eq!(fixture.rows(Family::Command).await, 1);
    let key = command_key("one");
    assert_eq!(
        fixture.inspect(key.clone()).await.0.outcome(),
        Outcome::Pending
    );
    host.acquire(Mode::Command).unwrap();
    assert!(host.read(b"counter".to_vec()).await.unwrap().is_none());
    host.put(b"counter".to_vec(), value(b"one")).await.unwrap();
    let (duplicate, request, allowance) = fixture.invocation(false, "one");
    let duplicate_result = duplicate.admit(&request, &allowance);
    tokio::pin!(duplicate_result);
    assert!(
        tokio::time::timeout(std::time::Duration::from_millis(30), &mut duplicate_result)
            .await
            .is_err()
    );
    assert_eq!(fixture.rows(Family::Command).await, 1);
    assert_eq!(fixture.rows(Family::State).await, 0);
    host.finish_guest_access();
    let _ = budget.finalize_at(None, std::time::Instant::now());
    assert!(budget.reserve_host_memory(1).is_err());
    let completion = execution.completion.complete(success(b"result")).await;
    let command = completion
        .durable_command()
        .unwrap_or_else(|| panic!("{completion:?}"))
        .clone();
    assert_eq!(command.outcome(), Outcome::Committed);
    assert!(completion.delivery_failure().is_none());
    let (record, body) = fixture.inspect(key).await;
    assert_eq!(record, command);
    assert_eq!(body.unwrap().value().unwrap().bytes, b"result");
    assert_eq!(fixture.rows(Family::State).await, 1);
    let duplicate_result =
        tokio::time::timeout(std::time::Duration::from_secs(2), &mut duplicate_result)
            .await
            .unwrap()
            .unwrap();
    let crate::TransactionAdmission::Existing(replayed) = duplicate_result else {
        panic!("duplicate obtained another host")
    };
    assert_eq!(replayed.durable_command(), Some(&command));
    assert!(replayed.disposition().unwrap().recovered_result());
    assert_eq!(fixture.rows(Family::Command).await, 1);
    drop((replayed, completion, execution, host, admission));
    fixture.shutdown().await;
}

#[tokio::test]
async fn native_declared_rejection_discards_state_and_preserves_exact_result() {
    let fixture = Fixture::new().await;
    let (admission, envelope, budget) = fixture.invocation(false, "rejected");
    let execution = execute(admission.admit(&envelope, &budget).await.unwrap());
    execution.host.acquire(Mode::Command).unwrap();
    execution
        .host
        .put(b"counter".to_vec(), value(b"discarded"))
        .await
        .unwrap();
    execution.host.finish_guest_access();
    let _ = budget.finalize_at(None, std::time::Instant::now());
    let completion = execution
        .completion
        .complete(ActivationOutcome::DeclaredError {
            error: DeclaredError {
                code: "rejected".into(),
                message: "business rejection".into(),
                payload: b"reason".to_vec(),
                media_type: "application/octet-stream".into(),
                metadata: Metadata::new(),
            },
            consumption: BudgetConsumption::default(),
        })
        .await;
    assert_eq!(
        completion
            .durable_command()
            .unwrap_or_else(|| panic!("{completion:?}"))
            .outcome(),
        Outcome::Rejected
    );
    assert!(completion.delivery_failure().is_none());
    let (record, body) = fixture.inspect(command_key("rejected")).await;
    assert_eq!(
        &record,
        completion
            .durable_command()
            .unwrap_or_else(|| panic!("{completion:?}"))
    );
    assert_eq!(body.unwrap().value().unwrap().bytes, b"reason");
    assert_eq!(fixture.rows(Family::State).await, 0);
    assert_eq!(fixture.rows(Family::Outbox).await, 0);
    drop((completion, execution, admission));
    fixture.shutdown().await;
}

#[tokio::test]
async fn native_fresh_query_is_read_only_and_creates_no_command_journal() {
    let fixture = Fixture::new().await;
    let (admission, envelope, budget) = fixture.invocation(true, "query");
    let execution = execute(admission.admit(&envelope, &budget).await.unwrap());
    execution.host.acquire(Mode::Query).unwrap();
    assert!(execution
        .host
        .read(b"missing".to_vec())
        .await
        .unwrap()
        .is_none());
    assert_eq!(
        execution
            .host
            .put(b"counter".to_vec(), value(b"denied"))
            .await,
        Err(StateFailure::WrongMode)
    );
    assert_eq!(
        execution.host.view_identity().unwrap().version.len(),
        latent_state::session::version::VIEW_TOKEN_BYTES
    );
    assert_eq!(
        execution.native_host.as_ref().unwrap().retire().await,
        Err(StateFailure::HandleClosed)
    );
    assert_eq!(fixture.native.snapshot().unwrap().ordinary.slots, 1);
    execution.host.finish_guest_access();
    execution
        .native_host
        .as_ref()
        .unwrap()
        .retire()
        .await
        .unwrap();
    execution
        .native_host
        .as_ref()
        .unwrap()
        .retire()
        .await
        .unwrap();
    let completed = execution.completion.complete(success(b"query")).await;
    assert!(
        matches!(completed.outcome(), ActivationOutcome::Succeeded(_)),
        "{completed:?}"
    );
    assert!(completed.delivery_fence().is_some());
    for family in [
        Family::Command,
        Family::Attempt,
        Family::Result,
        Family::Outbox,
    ] {
        assert_eq!(fixture.rows(family).await, 0);
    }
    drop((completed, execution, admission));
    assert!(fixture.native.snapshot().unwrap().physically_retired());
    fixture.shutdown().await;
}

#[tokio::test]
async fn native_policy_revocation_denies_access_without_false_physical_retirement() {
    let fixture = Fixture::new().await;
    let (admission, envelope, budget) = fixture.invocation(false, "revoked");
    let execution = execute(admission.admit(&envelope, &budget).await.unwrap());
    execution.host.acquire(Mode::Command).unwrap();
    let retirement = execution.retirement.clone().unwrap();
    fixture.revoke();
    assert_eq!(
        execution.host.read(b"counter".to_vec()).await,
        Err(StateFailure::PermissionDenied)
    );
    assert!(retirement.proven_noncommit().is_err());
    assert_eq!(
        execution.native_host.as_ref().unwrap().retire().await,
        Err(StateFailure::HandleClosed)
    );
    assert!(retirement.proven_noncommit().is_err());
    execution.host.finish_guest_access();
    execution
        .native_host
        .as_ref()
        .unwrap()
        .retire()
        .await
        .unwrap();
    let retired = execution.completion.complete(success(b"denied")).await;
    drop((retired, execution, admission));
    assert!(retirement.proven_noncommit().is_ok());
    assert_eq!(fixture.rows(Family::State).await, 0);
    assert!(fixture.native.snapshot().unwrap().physically_retired());
    fixture.shutdown().await;
}

#[tokio::test]
async fn native_incompatible_selected_source_rejects_before_durable_admission() {
    let fixture = Fixture::new().await;
    let (admission, mut envelope, budget) = fixture.invocation(false, "bad-source");
    envelope.resolved_revision.as_mut().unwrap().release.0 = format!("sha256:{}", "f".repeat(64));
    assert!(admission.admit(&envelope, &budget).await.is_err());
    assert_eq!(fixture.rows(Family::Command).await, 0);
    assert_eq!(fixture.rows(Family::Result).await, 0);
    drop(admission);
    assert!(fixture.native.snapshot().unwrap().physically_retired());
    fixture.shutdown().await;
}

fn success(bytes: &[u8]) -> ActivationOutcome {
    ActivationOutcome::Succeeded(ActivationSuccess {
        output: bytes.to_vec(),
        output_media_type: "application/octet-stream".into(),
        consumption: BudgetConsumption::default(),
        committed_state_version: None,
        effect_ids: Vec::new(),
        metadata: Metadata::new(),
    })
}

#[tokio::test]
async fn native_original_cancellation_before_commit_preserves_pending_without_business_rows() {
    let fixture = Fixture::new().await;
    let (admission, envelope, budget) = fixture.invocation(false, "cancel-before-commit");
    let execution = execute(admission.admit(&envelope, &budget).await.unwrap());
    execution.host.acquire(Mode::Command).unwrap();
    execution
        .host
        .put(b"counter".to_vec(), value(b"never committed"))
        .await
        .unwrap();
    execution.host.finish_guest_access();
    let _ = budget.finalize_at(None, std::time::Instant::now());
    fixture.cancel_original(&envelope);
    let completed = execution.completion.complete(success(b"discarded")).await;
    assert!(matches!(
        completed.outcome(),
        ActivationOutcome::Failed { .. }
    ));
    assert!(completed.durable_command().is_none());
    let (command, body) = fixture.inspect(command_key("cancel-before-commit")).await;
    assert_eq!(command.outcome(), Outcome::Pending);
    assert!(body.is_none());
    assert_eq!(fixture.rows(Family::State).await, 0);
    assert_eq!(fixture.rows(Family::Outbox).await, 0);
    drop((completed, execution, admission));
    fixture.shutdown().await;
}

#[tokio::test]
async fn native_manager_completion_hook_commits_once_and_retains_affine_result() {
    let fixture = Fixture::new().await;
    let (admission, envelope, budget) = fixture.invocation(false, "original-hook");
    let execution = execute(admission.admit(&envelope, &budget).await.unwrap());
    execution.host.acquire(Mode::Command).unwrap();
    execution
        .host
        .put(b"counter".to_vec(), value(b"hook committed"))
        .await
        .unwrap();
    execution.host.finish_guest_access();
    let _ = budget.finalize_at(None, std::time::Instant::now());
    let completion = execution
        .completion
        .complete(success(b"owned result"))
        .await;
    assert!(
        matches!(completion.outcome(), ActivationOutcome::Succeeded(_)),
        "{completion:?}"
    );
    assert_eq!(
        completion
            .durable_command()
            .unwrap_or_else(|| panic!("{completion:?}"))
            .outcome(),
        Outcome::Committed
    );
    assert!(completion.delivery_failure().is_none());
    assert!(completion.delivery_fence().is_some());
    assert_eq!(
        fixture
            .inspect(command_key("original-hook"))
            .await
            .1
            .unwrap()
            .value()
            .unwrap()
            .bytes,
        b"owned result"
    );
    let repeated = execution
        .completion
        .complete(success(b"must not replace"))
        .await;
    assert!(matches!(
        repeated.outcome(),
        ActivationOutcome::Failed { .. }
    ));
    assert_eq!(
        fixture
            .inspect(command_key("original-hook"))
            .await
            .1
            .unwrap()
            .value()
            .unwrap()
            .bytes,
        b"owned result"
    );
    assert!(budget.reserve_host_memory(1).is_err());
    drop((repeated, completion, execution, admission));
    fixture.shutdown().await;
}
