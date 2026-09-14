use super::*;
use std::task::{Context, Poll, Waker};

#[tokio::test]
async fn a_queued_read_selects_current_material_and_rechecks_revocation() {
    use latent_capabilities::broker::pools::ProviderPoolLimits;
    let f = Fixture::configured(
        None,
        ProviderPoolLimits {
            maximum_running_requests: 1,
            maximum_running_per_provider: 1,
            maximum_running_per_tenant: 1,
            ..ProviderPoolLimits::default()
        },
    )
    .await;
    let (first, _) = f.session("occupies-slot");
    let held = f
        .provider
        .read(&first, "allowed".into())
        .unwrap()
        .await
        .unwrap();
    let (second, _) = f.session("queued");
    let mut pending = f.provider.read(&second, "allowed".into()).unwrap();
    assert!(matches!(
        pending
            .as_mut()
            .poll(&mut Context::from_waker(Waker::noop())),
        Poll::Pending
    ));
    write(&f.directory.path().join("secrets/value"), b"Beta");
    f.secrets.reload(1, specs("2")).unwrap().await.unwrap();
    drop(held);
    let value = pending.await.unwrap();
    let mut observed = Vec::new();
    let owner = value
        .disclose(&mut |view| observed.extend_from_slice(view.bytes))
        .unwrap();
    assert_eq!(observed, b"Beta");
    let mut pending = f.provider.read(&second, "allowed".into()).unwrap();
    assert!(matches!(
        pending
            .as_mut()
            .poll(&mut Context::from_waker(Waker::noop())),
        Poll::Pending
    ));
    f.revoke();
    drop(owner);
    assert!(matches!(pending.await, Err(SecretError::PermissionDenied)));
    drop(first);
    drop(second);
    f.idle();
    shutdown(&f).await;
}

#[tokio::test]
async fn actual_guest_waiting_for_a_read_rejects_rotation_and_cancellation() {
    let f = Fixture::new().await;
    for cancel in [false, true] {
        f.gate.armed.store(true, Ordering::Release);
        let (request, control) = f.request("waiting-guest", 0);
        let (report, ()) = tokio::join!(f.backend.invoke_contained(request, &control), async {
            tokio::time::timeout(Duration::from_secs(2), f.gate.entered.notified())
                .await
                .unwrap();
            assert_eq!(f.broker.snapshot().calls, 1);
            if cancel {
                control.probe.0.store(true, Ordering::Release);
            } else {
                f.secrets.reload(1, specs("2")).unwrap().await.unwrap();
            }
            f.gate.released.notify_one();
        });
        if cancel {
            match report.outcome {
                Ok(GuestOutcome::Returned { output, .. }) => assert_eq!(
                    serde_json::from_slice::<Vec<String>>(&output).unwrap(),
                    ["1003"]
                ),
                Ok(GuestOutcome::Interrupted { kind, .. }) => {
                    assert_eq!(kind, latent_executor::GuestInterruptionKind::Cancelled);
                }
                Err(error) => assert_eq!(error.code, latent_core::PlatformErrorCode::Cancelled),
                other => panic!("unexpected cancellation outcome: {other:?}"),
            }
        } else {
            let GuestOutcome::Returned { output, .. } = report.outcome.unwrap() else {
                panic!("typed stale read")
            };
            assert_eq!(
                serde_json::from_slice::<Vec<String>>(&output).unwrap(),
                ["1003"]
            );
        }
        assert_eq!(report.cleanup, ExecutionCleanup::Reusable);
        f.idle();
    }
    shutdown(&f).await;
}

#[tokio::test]
async fn abandoned_reload_does_not_refund_or_commit_its_still_running_worker() {
    let f = Fixture::new().await;
    let (entered, observed) = tokio::sync::oneshot::channel();
    let gate = Arc::new((std::sync::Mutex::new(false), std::sync::Condvar::new()));
    let worker_gate = gate.clone();
    *f.secret_clock.hook.lock().unwrap() = Some(Box::new(move || {
        entered.send(()).unwrap();
        let (lock, ready) = &*worker_gate;
        let mut released = lock.lock().unwrap();
        while !*released {
            released = ready.wait(released).unwrap();
        }
    }));
    let reload = f.secrets.reload(1, specs("2")).unwrap();
    tokio::time::timeout(Duration::from_secs(2), observed)
        .await
        .unwrap()
        .unwrap();
    drop(reload);
    let during = f.secrets.snapshot().unwrap();
    assert!(during.loading);
    assert_eq!(during.generation, 1);
    assert_eq!(during.retained_generations, 2);
    assert_eq!(f.pools.snapshot().unwrap().workers, 1);
    assert!(f.secrets.reload(1, specs("3")).is_err());
    let (lock, ready) = &*gate;
    *lock.lock().unwrap() = true;
    ready.notify_one();
    let deadline = Instant::now() + Duration::from_secs(2);
    while f.secrets.snapshot().unwrap().loading || f.pools.snapshot().unwrap().workers != 0 {
        assert!(Instant::now() < deadline);
        tokio::task::yield_now().await;
    }
    assert_eq!(f.secrets.snapshot().unwrap().generation, 1);
    assert_eq!(f.secrets.snapshot().unwrap().retained_generations, 1);
    assert_eq!(invoke(&f, 0).await, marker(b'A', b'1', 5));
    shutdown(&f).await;
}

#[tokio::test]
async fn closing_the_store_fences_retained_reads_and_a_candidate_worker() {
    let f = Fixture::new().await;
    let (session, _) = f.session("retained-at-close");
    let value = f
        .provider
        .read(&session, "allowed".into())
        .unwrap()
        .await
        .unwrap();
    let (entered, observed) = tokio::sync::oneshot::channel();
    let (release, wait) = std::sync::mpsc::sync_channel(1);
    *f.secret_clock.hook.lock().unwrap() = Some(Box::new(move || {
        entered.send(()).unwrap();
        wait.recv().unwrap();
    }));
    let reload = f.secrets.reload(1, specs("2")).unwrap();
    tokio::time::timeout(Duration::from_secs(2), observed)
        .await
        .unwrap()
        .unwrap();
    f.secrets.close();
    assert!(value
        .disclose(&mut |_| panic!("closed store disclosed bytes"))
        .is_err());
    drop(session);
    assert_eq!(f.secrets.snapshot().unwrap().retained_generations, 1);
    assert_eq!(f.pools.snapshot().unwrap().workers, 1);
    release.send(()).unwrap();
    assert!(reload.await.is_err());
    assert_eq!(f.secrets.snapshot().unwrap().generation, 1);
    assert_eq!(f.secrets.snapshot().unwrap().retained_generations, 0);
    f.idle();
    shutdown(&f).await;
}
