use super::*;
use latent_core::native_capacity::NativeCapacityLimits;

fn one_slot() -> NativeCapacityLimits {
    let mut limits = NativeCapacityLimits::default();
    limits.ordinary.slots = 1;
    limits
}

#[tokio::test]
async fn ingress_prepayment_transfers_one_original_slot_through_query_and_response() {
    let fixture = Fixture::with_native_limits(one_slot()).await;
    let native = fixture
        .owners
        .reserve_ingress(
            512,
            std::time::Instant::now() + std::time::Duration::from_secs(10),
        )
        .unwrap();
    assert_eq!(fixture.native.snapshot().unwrap().ordinary.slots, 1);
    let (admission, envelope, budget) = fixture.prepaid_invocation(true, "prepaid-query", native);
    // A second independent reservation would fail this actual native snapshot.
    let guest = admission.admit(&envelope, &budget).await.unwrap();
    guest.acquire(Mode::Query).unwrap();
    guest.finish_guest_access();
    let _ = budget.finalize_at(None, std::time::Instant::now());
    assert!(matches!(
        admission
            .complete(
                success(b"prepaid result"),
                fixture.commit_control(&envelope, &budget),
            )
            .await,
        ActivationOutcome::Succeeded(_)
    ));
    let response = admission.take_owned_completion().unwrap().unwrap();
    response.authority.with_current(&mut || ()).unwrap();
    drop((guest, admission));
    assert_eq!(fixture.native.snapshot().unwrap().ordinary.slots, 1);
    assert_eq!(fixture.rows(Family::Command).await, 0);
    assert_eq!(fixture.rows(Family::Result).await, 0);
    drop(response);
    assert!(fixture.native.snapshot().unwrap().physically_retired());
    fixture.shutdown().await;
}

#[tokio::test]
async fn unpolled_ingress_drop_retires_without_native_submission_or_pending() {
    let fixture = Fixture::with_native_limits(one_slot()).await;
    let native = fixture
        .owners
        .reserve_ingress(
            512,
            std::time::Instant::now() + std::time::Duration::from_secs(10),
        )
        .unwrap();
    let (admission, _, _) = fixture.prepaid_invocation(false, "unpolled-ingress", native);
    assert_eq!(fixture.native.snapshot().unwrap().ordinary.slots, 1);
    drop(admission);
    assert!(fixture.native.snapshot().unwrap().physically_retired());
    assert_eq!(fixture.rows(Family::Command).await, 0);
    fixture.shutdown().await;
}

#[tokio::test]
async fn foreign_recovery_and_underfunded_ingress_cannot_open_native_or_command_rows() {
    use latent_core::native_capacity::{
        NativeAdmissionClass as Class, NativeCapacityOwner, NativeReservationRequest as Request,
    };
    let fixture = Fixture::new().await;
    let foreign = NativeCapacityOwner::new(NativeCapacityLimits::default()).unwrap();
    let take_selection = || TransactionSelection {
        namespace: "orders".into(),
        incarnation: 1,
        entity: None,
        operation: "update".into(),
        mode: latent_manifest::TransactionOperationMode::StrictCommand,
        client_key: Some("wrong-ingress".into()),
        expected_versions: Vec::new(),
        minimum_view_version: None,
        input_format: "raw-v1".into(),
        retry: None,
    };
    let deadline = std::time::Instant::now() + std::time::Duration::from_secs(10);
    let complete = Request {
        request_bytes: 2 * 1024 * 1024,
        work_bytes: 48 * 1024 * 1024,
        response_bytes: 8 * 1024 * 1024 + 16 * 1024,
    };
    let native = foreign
        .reserve(Class::Ordinary, complete, deadline)
        .unwrap();
    assert!(NativeTransactionAdmission::with_ingress_reservation(
        Arc::clone(&fixture.owners),
        Arc::clone(&fixture.installation),
        take_selection(),
        native,
    )
    .is_err());
    let small = Request {
        request_bytes: 4096,
        work_bytes: 4096,
        response_bytes: 4096,
    };
    for class in [Class::Recovery, Class::Ordinary] {
        let native = fixture.native.reserve(class, small, deadline).unwrap();
        assert!(NativeTransactionAdmission::with_ingress_reservation(
            Arc::clone(&fixture.owners),
            Arc::clone(&fixture.installation),
            take_selection(),
            native,
        )
        .is_err());
    }
    assert!(fixture.native.snapshot().unwrap().physically_retired());
    assert!(foreign.snapshot().unwrap().physically_retired());
    assert_eq!(fixture.rows(Family::Command).await, 0);
    assert_eq!(fixture.rows(Family::State).await, 0);
    fixture.shutdown().await;
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
