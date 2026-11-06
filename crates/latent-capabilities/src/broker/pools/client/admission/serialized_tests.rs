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

fn socket() -> (TcpStream, TcpStream) {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let stream = TcpStream::connect(listener.local_addr().unwrap()).unwrap();
    let (peer, _) = listener.accept().unwrap();
    peer.set_read_timeout(Some(Duration::from_secs(1))).unwrap();
    (stream, peer)
}

#[tokio::test]
async fn serialized_cold_dials_keep_one_dial_and_two_independent_live_connections() {
    let setup = Setup::new(ProviderPoolLimits::default());
    let (session, _control) = setup.session("serialized-dials");
    let observer = session.observer();
    let first = setup.call(&session).await;
    let second = setup.call(&session).await;
    let dial = setup.client.reserve_connection(&first).unwrap();
    let mut waiting = Box::pin(setup.client.reserve_connection_serialized(&second));
    pending(waiting.as_mut());
    assert_eq!(setup.pools.snapshot().unwrap().connecting_connections, 1);
    assert_eq!(setup.pools.inner.quotas.use_of(Kind::Connection), 1);
    // The existing immediate API still refuses another concurrent dial.
    assert_eq!(
        ready(setup.client.reserve_connection_wait(&second))
            .err()
            .unwrap()
            .code,
        PlatformErrorCode::ResourceExhausted
    );
    let (stream, mut peer) = socket();
    let connection = dial.connected(stream).unwrap();
    let second_dial = waiting.await.unwrap();
    assert_eq!(setup.pools.snapshot().unwrap().connecting_connections, 1);
    assert_eq!(setup.pools.snapshot().unwrap().connections, 2);
    let (stream, mut second_peer) = socket();
    let second_connection = second_dial.connected(stream).unwrap();
    assert_eq!(setup.pools.snapshot().unwrap().connecting_connections, 0);
    // Retiring one socket must not retire the other request or its capacity.
    drop((second_connection, second));
    assert_eq!(second_peer.read(&mut [0]).unwrap(), 0);
    assert_eq!(setup.pools.snapshot().unwrap().connections, 1);
    drop((connection, first, session));
    assert_eq!(peer.read(&mut [0]).unwrap(), 0);
    assert!(observer.is_quiescent());
    clean(&setup.pools).await;
}

#[tokio::test]
async fn cancelled_or_dropped_serialized_wait_never_allocates_another_connection() {
    for cancel in [false, true] {
        let setup = Setup::new(ProviderPoolLimits::default());
        let (session, control) = setup.session("serialized-cancel");
        let observer = session.observer();
        let first = setup.call(&session).await;
        let second = setup.call(&session).await;
        let dial = setup.client.reserve_connection(&first).unwrap();
        let mut waiting = Box::pin(setup.client.reserve_connection_serialized(&second));
        pending(waiting.as_mut());
        if cancel {
            control.probe.0.store(true, Ordering::Release);
            assert_eq!(
                waiting.await.err().unwrap().code,
                PlatformErrorCode::Cancelled
            );
        } else {
            drop(waiting);
        }
        assert_eq!(setup.pools.snapshot().unwrap().connections, 1);
        assert_eq!(setup.pools.snapshot().unwrap().connecting_connections, 1);
        drop((dial, first, second, session));
        assert!(observer.is_quiescent());
        clean(&setup.pools).await;
    }
}

#[tokio::test]
async fn serialized_wait_keeps_its_original_absolute_deadline() {
    let setup = Setup::new(ProviderPoolLimits::default());
    let (session, _control) = setup.session("serialized-deadline");
    let first = setup.call(&session).await;
    let dial = setup.client.reserve_connection(&first).unwrap();
    let second = setup
        .pools
        .admit_until(
            &setup.client,
            &session,
            Instant::now() + Duration::from_millis(25),
        )
        .unwrap()
        .wait()
        .await
        .unwrap()
        .start(dispatch(&session))
        .unwrap();
    let deadline = second.io().deadline();
    assert_eq!(
        setup
            .client
            .reserve_connection_serialized(&second)
            .await
            .err()
            .unwrap()
            .code,
        PlatformErrorCode::DeadlineExceeded
    );
    assert_eq!(second.io().deadline(), deadline);
    assert_eq!(setup.pools.snapshot().unwrap().connections, 1);
    drop((dial, first, second, session));
    clean(&setup.pools).await;
}

#[tokio::test]
async fn failed_preceding_dial_keeps_backoff_instead_of_retrying() {
    let setup = Setup::new(ProviderPoolLimits::default());
    let (session, _control) = setup.session("serialized-backoff");
    let first = setup.call(&session).await;
    let second = setup.call(&session).await;
    let dial = setup.client.reserve_connection(&first).unwrap();
    let mut waiting = Box::pin(setup.client.reserve_connection_serialized(&second));
    pending(waiting.as_mut());
    drop(dial);
    let failure = waiting.await.err().unwrap();
    assert_eq!(failure.code, PlatformErrorCode::Unavailable);
    assert_eq!(failure.message, "provider-backoff");
    assert_eq!(setup.pools.snapshot().unwrap().connecting_connections, 0);
    assert_eq!(setup.pools.inner.quotas.use_of(Kind::Connection), 0);
    drop((first, second, session));
    clean(&setup.pools).await;
}

#[tokio::test]
async fn serialized_wait_does_not_wait_for_actual_capacity_or_poisoned_ownership() {
    let setup = Setup::new(ProviderPoolLimits {
        maximum_connections: 1,
        maximum_connections_per_client: 1,
        maximum_idle_connections: 1,
        ..ProviderPoolLimits::default()
    });
    let (session, _control) = setup.session("serialized-capacity");
    let call = setup.call(&session).await;
    let dial = setup.client.reserve_connection(&call).unwrap();
    assert_eq!(
        ready(setup.client.reserve_connection_serialized(&call))
            .err()
            .unwrap()
            .code,
        PlatformErrorCode::ResourceExhausted
    );
    assert_eq!(setup.pools.snapshot().unwrap().connections, 1);
    drop(dial);
    assert!(std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        let _lock = setup.client.core.backoff.lock().unwrap();
        panic!("controlled dial ownership poison");
    }))
    .is_err());
    assert_eq!(
        ready(setup.client.reserve_connection_serialized(&call))
            .err()
            .unwrap()
            .code,
        PlatformErrorCode::Unavailable
    );
    setup.client.core.backoff.clear_poison();
    drop((call, session));
    clean(&setup.pools).await;
}
