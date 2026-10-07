//! These tests execute the maintained provider against actual TCP peers and
//! sealed broker sessions. They are native-provider evidence, separate from
//! the component and standard-library qualification gate.
use super::{config, fixture::Fixture};
use crate::StreamErrorCode;
use latent_capabilities::broker::network::{
    OutboundStreamInvoker, StreamConnectRequest, StreamShutdown, StreamState,
};
use latent_policy::capability::{MutationRequest, RecordKind};
use std::time::{Duration, Instant};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::TcpListener,
};

async fn fixture() -> (Fixture, TcpListener) {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let mut config = config();
    config.destinations[0].endpoint.port = listener.local_addr().unwrap().port();
    (Fixture::new(config), listener)
}
fn request(fixture: &Fixture) -> StreamConnectRequest {
    StreamConnectRequest {
        endpoint: fixture.provider.inner.config.destinations[0]
            .endpoint
            .clone(),
        timeout_millis: None,
    }
}

#[tokio::test]
async fn actual_tcp_partial_reads_eof_and_send_half_close() {
    let (fixture, listener) = fixture().await;
    let peer = tokio::spawn(async move {
        let (mut socket, _) = listener.accept().await.unwrap();
        let mut message = Vec::new();
        socket.read_to_end(&mut message).await.unwrap();
        assert_eq!(message, b"PING");
        socket.write_all(b"one").await.unwrap();
        socket.write_all(b"two").await.unwrap();
        socket.shutdown().await.unwrap();
    });
    let (session, control) = fixture.session(5000);
    let stream = fixture
        .provider
        .start(&session, request(&fixture))
        .unwrap()
        .await
        .unwrap();
    assert_eq!(
        control.budget.snapshot_at(Instant::now()).outbound_requests,
        1
    );
    assert!(control.budget.host_memory_bytes() > 0);
    assert_eq!(
        stream.write(b"PING".to_vec(), None).unwrap().await.unwrap(),
        4
    );
    assert_eq!(
        stream
            .shutdown(StreamShutdown::Send)
            .unwrap()
            .await
            .unwrap()
            .state,
        StreamState::WriteShut
    );
    let mut received = Vec::new();
    while let Some(mut chunk) = stream.read(2, None).unwrap().await.unwrap() {
        let bytes = chunk.copy_bytes().unwrap();
        assert!(!bytes.is_empty() && bytes.len() <= 2);
        received.extend(bytes);
    }
    assert_eq!(received, b"onetwo");
    assert_eq!(stream.inspect().state, StreamState::ReadEofWriteShut);
    assert_eq!(stream.inspect().accepted_write_bytes, 4);
    assert_eq!(stream.inspect().delivered_read_bytes, 6);
    assert!(stream.inspect().application_write_attempted);
    assert_eq!(stream.close().await.unwrap().state, StreamState::Closed);
    peer.await.unwrap();
    assert_eq!(control.budget.host_memory_bytes(), 0);
    assert_eq!(fixture.provider.usage().unwrap().connections, 0);
    drop(session);
    fixture.clean().await;
}

#[tokio::test]
async fn retained_chunks_keep_original_charges_after_socket_close() {
    let (fixture, listener) = fixture().await;
    let peer = tokio::spawn(async move {
        let (mut socket, _) = listener.accept().await.unwrap();
        socket.write_all(&vec![0x5a; 32 * 1024]).await.unwrap();
        let mut eof = [0u8; 1];
        assert_eq!(socket.read(&mut eof).await.unwrap(), 0);
    });
    let (session, control) = fixture.session(5000);
    let stream = fixture
        .provider
        .start(&session, request(&fixture))
        .unwrap()
        .await
        .unwrap();
    let mut first = stream
        .read(16 * 1024, None)
        .unwrap()
        .await
        .unwrap()
        .unwrap();
    let mut second = stream
        .read(16 * 1024, None)
        .unwrap()
        .await
        .unwrap()
        .unwrap();
    assert_eq!(
        stream.read(16 * 1024, None).err().unwrap().code,
        StreamErrorCode::Exhausted
    );
    let mut produced = false;
    assert_eq!(
        stream
            .write_from(1, None, &mut || {
                produced = true;
                Ok(vec![0x5a])
            })
            .err()
            .unwrap()
            .code,
        StreamErrorCode::Exhausted
    );
    assert!(
        !produced,
        "the full window denies before canonical host copying"
    );
    let before = control.budget.host_memory_bytes();
    assert!(before >= 64 * 1024);
    stream.close().await.unwrap();
    peer.await.unwrap();
    let usage = fixture.provider.usage().unwrap();
    assert_eq!(usage.connections, 0);
    assert_eq!(usage.retained_chunks, 2);
    assert_eq!(fixture.pools.snapshot().unwrap().connections, 0);
    assert_eq!(fixture.pools.snapshot().unwrap().running_requests, 1);
    assert!(control.budget.host_memory_bytes() >= 64 * 1024);
    let first_bytes = first.copy_bytes().unwrap();
    let second_bytes = second.copy_bytes().unwrap();
    assert!(first_bytes.iter().chain(&second_bytes).all(|b| *b == 0x5a));
    drop(first_bytes);
    drop(second_bytes);
    drop(first);
    drop(second);
    assert_eq!(control.budget.host_memory_bytes(), 0);
    assert_eq!(fixture.pools.snapshot().unwrap().running_requests, 0);
    drop(session);
    fixture.clean().await;
}

#[tokio::test]
async fn dropped_facade_does_not_refund_an_unpolled_pending_socket() {
    let (fixture, listener) = fixture().await;
    let (session, control) = fixture.session(5000);
    let stream = fixture
        .provider
        .start(&session, request(&fixture))
        .unwrap()
        .await
        .unwrap();
    let (mut peer, _) = listener.accept().await.unwrap();
    let pending = stream.read(16 * 1024, None).unwrap();
    drop(stream);
    assert_eq!(fixture.provider.usage().unwrap().pending_operations, 1);
    assert_eq!(fixture.pools.snapshot().unwrap().connections, 1);
    assert_eq!(fixture.pools.snapshot().unwrap().running_requests, 1);
    assert!(control.budget.host_memory_bytes() >= 96 * 1024);
    drop(pending);
    let mut byte = [0];
    assert_eq!(
        tokio::time::timeout(Duration::from_secs(1), peer.read(&mut byte))
            .await
            .unwrap()
            .unwrap(),
        0
    );
    assert_eq!(fixture.pools.snapshot().unwrap().connections, 0);
    assert_eq!(fixture.pools.snapshot().unwrap().running_requests, 0);
    assert_eq!(control.budget.host_memory_bytes(), 0);
    drop(session);
    fixture.clean().await;
}

#[tokio::test]
async fn wrong_endpoint_is_denied_before_network_dispatch() {
    let (fixture, listener) = fixture().await;
    let (session, control) = fixture.session(5000);
    let mut request = request(&fixture);
    request.endpoint.port = request.endpoint.port.saturating_add(1);
    let failure = fixture.provider.start(&session, request).err().unwrap();
    assert_eq!(failure.code, StreamErrorCode::Denied);
    assert_eq!(
        control.budget.snapshot_at(Instant::now()).outbound_requests,
        0
    );
    assert_eq!(control.budget.host_memory_bytes(), 0);
    assert!(
        tokio::time::timeout(Duration::from_millis(50), listener.accept())
            .await
            .is_err()
    );
    drop(session);
    fixture.clean().await;
}

#[tokio::test]
async fn revoking_policy_prevents_application_write_on_existing_socket() {
    let (fixture, listener) = fixture().await;
    let (session, control) = fixture.session(5000);
    let stream = fixture
        .provider
        .start(&session, request(&fixture))
        .unwrap()
        .await
        .unwrap();
    let (mut peer, _) = listener.accept().await.unwrap();
    fixture
        .policies
        .mutate(
            MutationRequest {
                tenant: "a",
                actor: "operator",
                id: "p",
                kind: RecordKind::Policy,
                operation_id: "revoke",
                expected_revision: 2,
                document: None,
            },
            Instant::now() + Duration::from_secs(1),
            |_| Ok(()),
        )
        .unwrap();
    assert!(stream
        .write(b"NEVER".to_vec(), None)
        .unwrap()
        .await
        .is_err());
    assert!(!stream.inspect().application_write_attempted);
    assert_eq!(stream.inspect().accepted_write_bytes, 0);
    drop(stream);
    let mut bytes = Vec::new();
    peer.read_to_end(&mut bytes).await.unwrap();
    assert!(bytes.is_empty());
    assert_eq!(control.budget.host_memory_bytes(), 0);
    drop(session);
    fixture.clean().await;
}
