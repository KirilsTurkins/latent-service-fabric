//! Real protected-engine/policy tests. These are native host-owner tests;
//! the six authored Wasmtime components have a separate execution campaign.
mod cancellation;
mod cancellation_abort;
mod capacity;
pub(super) mod fixture;
mod history;
mod response;
mod staging;
mod technical_abort;

use super::*;
use crate::TransactionActivationAdmission;
use fixture::*;
use latent_activation::{ActivationOutcome, ActivationSuccess};
use latent_commit::atomic::Outcome;
use latent_core::{BudgetConsumption, DeclaredError, Metadata};
use latent_executor::transaction::{Mode, StateFailure, TransactionHost};
use latent_state::embedded::Family;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn trusted_inbox_admission_commits_the_original_input_and_recovers_duplicate() {
    use latent_commit::atomic::{Identity, InboxIdentity};
    use sha2::{Digest, Sha256};

    let fixture = Fixture::with_trigger().await;
    let identity = InboxIdentity {
        provider: "input".into(),
        binding: "scope".into(),
        message: "42".into(),
        payload_digest: Identity::parse_hex(&format!(
            "{:x}",
            latent_core::digest::HexDigest(Sha256::digest(b"same"))
        ))
        .unwrap(),
    };
    let (first, mut envelope, budget) = fixture.invocation(false, &identity.command_key().unwrap());
    envelope.principal.kind = latent_core::PrincipalKind::Trigger;
    let first = Arc::new(
        Arc::try_unwrap(first)
            .ok()
            .unwrap()
            .with_trusted_inbox(identity.clone())
            .unwrap(),
    );
    let guest = first.admit(&envelope, &budget).await.unwrap();
    guest.acquire(Mode::Command).unwrap();
    guest.finish_guest_access();
    let _ = budget.finalize_at(None, std::time::Instant::now());
    first
        .complete(
            success(b"original"),
            fixture.commit_control(&envelope, &budget),
        )
        .await;
    let original = first.take_owned_completion().unwrap().unwrap();
    let TransactionCompletionResult::Command(CommandCompletionDisposition::Durable {
        command, ..
    }) = &original.result
    else {
        panic!("input command did not commit");
    };
    assert_eq!(command.inbox_identity(), Some(&identity));
    assert_eq!(fixture.rows(Family::Inbox).await, 1);
    drop((guest, original, first, envelope, budget));

    let (replay, mut envelope, budget) =
        fixture.invocation(false, &identity.command_key().unwrap());
    envelope.principal.kind = latent_core::PrincipalKind::Trigger;
    let replay = Arc::new(
        Arc::try_unwrap(replay)
            .ok()
            .unwrap()
            .with_trusted_inbox(identity)
            .unwrap(),
    );
    assert_eq!(
        replay.admit(&envelope, &budget).await.err().unwrap().code,
        latent_core::PlatformErrorCode::AlreadyExists
    );
    let _ = budget.finalize_at(None, std::time::Instant::now());
    replay
        .complete(
            success(b"not executed"),
            fixture.commit_control(&envelope, &budget),
        )
        .await;
    assert!(matches!(
        replay.take_owned_completion().unwrap().unwrap().result,
        TransactionCompletionResult::Existing { .. }
    ));
    assert_eq!(fixture.rows(Family::Inbox).await, 1);
    drop((replay, envelope, budget));
    fixture.shutdown().await;
}

#[tokio::test]
async fn trusted_inbox_refuses_wrong_principal_payload_and_query_mode_before_storage() {
    use latent_commit::atomic::{Identity, InboxIdentity};
    use sha2::{Digest, Sha256};

    let fixture = Fixture::with_trigger().await;
    let identity = InboxIdentity {
        provider: "input".into(),
        binding: "scope".into(),
        message: "42".into(),
        payload_digest: Identity::parse_hex(&format!(
            "{:x}",
            latent_core::digest::HexDigest(Sha256::digest(b"same"))
        ))
        .unwrap(),
    };
    let (ordinary, envelope, budget) = fixture.invocation(false, &identity.command_key().unwrap());
    let ordinary = Arc::try_unwrap(ordinary)
        .ok()
        .unwrap()
        .with_trusted_inbox(identity.clone())
        .unwrap();
    assert_eq!(
        ordinary.admit(&envelope, &budget).await.err().unwrap().code,
        latent_core::PlatformErrorCode::PermissionDenied
    );
    drop((ordinary, envelope, budget));

    let (changed, mut envelope, budget) =
        fixture.invocation(false, &identity.command_key().unwrap());
    envelope.principal.kind = latent_core::PrincipalKind::Trigger;
    envelope.input = b"different".to_vec();
    let changed = Arc::try_unwrap(changed)
        .ok()
        .unwrap()
        .with_trusted_inbox(identity.clone())
        .unwrap();
    assert_eq!(
        changed.admit(&envelope, &budget).await.err().unwrap().code,
        latent_core::PlatformErrorCode::PermissionDenied
    );
    drop((changed, envelope, budget));

    let (wrong_key, envelope, budget) = fixture.invocation(false, "different-command-key");
    assert!(Arc::try_unwrap(wrong_key)
        .ok()
        .unwrap()
        .with_trusted_inbox(identity.clone())
        .is_err());
    drop((envelope, budget));

    let (query, envelope, budget) = fixture.invocation(true, "ignored");
    assert!(Arc::try_unwrap(query)
        .ok()
        .unwrap()
        .with_trusted_inbox(identity)
        .is_err());
    drop((envelope, budget));
    assert_eq!(fixture.rows(Family::Command).await, 0);
    assert_eq!(fixture.rows(Family::Inbox).await, 0);
    fixture.shutdown().await;
}

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
        Some(TransactionAdmissionResult::Existing { .. })
    ));
    assert_eq!(fixture.rows(Family::Command).await, 1);
    host.finish_guest_access(); // exact native test owns no guest references
    let _ = budget.finalize_at(None, std::time::Instant::now());
    assert!(budget.reserve_host_memory(1).is_err());
    let completion = CommandCompletion::new(
        claim,
        host,
        fixture.effects.clone(),
        fixture.time.clone(),
        fixture.commit_control(&envelope, &budget),
    )
    .unwrap();
    let result = completion.finish(success(b"result")).await;
    let CommandCompletionDisposition::Durable {
        command,
        result,
        cleanup_failure,
        retained,
        ..
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
    let _ = budget.finalize_at(None, std::time::Instant::now());
    let result = CommandCompletion::new(
        claim,
        host,
        fixture.effects.clone(),
        fixture.time.clone(),
        fixture.commit_control(&envelope, &budget),
    )
    .unwrap()
    .finish(ActivationOutcome::DeclaredError {
        error: DeclaredError {
            code: "rejected".into(),
            message: "business rejection".into(),
            payload: (b"reason".to_vec()).into(),
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
    assert_eq!(
        host.view_identity().unwrap().version.len(),
        latent_state::session::version::VIEW_TOKEN_BYTES
    );
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
        output: (bytes.to_vec()).into(),
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
    admission.admit(&envelope, &budget).await.unwrap();
    let TransactionAdmissionResult::Command { claim, host } =
        admission.take_result().unwrap().unwrap()
    else {
        panic!("command absent")
    };
    let key = claim.record().key().clone();
    host.acquire(Mode::Command).unwrap();
    host.put(b"counter".to_vec(), value(b"never committed"))
        .await
        .unwrap();
    host.finish_guest_access();
    let _ = budget.finalize_at(None, std::time::Instant::now());
    fixture.cancel_original(&envelope);
    let completion = CommandCompletion::new(
        claim,
        host,
        fixture.effects.clone(),
        fixture.time.clone(),
        fixture.commit_control(&envelope, &budget),
    )
    .unwrap();
    let result = completion.finish(success(b"discarded")).await;
    assert!(matches!(
        result,
        CommandCompletionDisposition::Retired { .. }
    ));
    let (command, body) = fixture.inspect(key).await;
    assert_eq!(command.outcome(), Outcome::Pending);
    assert!(body.is_none());
    assert_eq!(fixture.rows(Family::State).await, 0);
    assert_eq!(fixture.rows(Family::Outbox).await, 0);
    drop(result);
    fixture.shutdown().await;
}

#[tokio::test]
async fn native_manager_completion_hook_commits_once_and_retains_affine_result() {
    let fixture = Fixture::new().await;
    let (admission, envelope, budget) = fixture.invocation(false, "original-hook");
    let host = admission.admit(&envelope, &budget).await.unwrap();
    host.acquire(Mode::Command).unwrap();
    host.put(b"counter".to_vec(), value(b"hook committed"))
        .await
        .unwrap();
    host.finish_guest_access();
    let _ = budget.finalize_at(None, std::time::Instant::now());
    let observed = admission
        .complete(
            success(b"owned result"),
            fixture.commit_control(&envelope, &budget),
        )
        .await;
    let ActivationOutcome::Succeeded(observed) = observed else {
        panic!("commit failed")
    };
    assert!(observed.output.is_empty());
    assert!(admission.take_result().unwrap().is_none());
    let Some(TransactionCompletionResult::Command(CommandCompletionDisposition::Durable {
        command,
        result,
        retained,
        cleanup_failure,
        ..
    })) = admission.take_completion().unwrap()
    else {
        panic!("durable result absent")
    };
    assert_eq!(command.outcome(), Outcome::Committed);
    assert_eq!(result.value().unwrap().bytes, b"owned result");
    assert!(cleanup_failure.is_none());
    assert!(admission.take_completion().unwrap().is_none());
    assert!(budget.reserve_host_memory(1).is_err());
    drop((result, retained));
    fixture.shutdown().await;
}
