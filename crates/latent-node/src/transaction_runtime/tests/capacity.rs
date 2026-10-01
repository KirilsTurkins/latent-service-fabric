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
    let guest = admission.admit(&envelope, &budget).await.unwrap();
    let TransactionAdmissionResult::Query { host } = admission.take_result().unwrap().unwrap()
    else {
        panic!("query host absent");
    };
    host.acquire(Mode::Query).unwrap();
    host.finish_guest_access();
    let _ = budget.finalize_at(None, std::time::Instant::now());
    drop((guest, admission));
    assert_eq!(fixture.native.snapshot().unwrap().ordinary.slots, 1);

    let (blocked, request, allowance) = fixture.invocation(false, "blocked-command");
    let error = blocked.admit(&request, &allowance).await.err().unwrap();
    assert_eq!(
        error.code,
        latent_core::PlatformErrorCode::ResourceExhausted
    );
    assert!(blocked.take_result().unwrap().is_none());
    assert_eq!(fixture.rows(Family::Command).await, 0);
    host.retire().await.unwrap();
    // A real response/host owner still owns its prepaid allowance after view
    // retirement. Ledger freeze and waiter loss cannot release that allowance.
    assert_eq!(fixture.native.snapshot().unwrap().ordinary.slots, 1);
    drop(host);
    assert!(fixture.native.snapshot().unwrap().physically_retired());

    let (fresh, request, allowance) = fixture.invocation(true, "fresh-query");
    let guest = fresh.admit(&request, &allowance).await.unwrap();
    let TransactionAdmissionResult::Query { host } = fresh.take_result().unwrap().unwrap() else {
        panic!("fresh query absent");
    };
    host.finish_guest_access();
    host.retire().await.unwrap();
    drop((guest, host, fresh));
    assert!(fixture.native.snapshot().unwrap().physically_retired());
    fixture.shutdown().await;
}

#[tokio::test]
async fn global_close_before_original_commit_cas_discards_business_mutations() {
    let fixture = Fixture::new().await;
    let (admission, envelope, budget) = fixture.invocation(false, "native-close");
    let guest = admission.admit(&envelope, &budget).await.unwrap();
    guest.acquire(Mode::Command).unwrap();
    guest
        .put(b"counter".to_vec(), value(b"never committed"))
        .await
        .unwrap();
    guest.finish_guest_access();
    let _ = budget.finalize_at(None, std::time::Instant::now());
    fixture.native.close_ordinary();
    let observation = admission
        .complete(
            success(b"never released"),
            fixture.commit_control(&envelope, &budget),
        )
        .await;
    assert!(matches!(observation, ActivationOutcome::Failed { .. }));
    assert!(matches!(
        admission.take_completion().unwrap(),
        Some(TransactionCompletionResult::Command(
            CommandCompletionDisposition::Retired { .. }
        ))
    ));
    assert_eq!(fixture.rows(Family::State).await, 0);
    assert_eq!(fixture.rows(Family::Outbox).await, 0);
    assert_eq!(fixture.rows(Family::Command).await, 1);
    drop((guest, admission));
    assert!(fixture.native.snapshot().unwrap().physically_retired());
    fixture.shutdown().await;
}

#[tokio::test]
async fn durable_response_owner_retains_global_slot_after_native_view_and_admission_retire() {
    let fixture = Fixture::with_native_limits(one_slot()).await;
    let (admission, envelope, budget) = fixture.invocation(false, "response-owner");
    let guest = admission.admit(&envelope, &budget).await.unwrap();
    guest.acquire(Mode::Command).unwrap();
    guest.finish_guest_access();
    let _ = budget.finalize_at(None, std::time::Instant::now());
    let outcome = admission
        .complete(
            success(b"owned response"),
            fixture.commit_control(&envelope, &budget),
        )
        .await;
    assert!(matches!(outcome, ActivationOutcome::Succeeded(_)));
    let response = admission.take_completion().unwrap().unwrap();
    assert!(matches!(
        response,
        TransactionCompletionResult::Command(CommandCompletionDisposition::Durable { .. })
    ));
    drop((guest, admission));
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
    drop(response);
    assert!(fixture.native.snapshot().unwrap().physically_retired());
    fixture.shutdown().await;
}
