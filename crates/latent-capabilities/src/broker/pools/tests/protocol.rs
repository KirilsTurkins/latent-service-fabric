use super::*;

#[tokio::test]
async fn queued_scope_checks_policy_after_waiting_and_does_not_close_the_store() {
    let setup = Setup::new(single());
    let (first, _first_control) = setup.session("running-before-change");
    let running = setup.call(&first).await;
    let (session, _control) = setup.session("queued-before-change");
    let observer = session.observer();
    let mut waiting = Box::pin(setup.pools.admit(&setup.client, &session).unwrap().wait());
    pending(waiting.as_mut());
    setup.fixture.revoke_policy();
    drop(running);
    let ready = waiting.await.unwrap();
    assert!(ready
        .dispatch(CAP, "read", resource(), &[], CapabilityCallCost::new(128))
        .await
        .is_err());
    assert!(!observer.is_closed());
    assert_eq!(observer.retained_handles(), 0);
    assert_eq!(setup.pools.snapshot().unwrap().running_requests, 0);
    drop((first, session));
    clean(&setup.pools).await;
}

#[tokio::test]
async fn retained_queue_scope_cannot_reopen_a_dropped_store() {
    let setup = Setup::new(single());
    let (session, _control) = setup.session("closed-ready");
    let observer = session.observer();
    let ready = setup
        .pools
        .admit(&setup.client, &session)
        .unwrap()
        .wait()
        .await
        .unwrap();
    drop(session);
    assert!(observer.is_closed());
    assert!(ready
        .dispatch(CAP, "read", resource(), &[], CapabilityCallCost::new(128))
        .await
        .is_err());
    assert!(observer.is_quiescent());
    clean(&setup.pools).await;
}

#[tokio::test]
async fn followup_keeps_the_original_deadline_and_can_progress_with_one_running_slot() {
    let setup = Setup::new(single());
    let (session, _control) = setup.session("redirect-scope");
    let observer = session.observer();
    let deadline = Instant::now() + Duration::from_secs(1);
    let ready = setup
        .pools
        .admit_until(&setup.client, &session, deadline)
        .unwrap()
        .wait()
        .await
        .unwrap();
    let first = ready
        .dispatch(CAP, "read", resource(), &[], CapabilityCallCost::new(128))
        .await
        .unwrap();
    assert_eq!(first.io().deadline(), deadline);
    assert!(!observer.is_closed());
    let followup = setup.pools.admit_followup(&setup.client, &first).unwrap();
    drop(first);
    let next = followup
        .wait()
        .await
        .unwrap()
        .dispatch(CAP, "read", resource(), &[], CapabilityCallCost::new(128))
        .await
        .unwrap();
    assert_eq!(next.io().deadline(), deadline);
    drop(next);
    drop(session);
    assert!(observer.is_quiescent());
    clean(&setup.pools).await;
}

#[tokio::test]
async fn narrowed_timeout_cannot_be_refreshed_after_queueing() {
    let setup = Setup::new(single());
    let (session, _control) = setup.session("short-queue");
    assert!(setup
        .pools
        .admit_until(
            &setup.client,
            &session,
            session.deadline().unwrap() + Duration::from_secs(1)
        )
        .is_err());
    match setup
        .pools
        .admit_until(&setup.client, &session, Instant::now())
    {
        Ok(waiting) => assert!(waiting.wait().await.is_err()),
        Err(error) => assert_eq!(error.code, latent_core::PlatformErrorCode::DeadlineExceeded),
    }
    assert_eq!(setup.pools.snapshot().unwrap().pending_requests, 0);
    drop(session);
    clean(&setup.pools).await;
}

#[tokio::test]
async fn protocol_metadata_reserves_before_work_and_survives_provider_retirement() {
    let setup = Setup::new(ProviderPoolLimits::default());
    let before = setup.pools.snapshot().unwrap().metadata_bytes;
    let owned = setup.pools.reserve_protocol_metadata(8192).unwrap();
    assert_eq!(
        setup.pools.snapshot().unwrap().metadata_bytes,
        before + 8192
    );
    assert!(setup.pools.reserve_protocol_metadata(usize::MAX).is_err());
    setup.pools.retire();
    assert!(setup.pools.reserve_protocol_metadata(1).is_err());
    let retained = setup.pools.snapshot().unwrap().metadata_bytes;
    drop(owned);
    assert_eq!(
        setup.pools.snapshot().unwrap().metadata_bytes,
        retained - 8192
    );
    clean(&setup.pools).await;
}

// Only these new native-memory controls select the actual Phase 3 accounting
// profile. Keep the original legacy Setup and all five existing controls exact.
fn kernel_session(setup: &Setup, id: &str) -> (CapabilitySession, Control) {
    use crate::broker::CapabilityBindingSpec;
    use latent_core::{ActivationBudget, BudgetProfile, ClockSample, EffectiveActivationBudget};

    let (request, mut control) = setup.fixture.request(id);
    let original = control.budget.deadline();
    let sample = ClockSample::new(
        original.admitted_at_unix_millis(),
        original.admitted_at_monotonic(),
    );
    control.budget = ActivationBudget::with_profile(
        EffectiveActivationBudget::admit_profile_at(
            BudgetProfile::Phase3,
            &request.budget,
            &request.budget,
            &request.budget,
            request.activation.deadline_unix_millis,
            sample,
        )
        .unwrap(),
        BudgetProfile::Phase3,
    )
    .unwrap();
    assert_eq!(
        control.budget.deadline().unix_millis(),
        request.activation.deadline_unix_millis
    );
    let plan = setup
        .fixture
        .broker
        .compile_plan(
            &setup.fixture.revision,
            &[CapabilityBindingSpec {
                definition_digest: None,
                provider: &setup.provider.reference(),
                imported_operations: &["read".into()],
                policy_ids: &["p".into()],
                provider_binding_id: "binding",
                deployment_restriction_json: br#"{"operations":[]}"#,
            }],
            &setup.fixture.publication,
            Instant::now() + Duration::from_secs(1),
        )
        .unwrap();
    let session = setup
        .fixture
        .broker
        .open_session(plan, &request, &control, &setup.fixture.publication)
        .unwrap();
    (session, control)
}

#[tokio::test]
async fn kernel_occupancy_retains_original_io_request_scope_and_memory() {
    let setup = Setup::new(single());
    let (session, control) = kernel_session(&setup, "kernel-original-owner");
    let observer = session.observer();
    // The dispatched Work additionally owns its prepaid closed handle row.
    let before_call = control.budget.host_memory_bytes();
    let call = setup.call(&session).await;
    let scope = Arc::new(session.reserve_stream().unwrap());
    let (request, _) = setup.fixture.request("kernel-original-owner");
    let (core_payload, _) = crate::broker::session::native_backing::payload_bytes(
        &request,
        &session.core.plan.target.tenant.0,
        setup.fixture.broker.limits().maximum_handles_per_session,
    )
    .unwrap();
    let before = control.budget.host_memory_bytes();
    assert!(before > before_call);
    let mut original = call
        .reserve_stream_kernel_ownership(&scope, 98_304)
        .unwrap();
    original.confirm();
    drop((call, scope, session));
    assert_eq!(setup.pools.snapshot().unwrap().running_requests, 1);
    assert_eq!(control.budget.host_memory_bytes(), before + 98_304);
    assert!(!observer.is_quiescent());
    drop(original);
    // Final I/O retirement destroys both Work's handle row and Core payload.
    assert_eq!(control.budget.host_memory_bytes(), before_call - core_payload);
    assert_eq!(control.budget.outstanding_reservations(), 3);
    assert!(observer.is_quiescent());
    drop(observer);
    clean(&setup.pools).await;
    drop(setup);
    assert_eq!(control.budget.host_memory_bytes(), 0);
    assert_eq!(control.budget.outstanding_reservations(), 0);
}

#[tokio::test]
async fn kernel_occupancy_rejects_foreign_scope_and_nonoriginal_allowance() {
    let setup = Setup::new(ProviderPoolLimits::default());
    let (session, control) = kernel_session(&setup, "kernel-scope-original");
    let (foreign, foreign_control) = kernel_session(&setup, "kernel-scope-foreign");
    let call = setup.call(&session).await;
    let scope = Arc::new(session.reserve_stream().unwrap());
    let foreign_scope = Arc::new(foreign.reserve_stream().unwrap());
    let before = control.budget.host_memory_bytes();
    let foreign_before = foreign_control.budget.host_memory_bytes();
    assert!(call
        .reserve_stream_kernel_ownership(&foreign_scope, 65_536)
        .is_err());
    for bytes in [0, 1, 65_535, 65_537, 98_303, 98_305, u64::MAX] {
        assert!(call.reserve_stream_kernel_ownership(&scope, bytes).is_err());
    }
    assert_eq!(control.budget.host_memory_bytes(), before);
    assert_eq!(foreign_control.budget.host_memory_bytes(), foreign_before);
    drop((call, scope, foreign_scope, session, foreign));
    clean(&setup.pools).await;
}

#[tokio::test]
async fn stopped_kernel_occupancy_fails_checkpoint_without_refunding_owner() {
    let setup = Setup::new(single());
    let (session, control) = kernel_session(&setup, "kernel-owner-stopped");
    // The dispatched Work additionally owns its prepaid closed handle row.
    let before_call = control.budget.host_memory_bytes();
    let call = setup.call(&session).await;
    let scope = Arc::new(session.reserve_stream().unwrap());
    let before = control.budget.host_memory_bytes();
    assert!(before > before_call);
    let owner = call
        .reserve_stream_kernel_ownership(&scope, 65_536)
        .unwrap();
    call.io().stop_handle().stop();
    assert!(owner.checkpoint().is_err());
    drop((call, scope));
    assert_eq!(setup.pools.snapshot().unwrap().running_requests, 1);
    assert_eq!(control.budget.host_memory_bytes(), before + 65_536);
    drop(owner);
    // Session remains live; the completed Work's handle storage has retired.
    assert_eq!(control.budget.host_memory_bytes(), before_call);
    drop(session);
    clean(&setup.pools).await;
}

#[tokio::test]
async fn kernel_backing_uses_existing_fixed_metadata_ceiling() {
    let setup = Setup::new(ProviderPoolLimits::default());
    let before = setup.pools.snapshot().unwrap().metadata_bytes;
    let backing = setup.pools.reserve_stream_kernel_backing().unwrap();
    assert_eq!(
        setup.pools.snapshot().unwrap().metadata_bytes,
        before + 1024 * 1024
    );
    setup.pools.retire();
    assert!(setup.pools.reserve_stream_kernel_backing().is_err());
    assert_eq!(
        setup.pools.snapshot().unwrap().metadata_bytes,
        before + 1024 * 1024
    );
    // No kernel was entered by this test. This is destruction of an unentered
    // reservation, not evidence that descriptor close frees kernel backing.
    drop(backing);
    assert_eq!(setup.pools.snapshot().unwrap().metadata_bytes, before);
    clean(&setup.pools).await;
}
