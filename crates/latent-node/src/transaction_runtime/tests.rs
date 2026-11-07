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

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn entity_admission_waits_for_commit_before_opening_the_next_snapshot() {
    let fixture = Fixture::new().await;
    let (first, first_envelope, first_budget) = fixture.entity_invocation("first", "hot");
    first.admit(&first_envelope, &first_budget).await.unwrap();
    let TransactionAdmissionResult::Command { claim, host } = first.take_result().unwrap().unwrap()
    else {
        panic!("first command host absent");
    };
    host.acquire(Mode::Command).unwrap();
    host.put(b"counter".to_vec(), value(b"committed"))
        .await
        .unwrap();

    let (second, second_envelope, second_budget) = fixture.entity_invocation("second", "hot");
    let queued_admission = Arc::clone(&second);
    let queued_envelope = second_envelope.clone();
    let queued_budget = second_budget.clone();
    let waiting = tokio::spawn(async move {
        queued_admission
            .admit(&queued_envelope, &queued_budget)
            .await
    });
    tokio::time::timeout(std::time::Duration::from_secs(5), async {
        while fixture.owners.lanes.snapshot().queued < 1 {
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();
    assert!(!waiting.is_finished());

    host.finish_guest_access();
    let _ = first_budget.finalize_at(None, std::time::Instant::now());
    let completion = CommandCompletion::new(
        claim,
        host,
        fixture.effects.clone(),
        fixture.time.clone(),
        fixture.commit_control(&first_envelope, &first_budget),
    )
    .unwrap();
    let first_result = Box::pin(completion.finish(success(b"ok"))).await;
    match &first_result {
        CommandCompletionDisposition::Durable {
            cleanup_failure: None,
            ..
        } => {}
        CommandCompletionDisposition::Durable {
            cleanup_failure, ..
        } => {
            waiting.abort();
            panic!("first command cleanup failed: {cleanup_failure:?}");
        }
        CommandCompletionDisposition::Retired { reason, .. } => {
            waiting.abort();
            panic!("first command retired: {reason:?}");
        }
        CommandCompletionDisposition::RecoveryRequired {
            cleanup_failure, ..
        } => {
            waiting.abort();
            panic!("first command needs recovery: {cleanup_failure:?}");
        }
    }

    tokio::time::timeout(std::time::Duration::from_secs(5), waiting)
        .await
        .unwrap()
        .unwrap()
        .unwrap();
    let TransactionAdmissionResult::Command { claim, host } =
        second.take_result().unwrap().unwrap()
    else {
        panic!("second command host absent");
    };
    host.acquire(Mode::Command).unwrap();
    assert_eq!(
        host.read(b"counter".to_vec())
            .await
            .unwrap()
            .unwrap()
            .value
            .bytes,
        b"committed"
    );
    let retirement = claim.retirement();
    host.finish_guest_access();
    host.retire().await.unwrap();
    drop(claim);
    assert!(retirement.proven_noncommit().is_ok());
    host.retire_command_role().unwrap();
    drop((first, second, host));
    fixture.shutdown().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn cancelling_queued_entity_admission_removes_its_reservation_before_claim() {
    let fixture = Fixture::new().await;
    let (first, first_envelope, first_budget) = fixture.entity_invocation("first-cancel", "hot");
    first.admit(&first_envelope, &first_budget).await.unwrap();
    let TransactionAdmissionResult::Command { claim, host } = first.take_result().unwrap().unwrap()
    else {
        panic!("first command host absent");
    };
    let (second, envelope, budget) = fixture.entity_invocation("second-cancel", "hot");
    let control = fixture.admission_control(&envelope, &budget);
    let queued_admission = Arc::clone(&second);
    let queued_envelope = envelope.clone();
    let queued_budget = budget.clone();
    let waiting = tokio::spawn(async move {
        queued_admission
            .admit_controlled(&queued_envelope, &queued_budget, control)
            .await
    });
    tokio::time::timeout(std::time::Duration::from_secs(5), async {
        while fixture.owners.lanes.snapshot().queued < 1 {
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();
    fixture.cancel_original(&envelope);
    let outcome = tokio::time::timeout(std::time::Duration::from_secs(5), waiting)
        .await
        .unwrap()
        .unwrap();
    assert!(
        matches!(outcome, Err(error) if error.code == latent_core::PlatformErrorCode::Cancelled)
    );
    assert_eq!(fixture.owners.lanes.snapshot().queued, 0);
    assert_eq!(fixture.owners.lanes.snapshot().active, 1);
    assert_eq!(fixture.rows(Family::Command).await, 1);
    let retirement = claim.retirement();
    host.finish_guest_access();
    host.retire().await.unwrap();
    drop(claim);
    assert!(retirement.proven_noncommit().is_ok());
    host.retire_command_role().unwrap();
    drop((first, second, host));
    fixture.shutdown().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn active_entity_duplicate_uses_the_durable_in_progress_path_without_waiting() {
    let fixture = Fixture::new().await;
    let (first, envelope, budget) = fixture.entity_invocation("duplicate", "hot");
    first.admit(&envelope, &budget).await.unwrap();
    let TransactionAdmissionResult::Command { claim, host } = first.take_result().unwrap().unwrap()
    else {
        panic!("first command host absent");
    };
    host.acquire(Mode::Command).unwrap();
    let (duplicate, duplicate_envelope, duplicate_budget) =
        fixture.entity_invocation("duplicate", "hot");
    let result = tokio::time::timeout(
        std::time::Duration::from_secs(5),
        duplicate.admit(&duplicate_envelope, &duplicate_budget),
    )
    .await
    .unwrap();
    assert!(
        matches!(result, Err(error) if error.code == latent_core::PlatformErrorCode::AlreadyExists)
    );
    let Some(TransactionAdmissionResult::Existing { command, .. }) =
        duplicate.take_result().unwrap()
    else {
        panic!("duplicate did not retain the existing durable command");
    };
    assert_eq!(command.outcome(), Outcome::Pending);
    assert_eq!(fixture.owners.lanes.snapshot().active, 1);
    assert_eq!(fixture.owners.lanes.snapshot().queued, 0);
    let (conflicting, mut conflict_envelope, conflict_budget) =
        fixture.entity_invocation("duplicate", "hot");
    conflict_envelope.input = b"different".to_vec();
    let conflict = conflicting
        .admit(&conflict_envelope, &conflict_budget)
        .await;
    assert!(
        matches!(conflict, Err(error) if error.code == latent_core::PlatformErrorCode::StateConflict)
    );
    assert!(conflicting.take_result().unwrap().is_none());
    assert_eq!(fixture.owners.lanes.snapshot().queued, 0);
    host.finish_guest_access();
    let _ = budget.finalize_at(None, std::time::Instant::now());
    let completion = CommandCompletion::new(
        claim,
        host,
        fixture.effects.clone(),
        fixture.time.clone(),
        fixture.commit_control(&envelope, &budget),
    )
    .unwrap();
    assert!(matches!(
        Box::pin(completion.finish(success(b"ok"))).await,
        CommandCompletionDisposition::Durable {
            cleanup_failure: None,
            ..
        }
    ));
    assert_eq!(fixture.rows(Family::Command).await, 1);
    assert_eq!(fixture.owners.lanes.snapshot().active, 0);
    drop((first, duplicate, conflicting));
    fixture.shutdown().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn duplicates_queued_before_the_first_claim_replay_when_that_claim_is_published() {
    use latent_core::native_capacity::NativeBufferClass;
    use latent_state::entity_lanes::EntityScope;

    let mut limits = latent_core::native_capacity::NativeCapacityLimits::default();
    limits.ordinary.bytes = 512 * 1024 * 1024;
    let fixture = Fixture::with_native_limits(limits).await;
    let deadline = std::time::Instant::now() + std::time::Duration::from_secs(10);
    let reservation = fixture.owners.reserve_ingress(0, deadline).unwrap();
    let permit = reservation
        .reserve_buffer(NativeBufferClass::Request, 16 * 1024)
        .unwrap();
    let scope = EntityScope::new(
        latent_core::TenantId("a".into()),
        latent_core::StateNamespaceId("orders".into()),
        1,
        latent_core::EntityKey("hot".into()),
    )
    .unwrap();
    let holder = fixture
        .owners
        .lanes
        .acquire(
            scope,
            b"test-holder".to_vec(),
            0,
            deadline,
            Arc::new(|| true),
            permit,
        )
        .await
        .unwrap();
    drop(reservation);
    let (one, one_envelope, one_budget) = fixture.entity_invocation("simultaneous", "hot");
    let (two, two_envelope, two_budget) = fixture.entity_invocation("simultaneous", "hot");
    let one_owner = Arc::clone(&one);
    let two_owner = Arc::clone(&two);
    let first = tokio::spawn(async move { one_owner.admit(&one_envelope, &one_budget).await });
    tokio::time::timeout(std::time::Duration::from_secs(5), async {
        while fixture.owners.lanes.snapshot().queued < 1 {
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();
    let second = tokio::spawn(async move { two_owner.admit(&two_envelope, &two_budget).await });
    tokio::time::timeout(std::time::Duration::from_secs(5), async {
        while fixture.owners.lanes.snapshot().queued < 2 {
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();
    drop(holder);
    let (first, second) = tokio::time::timeout(std::time::Duration::from_secs(5), async {
        tokio::join!(first, second)
    })
    .await
    .unwrap();
    let first = first.unwrap();
    let second = second.unwrap();
    let (winner, replay) = match (&first, &second) {
        (Ok(_), Err(error)) if error.code == latent_core::PlatformErrorCode::AlreadyExists => {
            (&one, &two)
        }
        (Err(error), Ok(_)) if error.code == latent_core::PlatformErrorCode::AlreadyExists => {
            (&two, &one)
        }
        _ => panic!("simultaneous duplicates did not resolve to one owner and one replay"),
    };
    let Some(TransactionAdmissionResult::Existing { command, .. }) = replay.take_result().unwrap()
    else {
        panic!("duplicate did not retain the existing command");
    };
    assert_eq!(command.outcome(), Outcome::Pending);
    let Some(TransactionAdmissionResult::Command { claim, host }) = winner.take_result().unwrap()
    else {
        panic!("winning command host absent");
    };
    assert_eq!(fixture.rows(Family::Command).await, 1);
    assert_eq!(fixture.owners.lanes.snapshot().queued, 0);
    let retirement = claim.retirement();
    host.finish_guest_access();
    host.retire().await.unwrap();
    drop(claim);
    assert!(retirement.proven_noncommit().is_ok());
    host.retire_command_role().unwrap();
    drop((first, second, host, one, two));
    fixture.shutdown().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn cold_entity_admission_progresses_while_the_hot_entity_waits() {
    let fixture = Fixture::new().await;
    let (hot, hot_envelope, hot_budget) = fixture.entity_invocation("hot-one", "hot");
    hot.admit(&hot_envelope, &hot_budget).await.unwrap();
    let TransactionAdmissionResult::Command {
        claim: hot_claim,
        host: hot_host,
    } = hot.take_result().unwrap().unwrap()
    else {
        panic!("hot command host absent");
    };
    let (waiting_admission, waiting_envelope, waiting_budget) =
        fixture.entity_invocation("hot-two", "hot");
    let control = fixture.admission_control(&waiting_envelope, &waiting_budget);
    let waiting_owner = Arc::clone(&waiting_admission);
    let queued_envelope = waiting_envelope.clone();
    let waiting = tokio::spawn(async move {
        waiting_owner
            .admit_controlled(&queued_envelope, &waiting_budget, control)
            .await
    });
    tokio::time::timeout(std::time::Duration::from_secs(5), async {
        while fixture.owners.lanes.snapshot().queued < 1 {
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();
    let (overflow, overflow_envelope, overflow_budget) =
        fixture.entity_invocation("hot-overflow", "hot");
    let rejected = overflow.admit(&overflow_envelope, &overflow_budget).await;
    assert!(matches!(rejected, Err(error)
        if error.code == latent_core::PlatformErrorCode::ResourceExhausted
            && error.message == "entity-queue-backpressure"));
    let (cold, cold_envelope, cold_budget) = fixture.entity_invocation("cold-one", "cold");
    tokio::time::timeout(
        std::time::Duration::from_secs(5),
        cold.admit(&cold_envelope, &cold_budget),
    )
    .await
    .unwrap()
    .unwrap();
    assert!(!waiting.is_finished());
    assert_eq!(fixture.owners.lanes.snapshot().active, 2);
    assert!(
        fixture.owners.lanes.snapshot().retained_bytes()
            >= 3 * super::capacity::minimum_ingress_bytes()
    );
    let TransactionAdmissionResult::Command {
        claim: cold_claim,
        host: cold_host,
    } = cold.take_result().unwrap().unwrap()
    else {
        panic!("cold command host absent");
    };
    fixture.cancel_original(&waiting_envelope);
    assert!(
        matches!(waiting.await.unwrap(), Err(error) if error.code == latent_core::PlatformErrorCode::Cancelled)
    );
    for (claim, host) in [(hot_claim, hot_host), (cold_claim, cold_host)] {
        let retirement = claim.retirement();
        host.finish_guest_access();
        host.retire().await.unwrap();
        drop(claim);
        assert!(retirement.proven_noncommit().is_ok());
        host.retire_command_role().unwrap();
    }
    assert_eq!(fixture.owners.lanes.snapshot().keys, 0);
    drop((hot, cold, waiting_admission, overflow));
    fixture.shutdown().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn policy_revoked_while_entity_is_queued_refuses_claim_and_guest_host() {
    let fixture = Fixture::new().await;
    let (first, first_envelope, first_budget) = fixture.entity_invocation("revoke-first", "hot");
    first.admit(&first_envelope, &first_budget).await.unwrap();
    let TransactionAdmissionResult::Command { claim, host } = first.take_result().unwrap().unwrap()
    else {
        panic!("first command host absent");
    };
    let (second, envelope, budget) = fixture.entity_invocation("revoke-second", "hot");
    let queued = Arc::clone(&second);
    let waiting = tokio::spawn(async move { queued.admit(&envelope, &budget).await });
    tokio::time::timeout(std::time::Duration::from_secs(5), async {
        while fixture.owners.lanes.snapshot().queued < 1 {
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();
    fixture.revoke();
    let retirement = claim.retirement();
    host.finish_guest_access();
    host.retire().await.unwrap();
    drop(claim);
    assert!(retirement.proven_noncommit().is_ok());
    host.retire_command_role().unwrap();
    assert!(
        tokio::time::timeout(std::time::Duration::from_secs(5), waiting)
            .await
            .unwrap()
            .unwrap()
            .is_err()
    );
    assert_eq!(fixture.rows(Family::Command).await, 1);
    assert!(second.take_result().unwrap().is_none());
    assert_eq!(fixture.owners.lanes.snapshot().keys, 0);
    drop((first, second, host));
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
