use super::{config, fixture::Fixture};
use crate::StreamErrorCode;
use latent_capabilities::broker::network::{OutboundStreamInvoker, StreamConnectRequest};
use latent_policy::capability::{MutationRequest, RecordKind};
use std::{
    future::poll_fn,
    task::Poll,
    time::{Duration, Instant},
};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::TcpListener,
};

#[tokio::test]
async fn a_policy_change_while_readable_is_pending_is_checked_before_syscall() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let mut config = config();
    config.destinations[0].endpoint.port = listener.local_addr().unwrap().port();
    let endpoint = config.destinations[0].endpoint.clone();
    let fixture = Fixture::new(config);
    let (session, control) = fixture.session(5000);
    let stream = fixture
        .provider
        .start(
            &session,
            StreamConnectRequest {
                endpoint,
                timeout_millis: None,
            },
        )
        .unwrap()
        .await
        .unwrap();
    let (mut peer, _) = listener.accept().await.unwrap();
    let mut pending = stream.read(4, None).unwrap();
    assert!(poll_fn(|cx| Poll::Ready(pending.as_mut().poll(cx)))
        .await
        .is_pending());
    fixture
        .policies
        .mutate(
            MutationRequest {
                tenant: "a",
                actor: "operator",
                id: "p",
                kind: RecordKind::Policy,
                operation_id: "revoke-during-readiness",
                expected_revision: 2,
                document: None,
            },
            Instant::now() + Duration::from_secs(1),
            |_| Ok(()),
        )
        .unwrap();
    peer.write_all(b"NEVER").await.unwrap();
    assert_eq!(pending.await.err().unwrap().code, StreamErrorCode::Denied);
    assert_eq!(stream.inspect().delivered_read_bytes, 0);
    assert!(!stream.inspect().application_write_attempted);
    drop(stream);
    let mut byte = [0];
    match peer.read(&mut byte).await {
        Ok(0) => {}
        Err(failure) if failure.kind() == std::io::ErrorKind::ConnectionReset => {}
        value => panic!("revoked readable owner must retire: {value:?}"),
    }
    assert_eq!(control.budget.host_memory_bytes(), 0);
    drop(session);
    fixture.clean().await;
}

#[tokio::test]
async fn provider_retirement_wakes_pending_read_without_early_refund() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let mut config = config();
    config.destinations[0].endpoint.port = listener.local_addr().unwrap().port();
    let endpoint = config.destinations[0].endpoint.clone();
    let fixture = Fixture::new(config);
    let (session, control) = fixture.session(5000);
    let stream = fixture
        .provider
        .start(
            &session,
            StreamConnectRequest {
                endpoint,
                timeout_millis: None,
            },
        )
        .unwrap()
        .await
        .unwrap();
    let (mut peer, _) = listener.accept().await.unwrap();
    let mut pending = stream.read(4, None).unwrap();
    assert!(poll_fn(|cx| Poll::Ready(pending.as_mut().poll(cx)))
        .await
        .is_pending());
    fixture.provider.retire();
    assert!(fixture.provider.usage().unwrap().retired);
    assert_eq!(fixture.pools.snapshot().unwrap().connections, 1);
    assert!(control.budget.host_memory_bytes() >= 96 * 1024);
    assert_eq!(pending.await.err().unwrap().code, StreamErrorCode::Revoked);
    let mut byte = [0];
    assert_eq!(peer.read(&mut byte).await.unwrap(), 0);
    assert_eq!(fixture.pools.snapshot().unwrap().connections, 0);
    assert_eq!(fixture.pools.snapshot().unwrap().running_requests, 1);
    drop(stream);
    assert_eq!(control.budget.host_memory_bytes(), 0);
    drop(session);
    fixture.clean().await;
}
