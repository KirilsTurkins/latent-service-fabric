use super::*;
use latent_core::{ActivationBudget, ActivationTerminalState, PlatformError, PlatformErrorCode};
use std::sync::Arc;
use std::time::Duration;

const WATCHDOG: Duration = Duration::from_secs(5);

async fn queued(fixture: &Fixture, count: usize) {
    tokio::time::timeout(WATCHDOG, async {
        while fixture.owners.entity_snapshot().unwrap().queued != count {
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();
}

fn unstarted_failure() -> ActivationOutcome {
    ActivationOutcome::Failed {
        terminal_state: ActivationTerminalState::PlatformFailed,
        error: PlatformError {
            code: PlatformErrorCode::Internal,
            message: "actual host fixture has no guest references".into(),
            retryable: false,
            details: Vec::new(),
        },
        consumption: BudgetConsumption::default(),
    }
}

async fn retire(
    fixture: &Fixture,
    admission: &NativeTransactionAdmission,
    host: Option<&Arc<dyn TransactionHost>>,
    envelope: &latent_activation::ActivationEnvelope,
    budget: &ActivationBudget,
) {
    if let Some(host) = host {
        host.finish_guest_access();
    }
    let _ = budget.finalize_at(None, std::time::Instant::now());
    admission
        .complete(
            unstarted_failure(),
            fixture.commit_control(envelope, budget),
        )
        .await;
    let completion = admission
        .take_completion()
        .unwrap()
        .expect("actual completion owner must publish retirement");
    assert!(
        matches!(
            &completion,
            TransactionCompletionResult::Command(CommandCompletionDisposition::Retired { .. })
                | TransactionCompletionResult::PendingRetired { proof: Ok(_), .. }
        ),
        "host/no-host cleanup must positively retire its original physical attempt"
    );
    drop(completion);
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn hot_entity_waits_before_view_and_cold_entity_opens_on_the_same_real_owner() {
    let mut fixture = Fixture::new().await;
    fixture.configure_entities(&["hot", "cold"], default_entity_limits());
    let (first, first_envelope, first_budget) = fixture.entity_invocation("first", "hot");
    let first_host = first.admit(&first_envelope, &first_budget).await.unwrap();
    let baseline = fixture.store_owners();
    let (second, second_envelope, second_budget) = fixture.entity_invocation("second", "hot");
    let second_worker = Arc::clone(&second);
    let worker_envelope = second_envelope.clone();
    let worker_budget = second_budget.clone();
    let waiting =
        tokio::spawn(async move { second_worker.admit(&worker_envelope, &worker_budget).await });
    queued(&fixture, 1).await;
    assert_eq!(
        fixture.store_owners(),
        baseline,
        "queued command must own no native view or operation"
    );
    assert_eq!(fixture.owners.entity_snapshot().unwrap().active, 1);
    assert!(!waiting.is_finished());
    let (cold, cold_envelope, cold_budget) = fixture.entity_invocation("cold", "cold");
    let cold_host = tokio::time::timeout(WATCHDOG, cold.admit(&cold_envelope, &cold_budget))
        .await
        .unwrap()
        .unwrap();
    assert_eq!(fixture.owners.entity_snapshot().unwrap().active, 2);
    assert_eq!(fixture.owners.entity_snapshot().unwrap().queued, 1);
    retire(
        &fixture,
        &cold,
        Some(&cold_host),
        &cold_envelope,
        &cold_budget,
    )
    .await;
    retire(
        &fixture,
        &first,
        Some(&first_host),
        &first_envelope,
        &first_budget,
    )
    .await;
    let second_host = tokio::time::timeout(WATCHDOG, waiting)
        .await
        .unwrap()
        .unwrap()
        .unwrap();
    assert!(second_host.budget().is_same_instance(&second_budget));
    assert_eq!(fixture.owners.entity_snapshot().unwrap().active, 1);
    assert_eq!(fixture.owners.entity_snapshot().unwrap().queued, 0);
    retire(
        &fixture,
        &second,
        Some(&second_host),
        &second_envelope,
        &second_budget,
    )
    .await;
    assert_eq!(
        fixture.owners.entity_snapshot().unwrap(),
        Default::default()
    );
    drop((first_host, cold_host, second_host, first, cold, second));
    fixture.shutdown().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn detached_queued_future_removes_only_its_original_reservation() {
    let mut fixture = Fixture::new().await;
    fixture.configure_entities(&["hot"], default_entity_limits());
    let (first, first_envelope, first_budget) = fixture.entity_invocation("first", "hot");
    let first_host = first.admit(&first_envelope, &first_budget).await.unwrap();
    let (second, second_envelope, second_budget) = fixture.entity_invocation("second", "hot");
    let worker = Arc::clone(&second);
    let envelope = second_envelope.clone();
    let budget = second_budget.clone();
    let waiting = tokio::spawn(async move { worker.admit(&envelope, &budget).await });
    queued(&fixture, 1).await;
    let active_bytes = fixture.owners.entity_snapshot().unwrap().active_bytes;
    waiting.abort();
    assert!(matches!(waiting.await, Err(error) if error.is_cancelled()));
    queued(&fixture, 0).await;
    assert_eq!(fixture.owners.entity_snapshot().unwrap().active, 1);
    assert_eq!(
        fixture.owners.entity_snapshot().unwrap().active_bytes,
        active_bytes
    );
    assert_eq!(fixture.owners.entity_snapshot().unwrap().keys, 1);
    retire(&fixture, &second, None, &second_envelope, &second_budget).await;
    retire(
        &fixture,
        &first,
        Some(&first_host),
        &first_envelope,
        &first_budget,
    )
    .await;
    assert_eq!(
        fixture.owners.entity_snapshot().unwrap(),
        Default::default()
    );
    drop((first_host, first, second));
    fixture.shutdown().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn revoked_queued_command_refuses_current_policy_before_opening_a_host() {
    let mut fixture = Fixture::new().await;
    fixture.configure_entities(&["hot"], default_entity_limits());
    let (first, first_envelope, first_budget) = fixture.entity_invocation("first", "hot");
    let first_host = first.admit(&first_envelope, &first_budget).await.unwrap();
    let (second, second_envelope, second_budget) = fixture.entity_invocation("second", "hot");
    let worker = Arc::clone(&second);
    let envelope = second_envelope.clone();
    let budget = second_budget.clone();
    let waiting = tokio::spawn(async move { worker.admit(&envelope, &budget).await });
    queued(&fixture, 1).await;
    fixture.revoke();
    retire(
        &fixture,
        &first,
        Some(&first_host),
        &first_envelope,
        &first_budget,
    )
    .await;
    let result = tokio::time::timeout(WATCHDOG, waiting)
        .await
        .unwrap()
        .unwrap();
    assert!(matches!(
        result,
        Err(PlatformError {
            code: PlatformErrorCode::PermissionDenied,
            ..
        })
    ));
    retire(&fixture, &second, None, &second_envelope, &second_budget).await;
    assert_eq!(
        fixture.owners.entity_snapshot().unwrap(),
        Default::default()
    );
    drop((first_host, first, second));
    fixture.shutdown().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn per_entity_backpressure_keeps_the_hot_owner_and_independent_cold_progress() {
    let mut fixture = Fixture::new().await;
    let mut limits = default_entity_limits();
    limits.entity_queued = 1;
    fixture.configure_entities(&["hot", "cold"], limits);
    let (first, first_envelope, first_budget) = fixture.entity_invocation("first", "hot");
    let first_host = first.admit(&first_envelope, &first_budget).await.unwrap();
    let (second, second_envelope, second_budget) = fixture.entity_invocation("second", "hot");
    let worker = Arc::clone(&second);
    let envelope = second_envelope.clone();
    let budget = second_budget.clone();
    let waiting = tokio::spawn(async move { worker.admit(&envelope, &budget).await });
    queued(&fixture, 1).await;
    let (refused, refused_envelope, refused_budget) = fixture.entity_invocation("refused", "hot");
    let refusal = match refused.admit(&refused_envelope, &refused_budget).await {
        Err(failure) => failure,
        Ok(_) => panic!("finite hot-key queue must refuse the extra original command"),
    };
    assert_eq!(refusal.code, PlatformErrorCode::ResourceExhausted);
    assert_eq!(
        refusal.details,
        vec![latent_core::ErrorDetail {
            kind: "entity-lane.limit".into(),
            fields: Metadata::from([("reason".into(), "entity-queue".into())]),
        }]
    );
    assert_eq!(fixture.owners.entity_snapshot().unwrap().queued, 1);
    let (cold, cold_envelope, cold_budget) = fixture.entity_invocation("cold", "cold");
    let cold_host = tokio::time::timeout(WATCHDOG, cold.admit(&cold_envelope, &cold_budget))
        .await
        .unwrap()
        .unwrap();
    retire(
        &fixture,
        &cold,
        Some(&cold_host),
        &cold_envelope,
        &cold_budget,
    )
    .await;
    retire(&fixture, &refused, None, &refused_envelope, &refused_budget).await;
    waiting.abort();
    assert!(matches!(waiting.await, Err(error) if error.is_cancelled()));
    retire(&fixture, &second, None, &second_envelope, &second_budget).await;
    retire(
        &fixture,
        &first,
        Some(&first_host),
        &first_envelope,
        &first_budget,
    )
    .await;
    assert_eq!(
        fixture.owners.entity_snapshot().unwrap(),
        Default::default()
    );
    drop((first_host, cold_host, first, second, refused, cold));
    fixture.shutdown().await;
}

#[tokio::test]
async fn duplicate_claims_replay_without_an_entity_queue_or_second_host() {
    let mut fixture = Fixture::new().await;
    fixture.configure_entities(&["hot"], default_entity_limits());
    let (first, first_envelope, first_budget) = fixture.entity_invocation("same", "hot");
    let first_host = first.admit(&first_envelope, &first_budget).await.unwrap();
    let before = fixture.owners.entity_snapshot().unwrap();
    let (duplicate, duplicate_envelope, duplicate_budget) =
        fixture.entity_invocation("same", "hot");
    assert!(matches!(
        duplicate
            .admit(&duplicate_envelope, &duplicate_budget)
            .await,
        Err(PlatformError {
            code: PlatformErrorCode::AlreadyExists,
            ..
        })
    ));
    assert_eq!(fixture.owners.entity_snapshot().unwrap(), before);
    assert!(matches!(
        duplicate.take_result().unwrap(),
        Some(TransactionAdmissionResult::Existing { .. })
    ));
    retire(
        &fixture,
        &first,
        Some(&first_host),
        &first_envelope,
        &first_budget,
    )
    .await;
    assert_eq!(
        fixture.owners.entity_snapshot().unwrap(),
        Default::default()
    );
    drop((first_host, first, duplicate));
    fixture.shutdown().await;
}

#[tokio::test]
async fn unapproved_entity_and_transactional_child_refuse_before_durable_pending() {
    let mut fixture = Fixture::new().await;
    fixture.configure_entities(&["approved"], default_entity_limits());
    let (unapproved, envelope, budget) = fixture.entity_invocation("unapproved", "unapproved");
    assert!(matches!(
        unapproved.admit(&envelope, &budget).await,
        Err(PlatformError {
            code: PlatformErrorCode::PermissionDenied,
            ..
        })
    ));
    let (child, mut envelope, budget) = fixture.entity_invocation("child", "approved");
    envelope.parent_activation_id = Some(latent_core::ActivationId("existing-parent".into()));
    assert!(matches!(
        child.admit(&envelope, &budget).await,
        Err(PlatformError {
            code: PlatformErrorCode::PermissionDenied,
            ..
        })
    ));
    assert_eq!(fixture.rows(Family::Command).await, 0);
    assert_eq!(
        fixture.owners.entity_snapshot().unwrap(),
        Default::default()
    );
    drop((unapproved, child));
    fixture.shutdown().await;
}

#[tokio::test]
async fn completed_cold_entity_churn_returns_all_live_lane_metadata_to_zero() {
    let mut fixture = Fixture::new().await;
    fixture.configure_entities(&["one", "two", "three", "four"], default_entity_limits());
    for entity in ["one", "two", "three", "four"] {
        let (admission, envelope, budget) = fixture.entity_invocation(entity, entity);
        let host = admission.admit(&envelope, &budget).await.unwrap();
        assert_eq!(fixture.owners.entity_snapshot().unwrap().keys, 1);
        retire(&fixture, &admission, Some(&host), &envelope, &budget).await;
        assert_eq!(
            fixture.owners.entity_snapshot().unwrap(),
            Default::default()
        );
        drop((host, admission));
    }
    fixture.shutdown().await;
}

#[test]
fn installed_entity_limit_configuration_refuses_zero_unbounded_and_incoherent_values() {
    for changed in 0..5 {
        let mut limits = default_entity_limits();
        match changed {
            0 => limits.global_queued = 0,
            1 => limits.global_keys = usize::MAX,
            2 => limits.entity_queued = limits.tenant_queued + 1,
            3 => limits.entity_bytes = limits.tenant_bytes + 1,
            _ => limits.maximum_wait_age = Duration::MAX,
        }
        assert!(matches!(
            crate::transaction_runtime::entity::EntityAdmission::new(limits),
            Err(PlatformError {
                code: PlatformErrorCode::InvalidArgument,
                ..
            })
        ));
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn detached_real_native_worker_retains_lane_after_original_host_cleanup_until_actual_return()
{
    let mut fixture = Fixture::new().await;
    fixture.configure_entities(&["hot"], default_entity_limits());
    let (first, first_envelope, first_budget) = fixture.entity_invocation("first", "hot");
    first.admit(&first_envelope, &first_budget).await.unwrap();
    let TransactionAdmissionResult::Command { claim, host } = first.take_result().unwrap().unwrap()
    else {
        panic!("original actual claim and host required");
    };
    let (entered, entered_waiter) = tokio::sync::oneshot::channel();
    let (release, release_waiter) = std::sync::mpsc::channel();
    let physical = fixture.pause_entity_worker(Arc::clone(&host), entered, release_waiter);
    tokio::time::timeout(WATCHDOG, entered_waiter)
        .await
        .unwrap()
        .unwrap();
    drop(physical); // result observation detaches; the actual worker stays accepted
    host.finish_guest_access();
    let _ = first_budget.finalize_at(None, std::time::Instant::now());
    let disposition = CommandCompletion::new(
        claim,
        Arc::clone(&host),
        fixture.effects.clone(),
        fixture.time.clone(),
        fixture.commit_control(&first_envelope, &first_budget),
    )
    .unwrap()
    .finish(unstarted_failure())
    .await;
    assert!(matches!(
        disposition,
        CommandCompletionDisposition::Retired { .. }
    ));
    host.release_entity().unwrap(); // same positive cleanup boundary as the fixed completion driver
    assert_eq!(fixture.owners.entity_snapshot().unwrap().active, 1);
    let (second, second_envelope, second_budget) = fixture.entity_invocation("second", "hot");
    let worker = Arc::clone(&second);
    let envelope = second_envelope.clone();
    let budget = second_budget.clone();
    let waiting = tokio::spawn(async move { worker.admit(&envelope, &budget).await });
    queued(&fixture, 1).await;
    assert!(!waiting.is_finished());
    release.send(()).unwrap();
    let second_host = tokio::time::timeout(WATCHDOG, waiting)
        .await
        .unwrap()
        .unwrap()
        .unwrap();
    retire(
        &fixture,
        &second,
        Some(&second_host),
        &second_envelope,
        &second_budget,
    )
    .await;
    assert_eq!(
        fixture.owners.entity_snapshot().unwrap(),
        Default::default()
    );
    drop((host, second_host, disposition, first, second));
    fixture.shutdown().await;
}
