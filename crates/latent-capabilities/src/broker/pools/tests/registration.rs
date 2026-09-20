use super::*;
use latent_core::PlatformErrorCode;
use std::{
    future::Future,
    pin::Pin,
    task::{Context, Poll, Waker},
};

fn pending<T>(future: Pin<&mut impl Future<Output = T>>) {
    assert!(matches!(
        future.poll(&mut Context::from_waker(Waker::noop())),
        Poll::Pending
    ));
}

#[tokio::test]
async fn registry_contention_retains_one_bounded_admission_until_dispatch() {
    let setup = Setup::new(ProviderPoolLimits::default());
    let (session, _control) = setup.session("registry-contention");
    let observer = session.observer();
    let mut waiting;
    {
        let _registry = setup.pools.inner.state.lock().unwrap();
        let admission = setup.pools.admit(&setup.client, &session).unwrap();
        assert_eq!(setup.pools.inner.quotas.use_of(Kind::Pending), 1);
        assert_eq!(setup.pools.inner.io.snapshot().calls, 1);
        waiting = Box::pin(admission.wait());
        pending(waiting.as_mut());
        assert_eq!(setup.pools.inner.quotas.use_of(Kind::Running), 0);
    }
    let call = waiting.await.unwrap().start(dispatch(&session)).unwrap();
    assert_eq!(setup.pools.snapshot().unwrap().running_requests, 1);
    drop((call, session));
    assert!(observer.is_quiescent());
    clean(&setup.pools).await;
}

#[tokio::test]
async fn scheduling_contention_waits_without_re_registering_or_granting_twice() {
    let setup = Setup::new(ProviderPoolLimits::default());
    let (session, _control) = setup.session("schedule-contention");
    let mut waiting = Box::pin(setup.pools.admit(&setup.client, &session).unwrap().wait());
    {
        let _registry = setup.pools.inner.state.lock().unwrap();
        pending(waiting.as_mut());
        assert_eq!(setup.pools.inner.quotas.use_of(Kind::Pending), 1);
        assert_eq!(setup.pools.inner.quotas.use_of(Kind::Running), 0);
    }
    let call = waiting.await.unwrap().start(dispatch(&session)).unwrap();
    assert_eq!(setup.pools.snapshot().unwrap().running_requests, 1);
    drop((call, session));
    clean(&setup.pools).await;
}

#[tokio::test]
async fn cancelled_registration_and_scheduling_never_dispatch() {
    for registered in [false, true] {
        let setup = Setup::new(ProviderPoolLimits::default());
        let (session, control) = setup.session("registry-cancel");
        let observer = session.observer();
        let admitted = registered.then(|| setup.pools.admit(&setup.client, &session).unwrap());
        let mut waiting;
        {
            let _registry = setup.pools.inner.state.lock().unwrap();
            let admission =
                admitted.unwrap_or_else(|| setup.pools.admit(&setup.client, &session).unwrap());
            waiting = Box::pin(admission.wait());
            pending(waiting.as_mut());
            control.probe.0.store(true, Ordering::Release);
        }
        assert_eq!(
            waiting.await.err().unwrap().code,
            PlatformErrorCode::Cancelled
        );
        drop(session);
        assert!(observer.is_quiescent());
        clean(&setup.pools).await;
    }
}

#[tokio::test]
async fn pending_capacity_is_reserved_before_registration_and_refunded_only_on_drop() {
    let setup = Setup::new(ProviderPoolLimits {
        maximum_pending_requests: 1,
        ..ProviderPoolLimits::default()
    });
    let (session, _control) = setup.session("registry-capacity");
    {
        let _registry = setup.pools.inner.state.lock().unwrap();
        let admission = setup.pools.admit(&setup.client, &session).unwrap();
        assert_eq!(
            setup
                .pools
                .admit(&setup.client, &session)
                .err()
                .unwrap()
                .code,
            PlatformErrorCode::ResourceExhausted
        );
        assert_eq!(setup.pools.inner.quotas.use_of(Kind::Pending), 1);
        drop(admission);
        assert_eq!(setup.pools.inner.quotas.use_of(Kind::Pending), 0);
        assert_eq!(setup.pools.inner.io.snapshot().calls, 0);
        drop(setup.pools.admit(&setup.client, &session).unwrap());
    }
    drop(session);
    clean(&setup.pools).await;
}

#[tokio::test]
async fn registry_wait_keeps_the_original_queue_deadline() {
    let setup = Setup::new(ProviderPoolLimits {
        maximum_queue_age: Duration::from_millis(30),
        ..ProviderPoolLimits::default()
    });
    let (session, _control) = setup.session("registry-deadline");
    let mut waiting;
    {
        let _registry = setup.pools.inner.state.lock().unwrap();
        waiting = Box::pin(setup.pools.admit(&setup.client, &session).unwrap().wait());
        pending(waiting.as_mut());
        std::thread::sleep(Duration::from_millis(40));
    }
    assert_eq!(
        waiting.await.err().unwrap().code,
        PlatformErrorCode::DeadlineExceeded
    );
    drop(session);
    clean(&setup.pools).await;
}

#[tokio::test]
async fn retiring_during_registration_cannot_admit_stale_provider_work() {
    let setup = Setup::new(ProviderPoolLimits::default());
    let (session, _control) = setup.session("registry-retire");
    let mut waiting;
    {
        let _registry = setup.pools.inner.state.lock().unwrap();
        waiting = Box::pin(setup.pools.admit(&setup.client, &session).unwrap().wait());
        pending(waiting.as_mut());
    }
    setup.pools.retire();
    assert!(waiting.await.is_err());
    assert_eq!(setup.pools.inner.quotas.use_of(Kind::Running), 0);
    drop(session);
    clean(&setup.pools).await;
}
