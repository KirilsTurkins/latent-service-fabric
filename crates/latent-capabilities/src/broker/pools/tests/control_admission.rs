use super::*;
use latent_core::PlatformErrorCode;

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
