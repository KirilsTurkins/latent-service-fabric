use super::*;
use latent_core::PlatformErrorCode;

#[tokio::test]
async fn guest_worker_admission_waits_for_maintenance_without_replaying_work() {
    let setup = Setup::new(single());
    let (session, _control) = setup.session("worker-maintenance");
    let call = setup.call(&session).await;
    let executions = Arc::new(AtomicUsize::new(0));
    let observed = executions.clone();
    let mut admission = Box::pin(setup.pools.spawn_blocking_wait(call, move |call| {
        call.io().checkpoint().unwrap();
        observed.fetch_add(1, Ordering::AcqRel)
    }));
    {
        let _maintenance = setup.pools.inner.control.tasks.lock().unwrap();
        pending(admission.as_mut());
        assert_eq!(executions.load(Ordering::Acquire), 0);
        assert_eq!(setup.pools.inner.quotas.use_of(Kind::Worker), 0);
        assert_eq!(setup.pools.snapshot().unwrap().running_requests, 1);
    }
    assert_eq!(admission.await.unwrap().wait().await.unwrap(), 0);
    assert_eq!(executions.load(Ordering::Acquire), 1);
    drop(session);
    clean(&setup.pools).await;
}

#[tokio::test]
async fn cancelled_guest_admission_never_starts_physical_work() {
    let setup = Setup::new(single());
    let (session, control) = setup.session("worker-cancel");
    let observer = session.observer();
    let call = setup.call(&session).await;
    let owner = Arc::new(());
    let retained = Arc::downgrade(&owner);
    let mut admission = Box::pin(setup.pools.spawn_blocking_wait(call, move |_| {
        drop(owner);
        panic!("cancelled or abandoned admission must not start work")
    }));
    {
        let _maintenance = setup.pools.inner.control.tasks.lock().unwrap();
        pending(admission.as_mut());
        assert!(retained.upgrade().is_some());
        control.probe.0.store(true, Ordering::Release);
    }
    assert_eq!(
        admission.await.err().unwrap().code,
        PlatformErrorCode::Cancelled
    );
    drop(session);
    assert!(retained.upgrade().is_none());
    assert!(observer.is_quiescent());
    clean(&setup.pools).await;
}

#[tokio::test]
async fn abandoned_guest_admission_releases_its_call_without_spawning_work() {
    let setup = Setup::new(single());
    let (session, _control) = setup.session("worker-abandon");
    let observer = session.observer();
    let call = setup.call(&session).await;
    let owner = Arc::new(());
    let retained = Arc::downgrade(&owner);
    let mut admission = Box::pin(setup.pools.spawn_blocking_wait(call, move |_| {
        drop(owner);
        panic!("abandoned admission must not start work")
    }));
    {
        let _maintenance = setup.pools.inner.control.tasks.lock().unwrap();
        pending(admission.as_mut());
        assert!(retained.upgrade().is_some());
        drop(admission);
        drop(session);
        assert!(retained.upgrade().is_none());
        assert!(observer.is_quiescent());
    }
    clean(&setup.pools).await;
}

#[tokio::test]
async fn guest_worker_capacity_is_not_retried_or_refunded() {
    let setup = Setup::new(ProviderPoolLimits {
        maximum_workers: 1,
        ..ProviderPoolLimits::default()
    });
    let (session, _control) = setup.session("worker-capacity");
    let call = setup.call(&session).await;
    let charge = setup.pools.inner.quotas.acquire(Kind::Worker, 1).unwrap();
    let failure = setup
        .pools
        .spawn_blocking_wait(call, |_| {
            panic!("capacity rejection must not start physical work")
        })
        .await
        .err()
        .unwrap();
    assert_eq!(failure.code, PlatformErrorCode::ResourceExhausted);
    assert_eq!(setup.pools.inner.quotas.use_of(Kind::Worker), 1);
    drop((charge, session));
    clean(&setup.pools).await;
}

#[tokio::test]
async fn contended_control_slot_retains_one_closure_until_one_admission() {
    let setup = Setup::new(ProviderPoolLimits::default());
    let executions = Arc::new(AtomicUsize::new(0));
    let observed = executions.clone();
    let mut admission = Box::pin(
        setup
            .pools
            .control_blocking_before(Instant::now() + Duration::from_secs(1), move || {
                observed.fetch_add(1, Ordering::AcqRel)
            }),
    );
    {
        let _maintenance = setup.pools.inner.control.tasks.lock().unwrap();
        pending(admission.as_mut());
        assert_eq!(executions.load(Ordering::Acquire), 0);
        assert_eq!(setup.pools.inner.quotas.use_of(Kind::Worker), 0);
    }
    assert_eq!(admission.await.unwrap().wait().await.unwrap(), 0);
    assert_eq!(executions.load(Ordering::Acquire), 1);
    clean(&setup.pools).await;
}

#[tokio::test]
async fn dropping_a_contended_admission_releases_work_without_spawning_it() {
    let setup = Setup::new(ProviderPoolLimits::default());
    let owner = Arc::new(());
    let observed = Arc::downgrade(&owner);
    let mut admission = Box::pin(
        setup
            .pools
            .control_blocking_before(Instant::now() + Duration::from_secs(1), move || drop(owner)),
    );
    {
        let _maintenance = setup.pools.inner.control.tasks.lock().unwrap();
        pending(admission.as_mut());
        assert!(observed.upgrade().is_some());
        drop(admission);
        assert!(observed.upgrade().is_none());
        assert_eq!(setup.pools.inner.quotas.use_of(Kind::Worker), 0);
    }
    clean(&setup.pools).await;
}

#[tokio::test]
async fn original_deadline_prevents_work_before_and_after_contention() {
    let setup = Setup::new(ProviderPoolLimits::default());
    let failure = setup
        .pools
        .control_blocking_before(Instant::now(), || panic!("expired work must not start"))
        .await
        .err()
        .unwrap();
    assert_eq!(failure.code, PlatformErrorCode::DeadlineExceeded);
    let mut admission = Box::pin(
        setup
            .pools
            .control_blocking_before(Instant::now() + Duration::from_millis(3), || {
                panic!("contention must not extend the original deadline")
            }),
    );
    {
        let _maintenance = setup.pools.inner.control.tasks.lock().unwrap();
        pending(admission.as_mut());
        std::thread::sleep(Duration::from_millis(5));
    }
    assert_eq!(
        admission.await.err().unwrap().code,
        PlatformErrorCode::DeadlineExceeded
    );
    assert_eq!(setup.pools.inner.quotas.use_of(Kind::Worker), 0);
    clean(&setup.pools).await;
}

#[tokio::test]
async fn actual_capacity_and_retirement_are_not_retried() {
    let setup = Setup::new(ProviderPoolLimits {
        maximum_workers: 1,
        ..ProviderPoolLimits::default()
    });
    let charge = setup.pools.inner.quotas.acquire(Kind::Worker, 1).unwrap();
    let failure = setup
        .pools
        .control_blocking_before(Instant::now() + Duration::from_secs(1), || {
            panic!("capacity rejection must not start work")
        })
        .await
        .err()
        .unwrap();
    assert_eq!(failure.code, PlatformErrorCode::ResourceExhausted);
    assert_eq!(failure.message, "capability-capacity");
    drop(charge);
    setup.pools.retire();
    let failure = setup
        .pools
        .control_blocking_before(Instant::now() + Duration::from_secs(1), || {
            panic!("retired pools must not start work")
        })
        .await
        .err()
        .unwrap();
    assert_eq!(failure.code, PlatformErrorCode::PermissionDenied);
    clean(&setup.pools).await;
}

#[tokio::test]
async fn poisoned_control_ownership_is_not_treated_as_contention() {
    let setup = Setup::new(ProviderPoolLimits::default());
    let poisoned = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        let _owner = setup.pools.inner.control.tasks.lock().unwrap();
        panic!("controlled owner poison");
    }));
    assert!(poisoned.is_err());
    let failure = setup
        .pools
        .control_blocking_before(Instant::now() + Duration::from_secs(1), || {
            panic!("poisoned owners must not start work")
        })
        .await
        .err()
        .unwrap();
    assert_eq!(failure.code, PlatformErrorCode::Unavailable);
    assert_eq!(failure.message, "provider-control-owner-poisoned");
    assert_eq!(setup.pools.inner.quotas.use_of(Kind::Worker), 0);
    clean(&setup.pools).await;
}

#[tokio::test]
async fn an_accepted_job_outlives_its_waiter_until_physical_completion() {
    let setup = Setup::new(ProviderPoolLimits::default());
    let (entered, started) = tokio::sync::oneshot::channel();
    let (release, blocked) = std::sync::mpsc::sync_channel(1);
    let job = setup
        .pools
        .control_blocking_before(Instant::now() + Duration::from_secs(1), move || {
            entered.send(()).unwrap();
            blocked.recv_timeout(Duration::from_secs(2)).unwrap();
        })
        .await
        .unwrap();
    started.await.unwrap();
    drop(job);
    let retained = setup
        .pools
        .shutdown(Instant::now() + Duration::from_millis(20))
        .await
        .unwrap();
    assert_eq!(retained.workers, 1);
    assert!(!retained.is_clean());
    release.send(()).unwrap();
    clean(&setup.pools).await;
}
