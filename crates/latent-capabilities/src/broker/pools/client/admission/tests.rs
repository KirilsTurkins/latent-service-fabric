use super::*;
use crate::broker::pools::{ProviderPoolLimits, limits::Kind, tests::fixture::*};
use crate::broker::tests::fixture::{pending, ready};
use latent_core::PlatformErrorCode;
use std::sync::atomic::Ordering;
use std::time::Instant;

#[tokio::test]
async fn registry_inspection_delays_one_reservation_without_charging_capacity() {
    let setup = Setup::new(single());
    let (session, _control) = setup.session("dial-registry");
    let observer = session.observer();
    let call = setup.call(&session).await;
    let mut waiting = Box::pin(setup.client.reserve_connection_wait(&call));
    {
        let _inspection = setup.pools.inner.state.lock().unwrap();
        pending(waiting.as_mut());
        assert_eq!(setup.pools.inner.quotas.use_of(Kind::Connection), 0);
        assert!(!setup.client.core.backoff.lock().unwrap().dialing);
    }
    let reservation = waiting.await.unwrap();
    assert_eq!(setup.pools.snapshot().unwrap().connecting_connections, 1);
    assert_eq!(setup.pools.inner.quotas.use_of(Kind::Connection), 1);
    drop((reservation, call, session));
    assert!(observer.is_quiescent());
    clean(&setup.pools).await;
}

#[tokio::test]
async fn backoff_inspection_delays_reservation_without_starting_another_dial() {
    let setup = Setup::new(single());
    let (session, _control) = setup.session("dial-backoff-lock");
    let call = setup.call(&session).await;
    let mut waiting = Box::pin(setup.client.reserve_connection_wait(&call));
    {
        let _inspection = setup.client.core.backoff.lock().unwrap();
        pending(waiting.as_mut());
        assert_eq!(setup.pools.inner.quotas.use_of(Kind::Connection), 0);
    }
    let reservation = waiting.await.unwrap();
    assert_eq!(setup.pools.snapshot().unwrap().connecting_connections, 1);
    drop((reservation, call, session));
    clean(&setup.pools).await;
}

#[tokio::test]
async fn idle_maintenance_delays_checkout_and_preserves_the_physical_socket() {
    let setup = Setup::new(single());
    let (session, _control) = setup.session("checkout-idle");
    let call = setup.call(&session).await;
    let (mut connection, _peer) = connect(&setup.client, &call);
    let address = connection.resource().local_addr().unwrap();
    connection.park().unwrap();
    let mut waiting = Box::pin(setup.client.checkout_wait(&call));
    {
        let _maintenance = setup.client.idle.lock().unwrap();
        pending(waiting.as_mut());
        assert_eq!(setup.pools.snapshot().unwrap().idle_connections, 1);
    }
    let mut connection = waiting.await.unwrap().unwrap();
    assert_eq!(connection.resource().local_addr().unwrap(), address);
    assert_eq!(setup.pools.snapshot().unwrap().connections, 1);
    assert_eq!(setup.pools.snapshot().unwrap().idle_connections, 0);
    drop((connection, call, session));
    clean(&setup.pools).await;
}

#[tokio::test]
async fn cancelled_or_abandoned_connection_wait_never_reserves_a_socket() {
    for cancel in [false, true] {
        let setup = Setup::new(single());
        let (session, control) = setup.session("dial-cancel");
        let observer = session.observer();
        let call = setup.call(&session).await;
        let mut waiting = Box::pin(setup.client.reserve_connection_wait(&call));
        {
            let _inspection = setup.pools.inner.state.lock().unwrap();
            pending(waiting.as_mut());
            if cancel {
                control.probe.0.store(true, Ordering::Release);
            }
            assert_eq!(setup.pools.inner.quotas.use_of(Kind::Connection), 0);
        }
        if cancel {
            assert_eq!(
                waiting.await.err().unwrap().code,
                PlatformErrorCode::Cancelled
            );
        } else {
            drop(waiting);
        }
        assert_eq!(setup.pools.inner.quotas.use_of(Kind::Connection), 0);
        drop((call, session));
        assert!(observer.is_quiescent());
        clean(&setup.pools).await;
    }
}

#[tokio::test]
async fn connection_contention_preserves_the_original_http_deadline() {
    let setup = Setup::new(single());
    let (session, _control) = setup.session("dial-deadline");
    let observer = session.observer();
    let call = setup
        .pools
        .admit_until(
            &setup.client,
            &session,
            Instant::now() + Duration::from_millis(100),
        )
        .unwrap()
        .wait()
        .await
        .unwrap()
        .start(dispatch(&session))
        .unwrap();
    let original = call.io().deadline();
    let mut waiting = Box::pin(setup.client.reserve_connection_wait(&call));
    {
        let _inspection = setup.pools.inner.state.lock().unwrap();
        pending(waiting.as_mut());
        std::thread::sleep(Duration::from_millis(125));
    }
    assert_eq!(
        waiting.await.err().unwrap().code,
        PlatformErrorCode::DeadlineExceeded
    );
    assert_eq!(call.io().deadline(), original);
    assert_eq!(setup.pools.inner.quotas.use_of(Kind::Connection), 0);
    drop((call, session));
    assert!(observer.is_quiescent());
    clean(&setup.pools).await;
}

#[tokio::test]
async fn actual_capacity_active_dial_and_backoff_are_not_waited_or_retried() {
    let setup = Setup::new(ProviderPoolLimits {
        maximum_connections: 1,
        maximum_connections_per_client: 1,
        maximum_idle_connections: 1,
        ..ProviderPoolLimits::default()
    });
    let (session, _control) = setup.session("dial-no-retry");
    let call = setup.call(&session).await;
    let charge = setup
        .pools
        .inner
        .quotas
        .acquire(Kind::Connection, 1)
        .unwrap();
    assert_eq!(
        ready(setup.client.reserve_connection_wait(&call))
            .err()
            .unwrap()
            .code,
        PlatformErrorCode::ResourceExhausted
    );
    drop(charge);
    let reservation = ready(setup.client.reserve_connection_wait(&call)).unwrap();
    assert_eq!(
        ready(setup.client.reserve_connection_wait(&call))
            .err()
            .unwrap()
            .code,
        PlatformErrorCode::ResourceExhausted
    );
    drop(reservation);
    let failure = ready(setup.client.reserve_connection_wait(&call))
        .err()
        .unwrap();
    assert_eq!(failure.code, PlatformErrorCode::Unavailable);
    assert_eq!(failure.message, "provider-backoff");
    assert_eq!(setup.pools.inner.quotas.use_of(Kind::Connection), 0);
    drop((call, session));
    clean(&setup.pools).await;
}

#[tokio::test]
async fn poisoned_connection_registry_fails_closed_without_waiting() {
    let setup = Setup::new(single());
    let (session, _control) = setup.session("dial-poisoned");
    let call = setup.call(&session).await;
    assert!(
        std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            let _inspection = setup.pools.inner.state.lock().unwrap();
            panic!("controlled connection registry poison");
        }))
        .is_err()
    );
    let failure = ready(setup.client.reserve_connection_wait(&call))
        .err()
        .unwrap();
    assert_eq!(failure.code, PlatformErrorCode::Unavailable);
    assert_eq!(failure.message, "provider-client-owner-poisoned");
    assert_eq!(setup.pools.inner.quotas.use_of(Kind::Connection), 0);
    setup.pools.inner.state.clear_poison();
    drop((call, session));
    clean(&setup.pools).await;
}
