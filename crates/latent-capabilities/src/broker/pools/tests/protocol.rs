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
