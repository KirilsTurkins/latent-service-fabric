mod fixture;

use super::*;
use crate::{TransactionActivationAdmission, TransactionAdmission, TransactionExecution};
use fixture::Fixture;
use latent_activation::{ActivationOutcome, ActivationSuccess};
use latent_core::{
    ActivationTerminalState, BudgetConsumption, CancelDisposition, PlatformError, PlatformErrorCode,
};
use latent_executor::transaction::Mode;
use latent_state::{
    embedded::{Family, RowKey},
    store_io::StoreIoKind,
};
use std::{sync::Arc, time::Duration};

// Original common-owner schedules use the same five-second barrier watchdog
// and ten-second admitted wall-time ceiling. Neither is extended for this port.
const WATCHDOG: Duration = Duration::from_secs(5);

fn execute(admission: TransactionAdmission) -> TransactionExecution {
    match admission {
        TransactionAdmission::Execute(execution) => execution,
        TransactionAdmission::Existing(_) => panic!("original command must obtain its actual host"),
    }
}
fn unstarted_failure() -> ActivationOutcome {
    ActivationOutcome::Failed {
        terminal_state: ActivationTerminalState::PlatformFailed,
        error: PlatformError {
            code: PlatformErrorCode::Internal,
            message: "native fixture owns no guest Store references".into(),
            retryable: false,
            details: Vec::new(),
        },
        consumption: BudgetConsumption::default(),
    }
}
async fn finish(
    execution: &TransactionExecution,
    outcome: ActivationOutcome,
) -> TransactionCompletion {
    execution.host.finish_guest_access();
    // Match Lifecycle.complete: terminal authorization and the actual native
    // completion run before publication freezes the original root ledger.
    let completed = tokio::time::timeout(WATCHDOG, execution.completion.complete(outcome))
        .await
        .unwrap();
    let _ = execution
        .host
        .budget()
        .finalize_at(None, std::time::Instant::now());
    completed
}
async fn retire(execution: &TransactionExecution) {
    let completed = finish(execution, unstarted_failure()).await;
    let record = completed
        .durable_command()
        .expect("actual aborted original command receipt");
    assert_eq!(record.outcome(), latent_commit::atomic::Outcome::Aborted);
    assert!(!completed.disposition().unwrap().requires_recovery());
}
fn success() -> ActivationOutcome {
    ActivationOutcome::Succeeded(ActivationSuccess {
        output: b"actual-native-result".to_vec(),
        output_media_type: "application/octet-stream".into(),
        consumption: BudgetConsumption::default(),
        committed_state_version: None,
        effect_ids: vec![],
        metadata: latent_core::Metadata::new(),
    })
}

#[tokio::test]
async fn unbound_original_budget_refuses_current_authorization_before_pending_or_entity_work() {
    let fixture = Fixture::new().await;
    let call = fixture.unbound_call("unbound", "hot");
    let before = fixture.owners.store.snapshot().unwrap();
    let deadline = call.budget.deadline().monotonic();
    assert!(call.budget.descendant_is_cancelled());
    call.admission
        .preflight(&call.envelope, &call.budget)
        .await
        .unwrap();
    let error = call
        .admission
        .admit(&call.envelope, &call.budget)
        .await
        .err()
        .expect("unbound original cancellation owner must remain denied");
    assert_eq!(error.code, PlatformErrorCode::PermissionDenied);
    assert_eq!(call.budget.deadline().monotonic(), deadline);
    assert_eq!(fixture.lanes.snapshot().unwrap(), Default::default());
    fixture.assert_no_claim().await;
    assert_eq!(
        fixture.owners.store.snapshot().unwrap().physical_owners,
        before.physical_owners
    );
    drop(call);
    fixture.shutdown().await;
}

#[tokio::test]
async fn actual_registered_root_cancellation_refuses_claim_before_any_lane_or_host() {
    let fixture = Fixture::new().await;
    let call = fixture.call("cancel-before-claim", "hot");
    let deadline = call.budget.deadline().monotonic();
    assert!(!call.budget.descendant_is_cancelled());
    assert_eq!(
        fixture
            .cancellations
            .cancel(call.registration.activation_id(), "before claim")
            .unwrap(),
        CancelDisposition::Accepted
    );
    assert!(call.budget.descendant_is_cancelled());
    let error = call
        .admission
        .admit(&call.envelope, &call.budget)
        .await
        .err()
        .expect("original cancelled root must not acquire a command");
    assert_eq!(error.code, PlatformErrorCode::PermissionDenied);
    assert_eq!(call.budget.deadline().monotonic(), deadline);
    assert_eq!(fixture.lanes.snapshot().unwrap(), Default::default());
    fixture.assert_no_claim().await;
    drop(call);
    fixture.shutdown().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn detached_original_transport_retires_queued_claim_without_cancellation_or_refunding_active_owner(
) {
    let fixture = Fixture::new().await;
    let first = fixture.call("first", "hot");
    let execution = execute(first.admit().await);
    let original = fixture.owners.store.snapshot().unwrap();
    let stopped = fixture.call("disconnected", "hot");
    let waiting = stopped.waiting();
    fixture.queued(1).await;
    assert_eq!(
        fixture.owners.store.snapshot().unwrap().physical_owners,
        original.physical_owners + 1
    );
    let original_deadline = stopped.budget.deadline().monotonic();
    stopped.interrupt_transport(crate::ActivationTransportInterruption::Disconnected);
    let TransactionAdmission::Existing(completed) = tokio::time::timeout(WATCHDOG, waiting)
        .await
        .unwrap()
        .unwrap()
        .unwrap()
    else {
        panic!("interrupted original transport must clean its Pending claim before opening a host");
    };
    assert_eq!(stopped.budget.deadline().monotonic(), original_deadline);
    assert!(!stopped.registration.token().is_cancelled());
    assert_eq!(
        completed.durable_command().unwrap().outcome(),
        latent_commit::atomic::Outcome::Aborted
    );
    assert!(
        matches!(completed.outcome(), ActivationOutcome::Failed { error, .. } if error.code == PlatformErrorCode::Cancelled && error.message == "activation transport disconnected")
    );
    assert_eq!(fixture.lanes.snapshot().unwrap().queued, 0);
    assert_eq!(fixture.lanes.snapshot().unwrap().active, 1);
    assert_eq!(
        fixture.owners.store.snapshot().unwrap().physical_owners,
        original.physical_owners
    );
    let cold = fixture.call("cold-after-disconnect", "cold");
    let cold_execution = execute(tokio::time::timeout(WATCHDOG, cold.admit()).await.unwrap());
    assert_eq!(fixture.lanes.snapshot().unwrap().active, 2);
    retire(&cold_execution).await;
    retire(&execution).await;
    assert_eq!(fixture.lanes.snapshot().unwrap(), Default::default());
    drop((completed, cold_execution, execution, first, stopped, cold));
    fixture.shutdown().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn actual_duplicate_uses_original_waiter_and_replays_without_entity_enqueue_or_another_host()
{
    let fixture = Fixture::new().await;
    let original = fixture.call("same-command", "hot");
    let execution = execute(original.admit().await);
    let duplicate = fixture.call("same-command", "hot");
    let waiting = duplicate.waiting();
    tokio::time::timeout(WATCHDOG, async {
        while fixture.waiters.snapshot().unwrap().waiters != 1 {
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();
    assert_eq!(fixture.lanes.snapshot().unwrap().active, 1);
    assert_eq!(fixture.lanes.snapshot().unwrap().queued, 0);
    assert!(!waiting.is_finished());
    let committed = finish(&execution, success()).await;
    assert_eq!(
        committed.durable_command().unwrap().outcome(),
        latent_commit::atomic::Outcome::Committed
    );
    let TransactionAdmission::Existing(replayed) = tokio::time::timeout(WATCHDOG, waiting)
        .await
        .unwrap()
        .unwrap()
        .unwrap()
    else {
        panic!("original command replay cannot schedule another host");
    };
    assert_eq!(replayed.durable_command(), committed.durable_command());
    assert!(
        matches!(replayed.outcome(), ActivationOutcome::Succeeded(result) if result.output == b"actual-native-result")
    );
    assert_eq!(fixture.lanes.snapshot().unwrap(), Default::default());
    drop((committed, replayed, execution, original, duplicate));
    fixture.shutdown().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn two_real_factories_share_hot_eligibility_before_view_and_allow_cold_progress() {
    let fixture = Fixture::new().await;
    let first = fixture.call("first", "hot");
    let first_execution = execute(first.admit().await);
    let original = fixture.owners.store.snapshot().unwrap();
    let second = fixture.call("second", "hot");
    let waiting = second.waiting();
    fixture.queued(1).await;
    let queued = fixture.owners.store.snapshot().unwrap();
    // Durable Pending prepays one original operation. It opens no retained
    // native view, guest Store, host operation or scheduler cell while queued.
    assert_eq!(queued.physical_owners, original.physical_owners + 1);
    assert_eq!(queued.active_reads, original.active_reads);
    assert!(!waiting.is_finished());
    assert_eq!(fixture.lanes.snapshot().unwrap().active, 1);
    let cold = fixture.call("cold", "cold");
    let cold_execution = execute(tokio::time::timeout(WATCHDOG, cold.admit()).await.unwrap());
    assert_eq!(fixture.lanes.snapshot().unwrap().active, 2);
    assert_eq!(fixture.lanes.snapshot().unwrap().queued, 1);
    retire(&cold_execution).await;
    retire(&first_execution).await;
    let second_execution = execute(
        tokio::time::timeout(WATCHDOG, waiting)
            .await
            .unwrap()
            .unwrap()
            .unwrap(),
    );
    assert!(second_execution
        .host
        .budget()
        .is_same_instance(&second.budget));
    assert_eq!(fixture.lanes.snapshot().unwrap().active, 1);
    assert_eq!(fixture.lanes.snapshot().unwrap().queued, 0);
    retire(&second_execution).await;
    assert_eq!(fixture.lanes.snapshot().unwrap(), Default::default());
    drop((
        first_execution,
        second_execution,
        cold_execution,
        first,
        second,
        cold,
    ));
    fixture.shutdown().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_registered_cancellation_removes_only_the_queued_command_and_publishes_its_abort()
{
    let fixture = Fixture::new().await;
    let first = fixture.call("first", "hot");
    let first_execution = execute(first.admit().await);
    let second = fixture.call("second", "hot");
    let waiting = second.waiting();
    fixture.queued(1).await;
    assert_eq!(
        fixture
            .cancellations
            .cancel(second.registration.activation_id(), "queued cancellation")
            .unwrap(),
        CancelDisposition::Accepted
    );
    let TransactionAdmission::Existing(completed) = tokio::time::timeout(WATCHDOG, waiting)
        .await
        .unwrap()
        .unwrap()
        .unwrap()
    else {
        panic!("queued cancellation must not open a guest host");
    };
    assert_eq!(
        completed.durable_command().unwrap().outcome(),
        latent_commit::atomic::Outcome::Aborted
    );
    assert_eq!(fixture.lanes.snapshot().unwrap().queued, 0);
    assert_eq!(fixture.lanes.snapshot().unwrap().active, 1);
    assert!(first_execution
        .host
        .budget()
        .is_same_instance(&first.budget));
    retire(&first_execution).await;
    assert_eq!(fixture.lanes.snapshot().unwrap(), Default::default());
    drop((completed, first_execution, first, second));
    fixture.shutdown().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn queued_current_policy_revocation_refuses_guest_view_and_preserves_recovery_disposition() {
    let fixture = Fixture::new().await;
    let first = fixture.call("first", "hot");
    let first_execution = execute(first.admit().await);
    let second = fixture.call("second", "hot");
    let waiting = second.waiting();
    fixture.queued(1).await;
    fixture.revoke_policy();
    // The current policy prevents abort publication as well as execution. The
    // original attempt retires, while its durable Pending row requires repair.
    let original = finish(&first_execution, unstarted_failure()).await;
    assert!(original.disposition().unwrap().requires_recovery());
    let TransactionAdmission::Existing(refused) = tokio::time::timeout(WATCHDOG, waiting)
        .await
        .unwrap()
        .unwrap()
        .unwrap()
    else {
        panic!("revocation must refuse queued host opening");
    };
    assert!(refused.disposition().unwrap().requires_recovery());
    assert!(refused.durable_command().is_none());
    assert!(matches!(
        refused.outcome(),
        ActivationOutcome::Failed { .. }
    ));
    assert_eq!(fixture.lanes.snapshot().unwrap(), Default::default());
    drop((original, refused, first_execution, first, second));
    fixture.shutdown().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn detached_actual_native_reader_keeps_hot_lane_through_host_cleanup_until_physical_return() {
    let fixture = Fixture::new().await;
    let first = fixture.call("first", "hot");
    let first_execution = execute(first.admit().await);
    let host = first.admission.observed_host();
    let actual = host
        .retain_entity()
        .unwrap()
        .expect("actual claimed physical lane owner");
    let keeper: Arc<dyn std::any::Any + Send + Sync> = Arc::new((Arc::clone(&host), actual));
    let (entered, entered_waiter) = tokio::sync::oneshot::channel();
    let (release, release_waiter) = std::sync::mpsc::channel();
    let physical = fixture
        .owners
        .store
        .with_store_retaining(StoreIoKind::Read, 4096, keeper, move |store| {
            let view = store.snapshot()?;
            let absent = view
                .get(&RowKey {
                    family: Family::State,
                    key: b"counter".to_vec(),
                })?
                .is_none();
            entered.send(()).unwrap();
            release_waiter.recv_timeout(WATCHDOG).unwrap();
            drop(view);
            Ok(absent)
        })
        .unwrap();
    tokio::time::timeout(WATCHDOG, entered_waiter)
        .await
        .unwrap()
        .unwrap();
    drop(physical); // Only observation detaches; the native closure still owns it.
    retire(&first_execution).await;
    assert_eq!(fixture.lanes.snapshot().unwrap().active, 1);
    let second = fixture.call("second", "hot");
    let waiting = second.waiting();
    fixture.queued(1).await;
    assert!(!waiting.is_finished());
    release.send(()).unwrap();
    let second_execution = execute(
        tokio::time::timeout(WATCHDOG, waiting)
            .await
            .unwrap()
            .unwrap()
            .unwrap(),
    );
    retire(&second_execution).await;
    assert_eq!(fixture.lanes.snapshot().unwrap(), Default::default());
    drop((host, first_execution, second_execution, first, second));
    fixture.shutdown().await;
}

#[tokio::test]
async fn actual_final_commit_accepts_original_fences_and_retired_observation_cannot_execute_again()
{
    let fixture = Fixture::new().await;
    let call = fixture.call("commit", "hot");
    let execution = execute(call.admit().await);
    let host = call.admission.observed_host();
    let observer = host.retain_entity().unwrap().unwrap().fence();
    execution.host.acquire(Mode::Command).unwrap();
    execution
        .host
        .put(
            b"counter".to_vec(),
            latent_core::transaction_contract::Value {
                bytes: 7u64.to_le_bytes().to_vec(),
                media_type: "application/octet-stream".into(),
                metadata: vec![],
            },
        )
        .await
        .unwrap();
    execution.host.release(Mode::Command);
    let completed = finish(&execution, success()).await;
    assert_eq!(
        completed.durable_command().unwrap().outcome(),
        latent_commit::atomic::Outcome::Committed
    );
    assert!(completed.delivery_fence().is_some());
    assert_eq!(fixture.lanes.snapshot().unwrap(), Default::default());
    let mut invoked = false;
    assert!(observer
        .with_current(|| {
            invoked = true;
        })
        .is_err());
    assert!(
        !invoked,
        "retired observer must refuse before any acceptance callback"
    );
    drop((completed, observer, host, execution, call));
    fixture.shutdown().await;
}

#[tokio::test]
async fn original_cancellation_gate_rejects_final_write_with_current_entity_and_policy_fences() {
    let fixture = Fixture::new().await;
    let call = fixture.call("cancel-before-commit", "hot");
    let execution = execute(call.admit().await);
    let host = call.admission.observed_host();
    let observer = host.retain_entity().unwrap().unwrap().fence();
    assert!(observer.with_current(|| ()).is_ok());
    assert_eq!(
        fixture
            .cancellations
            .cancel(call.registration.activation_id(), "before final acceptance")
            .unwrap(),
        CancelDisposition::Accepted
    );
    let completed = finish(&execution, success()).await;
    assert!(matches!(
        completed.outcome(),
        ActivationOutcome::Failed { .. }
    ));
    assert_ne!(
        completed.durable_command().map(|record| record.outcome()),
        Some(latent_commit::atomic::Outcome::Committed)
    );
    assert_eq!(fixture.lanes.snapshot().unwrap(), Default::default());
    assert!(observer
        .with_current(|| panic!("stale fence must never accept"))
        .is_err());
    drop((completed, observer, host, execution, call));
    fixture.shutdown().await;
}
