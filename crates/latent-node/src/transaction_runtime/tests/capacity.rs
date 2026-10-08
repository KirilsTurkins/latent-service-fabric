use super::*;
use latent_core::native_capacity::NativeCapacityLimits;
fn one_slot() -> NativeCapacityLimits {
    let mut limits = NativeCapacityLimits::default();
    limits.ordinary.slots = 1;
    limits
}

#[tokio::test]
async fn frozen_query_and_lost_waiter_retain_original_global_slot_through_real_retirement() {
    let fixture = Fixture::with_native_limits(one_slot()).await;
    let (admission, envelope, budget) = fixture.invocation(true, "first-query");
    let execution = execute(admission.admit(&envelope, &budget).await.unwrap());
    execution.host.acquire(Mode::Query).unwrap();
    execution.host.finish_guest_access();
    let _ = budget.finalize_at(None, std::time::Instant::now());
    let host = execution.host.clone();
    let hook = execution.completion.clone();
    drop((execution, admission));
    assert_eq!(fixture.native.snapshot().unwrap().ordinary.slots, 1);
    let (blocked, request, allowance) = fixture.invocation(false, "blocked-command");
    assert_eq!(
        blocked
            .admit(&request, &allowance)
            .await
            .err()
            .unwrap()
            .code,
        latent_core::PlatformErrorCode::ResourceExhausted
    );
    assert_eq!(fixture.rows(Family::Command).await, 0);
    let retired = hook.complete(success(b"query")).await;
    assert!(
        matches!(retired.outcome(), ActivationOutcome::Succeeded(_)),
        "{retired:?}"
    );
    assert_eq!(fixture.native.snapshot().unwrap().ordinary.slots, 1);
    drop((host, hook, retired, blocked));
    assert!(fixture.native.snapshot().unwrap().physically_retired());
    let (fresh, request, allowance) = fixture.invocation(true, "fresh-query");
    let execution = execute(fresh.admit(&request, &allowance).await.unwrap());
    execution.host.finish_guest_access();
    let completion = execution.completion.complete(success(b"fresh")).await;
    assert!(
        matches!(completion.outcome(), ActivationOutcome::Succeeded(_)),
        "{completion:?}"
    );
    drop((completion, execution, fresh));
    assert!(fixture.native.snapshot().unwrap().physically_retired());
    fixture.shutdown().await;
}

#[tokio::test]
async fn global_close_before_original_commit_cas_discards_business_mutations() {
    let fixture = Fixture::new().await;
    let (admission, envelope, budget) = fixture.invocation(false, "native-close");
    let execution = execute(admission.admit(&envelope, &budget).await.unwrap());
    execution.host.acquire(Mode::Command).unwrap();
    execution
        .host
        .put(b"counter".to_vec(), value(b"never committed"))
        .await
        .unwrap();
    execution.host.finish_guest_access();
    let _ = budget.finalize_at(None, std::time::Instant::now());
    fixture.native.close_ordinary();
    let observation = execution
        .completion
        .complete(success(b"never released"))
        .await;
    assert!(matches!(
        observation.outcome(),
        ActivationOutcome::Failed { .. }
    ));
    assert!(observation.durable_command().is_none());
    assert_eq!(fixture.rows(Family::State).await, 0);
    assert_eq!(fixture.rows(Family::Outbox).await, 0);
    assert_eq!(fixture.rows(Family::Command).await, 1);
    drop((observation, execution, admission));
    assert!(fixture.native.snapshot().unwrap().physically_retired());
    fixture.shutdown().await;
}

#[tokio::test]
async fn durable_response_owner_retains_global_slot_after_native_view_and_admission_retire() {
    let fixture = Fixture::with_native_limits(one_slot()).await;
    let (admission, envelope, budget) = fixture.invocation(false, "response-owner");
    let execution = execute(admission.admit(&envelope, &budget).await.unwrap());
    execution.host.acquire(Mode::Command).unwrap();
    execution.host.finish_guest_access();
    let _ = budget.finalize_at(None, std::time::Instant::now());
    let response = execution
        .completion
        .complete(success(b"owned response"))
        .await;
    assert!(
        matches!(response.outcome(), ActivationOutcome::Succeeded(_)),
        "{response:?}"
    );
    assert_eq!(
        response.durable_command().unwrap().outcome(),
        Outcome::Committed
    );
    assert!(response.delivery_fence().is_some());
    drop((execution, admission));
    assert_eq!(fixture.native.snapshot().unwrap().ordinary.slots, 1);
    let (blocked, request, allowance) = fixture.invocation(true, "response-blocked-query");
    assert_eq!(
        blocked
            .admit(&request, &allowance)
            .await
            .err()
            .unwrap()
            .code,
        latent_core::PlatformErrorCode::ResourceExhausted
    );
    drop((response, blocked));
    assert!(fixture.native.snapshot().unwrap().physically_retired());
    fixture.shutdown().await;
}
