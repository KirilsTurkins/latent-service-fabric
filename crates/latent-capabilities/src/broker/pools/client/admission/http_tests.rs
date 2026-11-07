use super::*;
use crate::broker::pools::{limits::Kind, tests::fixture::*, ProviderPoolLimits};
use crate::broker::tests::fixture::{pending, ready};
use latent_core::PlatformErrorCode;
use std::{
    io::Read,
    net::{TcpListener, TcpStream},
    sync::atomic::Ordering,
    time::Instant,
};

fn socket(
    reservation: ConnectionReservation<TcpStream>,
) -> (PooledConnection<TcpStream>, TcpStream) {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let stream = TcpStream::connect(listener.local_addr().unwrap()).unwrap();
    let (peer, _) = listener.accept().unwrap();
    peer.set_read_timeout(Some(Duration::from_millis(100)))
        .unwrap();
    (reservation.connected(stream).unwrap(), peer)
}

#[tokio::test]
async fn http_sibling_dials_after_setup_without_waiting_for_the_first_response() {
    let setup = Setup::new(ProviderPoolLimits::default());
    let (session, _control) = setup.session("http-sibling-setup");
    let observer = session.observer();
    let first_call = setup.call(&session).await;
    let second_call = setup.call(&session).await;
    let first = setup.client.reserve_connection(&first_call).unwrap();
    let before = setup.pools.snapshot().unwrap();
    let mut waiting = Box::pin(setup.client.reserve_http_connection_wait(&second_call));
    pending(waiting.as_mut());
    assert_eq!(setup.pools.snapshot().unwrap(), before);
    assert_eq!(setup.pools.inner.quotas.use_of(Kind::Connection), 1);
    // Ordinary APIs retain their immediate active-dial refusal.
    assert_eq!(
        ready(setup.client.reserve_connection_wait(&second_call))
            .err()
            .unwrap()
            .code,
        PlatformErrorCode::ResourceExhausted
    );
    // The real first socket remains open without returning any response.
    // Only setup completes; no header, body, close, or retry releases the slot.
    let (first, mut first_peer) = socket(first);
    let second = waiting.await.unwrap();
    assert_eq!(setup.pools.inner.quotas.use_of(Kind::Connection), 2);
    let (second, mut second_peer) = socket(second);
    assert_eq!(setup.pools.snapshot().unwrap().connecting_connections, 0);
    drop((first, second, first_call, second_call, session));
    assert_eq!(first_peer.read(&mut [0]).unwrap(), 0);
    assert_eq!(second_peer.read(&mut [0]).unwrap(), 0);
    assert!(observer.is_quiescent());
    clean(&setup.pools).await;
}

#[tokio::test]
async fn cancelled_or_dropped_http_dial_wait_does_not_release_another_call() {
    for cancelled in [false, true] {
        let setup = Setup::new(ProviderPoolLimits::default());
        let (first_session, _first_control) = setup.session("http-first");
        let first_call = setup.call(&first_session).await;
        let first = setup.client.reserve_connection(&first_call).unwrap();
        let (second_session, second_control) = setup.session("http-second");
        let observer = second_session.observer();
        let second_call = setup.call(&second_session).await;
        let mut waiting = Box::pin(setup.client.reserve_http_connection_wait(&second_call));
        pending(waiting.as_mut());
        if cancelled {
            second_control.probe.0.store(true, Ordering::Release);
            assert_eq!(
                waiting.await.err().unwrap().code,
                PlatformErrorCode::Cancelled
            );
        } else {
            drop(waiting);
        }
        assert_eq!(setup.pools.inner.quotas.use_of(Kind::Connection), 1);
        assert!(setup.client.core.backoff.lock().unwrap().dialing);
        drop((second_call, second_session));
        assert!(observer.is_quiescent());
        let (first, mut peer) = socket(first);
        drop((first, first_call, first_session));
        assert_eq!(peer.read(&mut [0]).unwrap(), 0);
        clean(&setup.pools).await;
    }
}

#[tokio::test]
async fn http_dial_wait_keeps_the_original_deadline_and_connection_owner() {
    let setup = Setup::new(ProviderPoolLimits::default());
    let (session, _control) = setup.session("http-setup-deadline");
    let first_call = setup.call(&session).await;
    let first = setup.client.reserve_connection(&first_call).unwrap();
    let second_call = setup
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
    let original = second_call.io().deadline();
    let mut waiting = Box::pin(setup.client.reserve_http_connection_wait(&second_call));
    pending(waiting.as_mut());
    std::thread::sleep(Duration::from_millis(125));
    assert_eq!(
        waiting.await.err().unwrap().code,
        PlatformErrorCode::DeadlineExceeded
    );
    assert_eq!(second_call.io().deadline(), original);
    assert_eq!(setup.pools.inner.quotas.use_of(Kind::Connection), 1);
    drop((first, first_call, second_call, session));
    clean(&setup.pools).await;
}

#[tokio::test]
async fn http_dial_wait_does_not_wait_through_backoff_or_retry_a_failed_dial() {
    let setup = Setup::new(ProviderPoolLimits {
        initial_backoff: Duration::from_secs(30),
        maximum_backoff: Duration::from_secs(30),
        ..ProviderPoolLimits::default()
    });
    let (session, _control) = setup.session("http-setup-failed");
    let first_call = setup.call(&session).await;
    let second_call = setup.call(&session).await;
    let first = setup.client.reserve_connection(&first_call).unwrap();
    let mut waiting = Box::pin(setup.client.reserve_http_connection_wait(&second_call));
    pending(waiting.as_mut());
    drop(first);
    let error = waiting.await.err().unwrap();
    assert_eq!(error.code, PlatformErrorCode::Unavailable);
    assert_eq!(error.message, "provider-backoff");
    assert_eq!(setup.pools.inner.quotas.use_of(Kind::Connection), 0);
    drop((first_call, second_call, session));
    clean(&setup.pools).await;
}

#[tokio::test]
async fn http_dial_wait_preserves_capacity_refusal_after_another_dial_completes() {
    let setup = Setup::new(ProviderPoolLimits {
        maximum_connections: 1,
        maximum_connections_per_client: 1,
        maximum_idle_connections: 1,
        ..ProviderPoolLimits::default()
    });
    let (session, _control) = setup.session("http-setup-capacity");
    let first_call = setup.call(&session).await;
    let second_call = setup.call(&session).await;
    let first = setup.client.reserve_connection(&first_call).unwrap();
    let mut waiting = Box::pin(setup.client.reserve_http_connection_wait(&second_call));
    pending(waiting.as_mut());
    let (first, mut peer) = socket(first);
    assert_eq!(
        waiting.await.err().unwrap().code,
        PlatformErrorCode::ResourceExhausted
    );
    assert_eq!(setup.pools.inner.quotas.use_of(Kind::Connection), 1);
    assert_eq!(setup.pools.snapshot().unwrap().connecting_connections, 0);
    drop((first, first_call, second_call, session));
    assert_eq!(peer.read(&mut [0]).unwrap(), 0);
    clean(&setup.pools).await;
}

#[tokio::test]
async fn http_dial_wait_cannot_borrow_a_different_client_or_poisoned_registry() {
    let setup = Setup::new(ProviderPoolLimits::default());
    let (session, _control) = setup.session("http-setup-authority");
    let call = setup.call(&session).await;
    let other = setup.pools.client::<TcpStream>(&setup.provider, 1).unwrap();
    assert_eq!(
        ready(other.reserve_http_connection_wait(&call))
            .err()
            .unwrap()
            .code,
        PlatformErrorCode::PermissionDenied
    );
    assert!(std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        let _guard = setup.pools.inner.state.lock().unwrap();
        panic!("controlled registry poison");
    }))
    .is_err());
    let error = ready(setup.client.reserve_http_connection_wait(&call))
        .err()
        .unwrap();
    assert_eq!(error.code, PlatformErrorCode::Unavailable);
    assert_eq!(error.message, "provider-client-owner-poisoned");
    assert_eq!(setup.pools.inner.quotas.use_of(Kind::Connection), 0);
    setup.pools.inner.state.clear_poison();
    drop((other, call, session));
    clean(&setup.pools).await;
}
