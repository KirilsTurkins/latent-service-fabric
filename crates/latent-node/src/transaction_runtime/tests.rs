//! Real protected-engine/policy tests. These are native host-owner tests;
//! the six authored Wasmtime components have a separate execution campaign.
mod fixture;

use super::*;
use crate::TransactionActivationAdmission;
use fixture::*;
use latent_activation::{ActivationOutcome, ActivationSuccess};
use latent_commit::atomic::Outcome;
use latent_core::{BudgetConsumption, DeclaredError, Metadata};
use latent_executor::transaction::{Mode, StateFailure, TransactionHost};
use latent_state::embedded::Family;

#[tokio::test]
async fn native_admission_persists_pending_before_host_and_success_commits_once() {
    let fixture = Fixture::new().await;
    let (admission, envelope, budget) = fixture.invocation(false, "one");
    let host = admission.admit(&envelope, &budget).await.unwrap();
    assert!(host.budget().is_same_instance(&budget));
    assert_eq!(fixture.rows(Family::Command).await, 1);
    let TransactionAdmissionResult::Command { claim, host } =
        admission.take_result().unwrap().unwrap()
    else {
        panic!("command host absent");
    };
    let key = claim.record().key().clone();
    assert_eq!(claim.record().outcome(), Outcome::Pending);
    host.acquire(Mode::Command).unwrap();
    assert!(host.read(b"counter".to_vec()).await.unwrap().is_none());
    host.put(b"counter".to_vec(), value(b"one")).await.unwrap();
    let (duplicate, duplicate_envelope, duplicate_budget) = fixture.invocation(false, "one");
    assert!(duplicate
        .admit(&duplicate_envelope, &duplicate_budget)
        .await
        .is_err());
    assert!(matches!(
        duplicate.take_result().unwrap(),
        Some(TransactionAdmissionResult::Existing(_))
    ));
    assert_eq!(fixture.rows(Family::Command).await, 1);
    host.finish_guest_access(); // exact native test owns no guest references
    let completion =
        CommandCompletion::new(claim, host, fixture.effects.clone(), fixture.time.clone()).unwrap();
    let result = completion.finish(success(b"result")).await;
    let CommandCompletionDisposition::Durable {
        command,
        result,
        cleanup_failure,
        retained,
    } = result
    else {
        panic!("native commit was not durable");
    };
    assert_eq!(command.outcome(), Outcome::Committed);
    assert_eq!(result.value().unwrap().bytes, b"result");
    assert!(cleanup_failure.is_none());
    let (record, body) = fixture.inspect(key).await;
    assert_eq!(record, command);
    assert_eq!(body.unwrap(), *result);
    assert_eq!(fixture.rows(Family::State).await, 1);
    drop(retained);
    fixture.shutdown().await;
}

#[tokio::test]
async fn native_declared_rejection_discards_state_and_preserves_exact_result() {
    let fixture = Fixture::new().await;
    let (admission, envelope, budget) = fixture.invocation(false, "rejected");
    admission.admit(&envelope, &budget).await.unwrap();
    let TransactionAdmissionResult::Command { claim, host } =
        admission.take_result().unwrap().unwrap()
    else {
        panic!("command host absent");
    };
    host.acquire(Mode::Command).unwrap();
    host.put(b"counter".to_vec(), value(b"discarded"))
        .await
        .unwrap();
    host.finish_guest_access();
    let result = CommandCompletion::new(claim, host, fixture.effects.clone(), fixture.time.clone())
        .unwrap()
        .finish(ActivationOutcome::DeclaredError {
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
    let CommandCompletionDisposition::Durable {
        command,
        result,
        cleanup_failure,
        ..
    } = result
    else {
        panic!("rejection was not durable");
    };
    assert_eq!(command.outcome(), Outcome::Rejected);
    assert_eq!(result.value().unwrap().bytes, b"reason");
    assert!(cleanup_failure.is_none());
    assert_eq!(fixture.rows(Family::State).await, 0);
    assert_eq!(fixture.rows(Family::Outbox).await, 0);
    fixture.shutdown().await;
}

#[tokio::test]
async fn native_fresh_query_is_read_only_and_creates_no_command_journal() {
    let fixture = Fixture::new().await;
    let (admission, envelope, budget) = fixture.invocation(true, "query");
    let host = admission.admit(&envelope, &budget).await.unwrap();
    host.acquire(Mode::Query).unwrap();
    assert!(host.read(b"missing".to_vec()).await.unwrap().is_none());
    assert_eq!(
        host.put(b"counter".to_vec(), value(b"denied")).await,
        Err(StateFailure::WrongMode)
    );
    assert_eq!(host.view_identity().unwrap().version.len(), 16);
    let TransactionAdmissionResult::Query { host } = admission.take_result().unwrap().unwrap()
    else {
        panic!("query host absent");
    };
    assert_eq!(host.retire().await, Err(StateFailure::HandleClosed));
    host.finish_guest_access();
    host.retire().await.unwrap();
    host.retire().await.unwrap();
    for family in [
        Family::Command,
        Family::Attempt,
        Family::Result,
        Family::Outbox,
    ] {
        assert_eq!(fixture.rows(family).await, 0);
    }
    fixture.shutdown().await;
}

#[tokio::test]
async fn native_policy_revocation_denies_access_without_false_physical_retirement() {
    let fixture = Fixture::new().await;
    let (admission, envelope, budget) = fixture.invocation(false, "revoked");
    admission.admit(&envelope, &budget).await.unwrap();
    let TransactionAdmissionResult::Command { claim, host } =
        admission.take_result().unwrap().unwrap()
    else {
        panic!("command host absent");
    };
    host.acquire(Mode::Command).unwrap();
    let retirement = claim.retirement();
    fixture.revoke();
    assert_eq!(
        host.read(b"counter".to_vec()).await,
        Err(StateFailure::PermissionDenied)
    );
    assert_eq!(host.retire().await, Err(StateFailure::HandleClosed));
    assert!(retirement.proven_noncommit().is_err());
    host.finish_guest_access();
    host.retire().await.unwrap();
    drop(claim);
    assert!(retirement.proven_noncommit().is_ok());
    host.retire_command_role().unwrap();
    assert_eq!(fixture.rows(Family::State).await, 0);
    fixture.shutdown().await;
}

#[tokio::test]
async fn native_incompatible_selected_source_rejects_before_durable_admission() {
    let fixture = Fixture::new().await;
    let (admission, mut envelope, budget) = fixture.invocation(false, "bad-source");
    envelope.resolved_revision.as_mut().unwrap().release.0 = format!("sha256:{}", "f".repeat(64));
    assert!(admission.admit(&envelope, &budget).await.is_err());
    assert!(admission.take_result().unwrap().is_none());
    assert_eq!(fixture.rows(Family::Command).await, 0);
    assert_eq!(fixture.rows(Family::Result).await, 0);
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
