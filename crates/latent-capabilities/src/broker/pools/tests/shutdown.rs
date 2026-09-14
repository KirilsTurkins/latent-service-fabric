use super::*;

#[tokio::test]
async fn dropping_job_waiter_stops_but_does_not_refund_a_blocked_worker() {
    let setup = Setup::new(single());
    let (session, _control) = setup.session("job-waiter");
    let observer = session.observer();
    let call = setup.call(&session).await;
    let waiter = call.io().job_waiter();
    let (entered, started) = tokio::sync::oneshot::channel();
    let (release, blocked) = std::sync::mpsc::sync_channel(1);
    let job = setup
        .pools
        .spawn_blocking(call, move |call| {
            entered.send(()).unwrap();
            blocked.recv_timeout(Duration::from_secs(2)).unwrap();
            assert!(call.io().checkpoint().is_err());
            drop(call);
        })
        .unwrap();
    started.await.unwrap();
    let mut response = Box::pin(waiter.wait(job.wait()));
    pending(response.as_mut());
    drop(response);
    drop(session);
    let retained = setup
        .pools
        .shutdown(Instant::now() + Duration::from_millis(30))
        .await
        .unwrap();
    assert_eq!(retained.workers, 1);
    assert_eq!(retained.running_requests, 1);
    assert!(!retained.is_clean());
    assert!(!observer.is_quiescent());
    release.send(()).unwrap();
    clean(&setup.pools).await;
    assert!(observer.is_quiescent());
}

#[tokio::test]
async fn delayed_result_consumers_keep_pool_capacity_and_the_original_session() {
    let setup = Setup::new(single());
    let (session, _control) = setup.session("retained-result");
    let observer = session.observer();
    let call = setup.call(&session).await;
    let mut buffer = call.io().buffer(32, 16).unwrap();
    buffer.spare_mut().unwrap()[0] = 42;
    buffer.advance_written(1).unwrap();
    let buffer = buffer.retain().unwrap();
    drop(call);
    drop(session);
    assert_eq!(setup.pools.snapshot().unwrap().running_requests, 1);
    assert!(!observer.is_quiescent());
    assert_eq!(buffer.bytes(), &[42]);
    drop(buffer);
    assert_eq!(setup.pools.snapshot().unwrap().running_requests, 0);
    assert!(observer.is_quiescent());
    clean(&setup.pools).await;
}

#[tokio::test]
async fn control_owner_failure_denies_work_and_cannot_report_clean_shutdown() {
    let setup = Setup::new(ProviderPoolLimits::default());
    setup
        .pools
        .inner
        .control
        .owner_task
        .lock()
        .unwrap()
        .as_ref()
        .unwrap()
        .abort();
    tokio::task::yield_now().await;
    let report = setup
        .pools
        .shutdown(Instant::now() + Duration::from_secs(1))
        .await
        .unwrap();
    assert!(report.control_failed);
    assert!(!report.is_clean());
    assert!(setup.pools.provider("secrets").is_err());
}

#[tokio::test]
async fn cancelled_blocking_job_stays_charged_until_socket_close_and_real_join() {
    let setup = Setup::new(ProviderPoolLimits {
        maximum_workers: 1,
        maximum_cleanup_jobs: 1,
        ..ProviderPoolLimits::default()
    });
    let (session, control) = setup.session("blocking");
    let observer = session.observer();
    let call = setup.call(&session).await;
    let (connection, mut peer) = connect(&setup.client, &call);
    let (cleanup, mut cleanup_peer) = connect(&setup.client, &call);
    let (entered, started) = tokio::sync::oneshot::channel();
    let (release, blocked) = std::sync::mpsc::sync_channel(1);
    let job = setup
        .pools
        .spawn_blocking(call, move |call| {
            entered.send(()).unwrap();
            blocked.recv_timeout(Duration::from_secs(2)).unwrap();
            assert!(call.io().checkpoint().is_err());
            drop(connection);
            drop(call);
        })
        .unwrap();
    started.await.unwrap();
    let (other, _other_control) = setup.session("worker-full");
    let other_call = setup.call(&other).await;
    assert!(setup
        .pools
        .spawn_blocking(other_call, |_| panic!("over-capacity work started"))
        .is_err());
    // Cleanup has reserved capacity even with the only blocking worker occupied.
    let result = setup
        .pools
        .cleanup(cleanup, |_| Box::pin(async { true }))
        .unwrap()
        .wait()
        .await
        .unwrap();
    assert!(matches!(result, CleanupResult::Closed));
    assert_eq!(cleanup_peer.read(&mut [0]).unwrap(), 0);
    control.probe.0.store(true, Ordering::Release);
    drop(job);
    drop((session, other));
    let retained = setup
        .pools
        .shutdown(Instant::now() + Duration::from_millis(30))
        .await
        .unwrap();
    assert_eq!(retained.workers, 1);
    assert_eq!(retained.connections, 1);
    assert_eq!(retained.running_requests, 1);
    assert_eq!(retained.control_owners, 1);
    assert!(!observer.is_quiescent());
    release.send(()).unwrap();
    clean(&setup.pools).await;
    assert!(observer.is_quiescent());
    assert_eq!(peer.read(&mut [0]).unwrap(), 0);
}

#[tokio::test]
async fn failed_cleanup_keeps_physical_owner_until_explicit_recovery_or_drop() {
    let setup = Setup::new(ProviderPoolLimits::default());
    let (session, _control) = setup.session("failed-cleanup");
    let observer = session.observer();
    let call = setup.call(&session).await;
    let (connection, mut peer) = connect(&setup.client, &call);
    let result = setup
        .pools
        .cleanup(connection, |_| Box::pin(async { false }))
        .unwrap()
        .wait()
        .await
        .unwrap();
    let CleanupResult::Retained(connection) = result else {
        panic!("failed close lost ownership")
    };
    drop(call);
    drop(session);
    let report = setup.pools.snapshot().unwrap();
    assert_eq!(report.connections, 1);
    assert_eq!(report.failed_cleanup, 1);
    assert_eq!(report.running_requests, 1);
    assert!(!observer.is_quiescent());
    assert!(peer.read(&mut [0]).is_err());
    let result = setup
        .pools
        .cleanup(connection, |_| Box::pin(async { true }))
        .unwrap()
        .wait()
        .await
        .unwrap();
    assert!(matches!(result, CleanupResult::Closed));
    assert_eq!(peer.read(&mut [0]).unwrap(), 0);
    assert_eq!(setup.pools.snapshot().unwrap().failed_cleanup, 0);
    assert!(observer.is_quiescent());
    clean(&setup.pools).await;
}

#[tokio::test]
async fn delayed_cleanup_and_dropped_waiter_do_not_refund_the_provider() {
    let setup = Setup::new(ProviderPoolLimits {
        maximum_cleanup_jobs: 1,
        ..ProviderPoolLimits::default()
    });
    let (session, _control) = setup.session("delayed-close");
    let call = setup.call(&session).await;
    let (connection, mut peer) = connect(&setup.client, &call);
    let (release, blocked) = tokio::sync::oneshot::channel();
    let job = setup
        .pools
        .cleanup(connection, move |_| {
            Box::pin(async move {
                blocked.await.unwrap();
                true
            })
        })
        .unwrap();
    drop(job);
    drop(call);
    drop(session);
    let retained = setup
        .pools
        .shutdown(Instant::now() + Duration::from_millis(30))
        .await
        .unwrap();
    assert_eq!(retained.cleanup_jobs, 1);
    assert_eq!(retained.connections, 1);
    release.send(()).unwrap();
    clean(&setup.pools).await;
    assert_eq!(peer.read(&mut [0]).unwrap(), 0);
}

#[tokio::test]
async fn provider_panic_drops_actual_owners_without_stopping_the_control_owner() {
    let setup = Setup::new(ProviderPoolLimits::default());
    let (session, _control) = setup.session("provider-panic");
    let call = setup.call(&session).await;
    let (connection, mut peer) = connect(&setup.client, &call);
    let job: ProviderJob<()> = setup
        .pools
        .spawn(call, move |call| async move {
            let _call = call;
            let _connection = connection;
            panic!("synthetic provider failure");
        })
        .unwrap();
    assert!(job.wait().await.is_err());
    assert_eq!(peer.read(&mut [0]).unwrap(), 0);
    drop(session);
    clean(&setup.pools).await;
}
