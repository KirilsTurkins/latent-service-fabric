//! These tests execute the maintained provider against actual TCP peers and
//! sealed broker sessions. They are native-provider evidence, separate from
//! the component and standard-library qualification gate.
use super::{config, fixture::Fixture};
use crate::StreamErrorCode;
use latent_capabilities::broker::network::{
    OutboundStreamInvoker, StreamConnectRequest, StreamInterest, StreamShutdown, StreamState,
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
    let control_session_bytes = control.native_session_bytes();
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
        received.extend_from_slice(&bytes);
    }
    assert_eq!(received, b"onetwo");
    assert_eq!(stream.inspect().state, StreamState::ReadEofWriteShut);
    assert_eq!(stream.inspect().accepted_write_bytes, 4);
    assert_eq!(stream.inspect().delivered_read_bytes, 6);
    assert!(stream.inspect().application_write_attempted);
    assert_eq!(stream.close().await.unwrap().state, StreamState::Closed);
    peer.await.unwrap();
    assert_eq!(control.budget.host_memory_bytes(), control_session_bytes);
    assert_eq!(fixture.provider.usage().unwrap().connections, 0);
    drop(session);
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();
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
    let control_session_bytes = control.native_session_bytes();
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
    assert!(first_bytes
        .iter()
        .chain(second_bytes.iter())
        .all(|b| *b == 0x5a));
    drop(first_bytes);
    drop(second_bytes);
    drop(first);
    drop(second);
    assert_eq!(control.budget.host_memory_bytes(), control_session_bytes);
    assert_eq!(fixture.pools.snapshot().unwrap().running_requests, 0);
    drop(session);
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();
}

#[tokio::test]
async fn dropped_facade_does_not_refund_an_unpolled_pending_socket() {
    let (fixture, listener) = fixture().await;
    let (session, control) = fixture.session(5000);
    let control_session_bytes = control.native_session_bytes();
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
    assert_eq!(control.budget.host_memory_bytes(), control_session_bytes);
    drop(session);
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();
}

#[tokio::test]
async fn dropped_write_before_dispatch_keeps_the_same_connection_usable() {
    use crate::connection::TestWritePoint;

    let (fixture, listener) = fixture().await;
    let (session, control) = fixture.session(5000);
    let stream = fixture
        .provider
        .start(&session, request(&fixture))
        .unwrap()
        .await
        .unwrap();
    let (mut peer, _) = listener.accept().await.unwrap();
    let owner = fixture
        .provider
        .inner
        .connections
        .snapshot(0)
        .unwrap()
        .unwrap();
    let (entered, release) = owner.test_write_gate(TestWritePoint::BeforeDispatch);
    drop(owner);
    let mut write = stream.write(b"NEVER".to_vec(), None).unwrap();
    tokio::select! {
        result = &mut write => panic!("write completed before the pre-dispatch gate: {result:?}"),
        reached = tokio::time::timeout(Duration::from_secs(1), entered) => reached.expect("test gate deadline").unwrap(),
    }
    drop(write);
    drop(release);
    assert_eq!(stream.inspect().state, StreamState::Open);
    assert!(!stream.inspect().application_write_attempted);
    assert_eq!(stream.inspect().accepted_write_bytes, 0);
    assert_eq!(fixture.provider.usage().unwrap().pending_operations, 0);
    assert_eq!(
        stream.write(b"LIVE".to_vec(), None).unwrap().await.unwrap(),
        4
    );
    let mut bytes = [0; 4];
    tokio::time::timeout(Duration::from_secs(1), peer.read_exact(&mut bytes))
        .await
        .expect("peer read deadline")
        .unwrap();
    assert_eq!(&bytes, b"LIVE");
    stream.close().await.unwrap();
    drop((peer, session));
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();
}

#[tokio::test]
async fn dropped_write_after_synthetic_no_progress_keeps_the_same_connection_usable() {
    use crate::connection::TestWritePoint;

    let (fixture, listener) = fixture().await;
    let (session, control) = fixture.session(5000);
    let stream = fixture
        .provider
        .start(&session, request(&fixture))
        .unwrap()
        .await
        .unwrap();
    let (mut peer, _) = listener.accept().await.unwrap();
    let owner = fixture
        .provider
        .inner
        .connections
        .snapshot(0)
        .unwrap()
        .unwrap();
    owner.test_write_none_once();
    let (entered, release) = owner.test_write_gate(TestWritePoint::NoProgress);
    drop(owner);
    let mut write = stream.write(b"NEVER".to_vec(), None).unwrap();
    tokio::select! {
        result = &mut write => panic!("write completed before no-progress gate: {result:?}"),
        reached = tokio::time::timeout(Duration::from_secs(1), entered) => reached.expect("test gate deadline").unwrap(),
    }
    drop(write);
    drop(release);
    assert_eq!(stream.inspect().state, StreamState::Open);
    assert!(stream.inspect().application_write_attempted);
    assert_eq!(stream.inspect().accepted_write_bytes, 0);
    assert_eq!(fixture.provider.usage().unwrap().pending_operations, 0);
    assert_eq!(
        stream.write(b"LIVE".to_vec(), None).unwrap().await.unwrap(),
        4
    );
    let mut bytes = [0; 4];
    tokio::time::timeout(Duration::from_secs(1), peer.read_exact(&mut bytes))
        .await
        .expect("peer read deadline")
        .unwrap();
    assert_eq!(&bytes, b"LIVE");
    stream.close().await.unwrap();
    drop((peer, session));
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();
}

#[tokio::test]
async fn dropped_write_during_synthetic_audit_wait_keeps_original_owners_and_never_replays() {
    use crate::connection::TestWritePoint;

    let (fixture, listener) = fixture().await;
    let (session, control) = fixture.session(5000);
    let baseline = control.native_session_bytes();
    let stream = fixture
        .provider
        .start(&session, request(&fixture))
        .unwrap()
        .await
        .unwrap();
    let (mut peer, _) = listener.accept().await.unwrap();
    let held_read = stream.read(1, None).unwrap();
    let owner = fixture
        .provider
        .inner
        .connections
        .snapshot(0)
        .unwrap()
        .unwrap();
    let (entered, release) = owner.test_write_gate(TestWritePoint::AuditPending);
    drop(owner);
    let mut write = stream.write(b"ONCE".to_vec(), None).unwrap();
    tokio::select! {
        result = &mut write => panic!("write completed before the audit gate: {result:?}"),
        reached = tokio::time::timeout(Duration::from_secs(1), entered) => reached.expect("test gate deadline").unwrap(),
    }
    let mut bytes = [0; 4];
    tokio::time::timeout(Duration::from_secs(1), peer.read_exact(&mut bytes))
        .await
        .expect("peer read deadline")
        .unwrap();
    assert_eq!(&bytes, b"ONCE");
    assert_eq!(stream.inspect().accepted_write_bytes, 4);
    assert_eq!(fixture.provider.usage().unwrap().pending_operations, 2);
    drop(write);
    drop(release);
    assert_eq!(stream.inspect().state, StreamState::Stopping);
    assert_eq!(stream.inspect().accepted_write_bytes, 4);
    assert!(stream.inspect().application_write_attempted);
    assert_eq!(fixture.provider.usage().unwrap().pending_operations, 1);
    assert_eq!(fixture.pools.snapshot().unwrap().connections, 1);
    assert!(control.budget.host_memory_bytes() > baseline);
    let mut copied = false;
    let failure = stream
        .write_from(1, None, &mut || {
            copied = true;
            Ok(vec![0])
        })
        .err()
        .unwrap();
    assert_eq!(failure.code, StreamErrorCode::Cancelled);
    assert!(failure.may_have_applied);
    assert!(!copied);
    drop(held_read);
    let mut byte = [0];
    assert_eq!(
        tokio::time::timeout(Duration::from_secs(1), peer.read(&mut byte))
            .await
            .unwrap()
            .unwrap(),
        0
    );
    assert_eq!(fixture.provider.usage().unwrap().connections, 0);
    assert!(
        tokio::time::timeout(Duration::from_millis(20), listener.accept())
            .await
            .is_err()
    );
    drop((peer, stream, session));
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();
}

#[tokio::test]
async fn synthetic_audit_failure_reports_the_accepted_prefix_once_and_fences_reuse() {
    let (fixture, listener) = fixture().await;
    let (session, control) = fixture.session(5000);
    let baseline = control.native_session_bytes();
    let stream = fixture
        .provider
        .start(&session, request(&fixture))
        .unwrap()
        .await
        .unwrap();
    let (mut peer, _) = listener.accept().await.unwrap();
    let held_read = stream.read(1, None).unwrap();
    let owner = fixture
        .provider
        .inner
        .connections
        .snapshot(0)
        .unwrap()
        .unwrap();
    owner.test_fail_audit_once();
    drop(owner);
    let failure = stream
        .write(b"ONCE".to_vec(), None)
        .unwrap()
        .await
        .err()
        .unwrap();
    assert_eq!(failure.code, StreamErrorCode::Uncertain);
    assert_eq!(failure.accepted_prefix_bytes, 4);
    assert!(failure.may_have_applied);
    assert_eq!(stream.inspect().accepted_write_bytes, 4);
    assert_eq!(stream.inspect().state, StreamState::Stopping);
    assert_eq!(fixture.provider.usage().unwrap().pending_operations, 1);
    assert_eq!(fixture.pools.snapshot().unwrap().connections, 1);
    assert!(control.budget.host_memory_bytes() > baseline);
    let mut bytes = [0; 4];
    tokio::time::timeout(Duration::from_secs(1), peer.read_exact(&mut bytes))
        .await
        .expect("peer read deadline")
        .unwrap();
    assert_eq!(&bytes, b"ONCE");
    assert!(stream.write(b"RETRY".to_vec(), None).is_err());
    drop(held_read);
    let mut byte = [0];
    assert_eq!(
        tokio::time::timeout(Duration::from_secs(1), peer.read(&mut byte))
            .await
            .unwrap()
            .unwrap(),
        0
    );
    assert_eq!(fixture.provider.usage().unwrap().connections, 0);
    drop((peer, stream, session));
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();
}

#[tokio::test]
async fn wrong_endpoint_is_denied_before_network_dispatch() {
    let (fixture, listener) = fixture().await;
    let (session, control) = fixture.session(5000);
    let control_session_bytes = control.native_session_bytes();
    let mut request = request(&fixture);
    request.endpoint.port = request.endpoint.port.saturating_add(1);
    let failure = fixture.provider.start(&session, request).err().unwrap();
    assert_eq!(failure.code, StreamErrorCode::Denied);
    assert_eq!(
        control.budget.snapshot_at(Instant::now()).outbound_requests,
        0
    );
    assert_eq!(control.budget.host_memory_bytes(), control_session_bytes);
    assert!(
        tokio::time::timeout(Duration::from_millis(50), listener.accept())
            .await
            .is_err()
    );
    drop(session);
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();
}

#[tokio::test]
async fn revoking_policy_prevents_application_write_on_existing_socket() {
    let (fixture, listener) = fixture().await;
    let (session, control) = fixture.session(5000);
    let control_session_bytes = control.native_session_bytes();
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
    assert_eq!(control.budget.host_memory_bytes(), control_session_bytes);
    drop(session);
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();
}

#[tokio::test]
async fn abort_both_wakes_read_and_keeps_the_held_write_owner_until_drop() {
    use std::{
        future::{poll_fn, Future},
        pin::Pin,
        task::Poll,
    };

    let (fixture, listener) = fixture().await;
    let (session, control) = fixture.session(5000);
    let baseline = control.native_session_bytes();
    let stream = fixture
        .provider
        .start(&session, request(&fixture))
        .unwrap()
        .await
        .unwrap();
    let (mut peer, _) = listener.accept().await.unwrap();
    assert_eq!(
        stream.write(b"PAID".to_vec(), None).unwrap().await.unwrap(),
        4
    );
    let mut received = [0; 4];
    peer.read_exact(&mut received).await.unwrap();
    assert_eq!(&received, b"PAID");
    let mut read = stream.read(1, None).unwrap();
    assert!(poll_fn(|cx| Poll::Ready(Pin::new(&mut read).poll(cx)))
        .await
        .is_pending());
    // The accepted but unpolled write owns its input and the original socket;
    // it never reaches the peer and holds the ordinary write slot.
    let write = stream.write(b"NEVER".to_vec(), None).unwrap();
    let abort = stream.shutdown(StreamShutdown::Both).unwrap();
    assert_eq!(fixture.provider.usage().unwrap().pending_operations, 3);
    assert_eq!(
        stream.shutdown(StreamShutdown::Both).err().unwrap().code,
        StreamErrorCode::InvalidState
    );
    assert_eq!(abort.await.unwrap().state, StreamState::Stopping);
    let failure = tokio::time::timeout(Duration::from_secs(1), read)
        .await
        .expect("local abort must wake the original read")
        .err()
        .unwrap();
    assert_eq!(failure.code, StreamErrorCode::Cancelled);
    assert!(failure.may_have_applied);
    assert_eq!(fixture.provider.usage().unwrap().pending_operations, 1);
    assert_eq!(fixture.pools.snapshot().unwrap().connections, 1);
    assert!(control.budget.host_memory_bytes() > baseline);
    assert!(stream.inspect().application_write_attempted);
    assert_eq!(stream.inspect().accepted_write_bytes, 4);
    drop(write);
    let mut byte = [0];
    assert_eq!(
        tokio::time::timeout(Duration::from_secs(1), peer.read(&mut byte))
            .await
            .expect("the original socket must close after its last owner")
            .unwrap(),
        0
    );
    assert_eq!(fixture.provider.usage().unwrap().connections, 0);
    drop((peer, stream, session));
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();
}

#[tokio::test]
async fn abort_both_is_available_after_the_send_half_was_closed() {
    let (fixture, listener) = fixture().await;
    let (session, control) = fixture.session(5000);
    let baseline = control.native_session_bytes();
    let stream = fixture
        .provider
        .start(&session, request(&fixture))
        .unwrap()
        .await
        .unwrap();
    let (mut peer, _) = listener.accept().await.unwrap();
    assert_eq!(
        stream
            .shutdown(StreamShutdown::Send)
            .unwrap()
            .await
            .unwrap()
            .state,
        StreamState::WriteShut
    );
    assert_eq!(
        stream
            .shutdown(StreamShutdown::Both)
            .unwrap()
            .await
            .unwrap()
            .state,
        StreamState::Closed
    );
    let mut byte = [0];
    assert_eq!(peer.read(&mut byte).await.unwrap(), 0);
    assert_eq!(fixture.provider.usage().unwrap().connections, 0);
    drop((peer, stream));
    assert_eq!(control.budget.host_memory_bytes(), baseline);
    drop(session);
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();
}

#[tokio::test]
async fn abort_both_unpolled_reserves_control_and_blocks_new_send_without_dispatch() {
    let (fixture, listener) = fixture().await;
    let (session, control) = fixture.session(5000);
    let stream = fixture
        .provider
        .start(&session, request(&fixture))
        .unwrap()
        .await
        .unwrap();
    let (mut peer, _) = listener.accept().await.unwrap();
    let abort = stream.shutdown(StreamShutdown::Both).unwrap();
    assert_eq!(
        stream.write(b"X".to_vec(), None).err().unwrap().code,
        StreamErrorCode::InvalidState
    );
    assert_eq!(
        stream.shutdown(StreamShutdown::Send).err().unwrap().code,
        StreamErrorCode::InvalidState
    );
    drop(abort);
    assert_eq!(stream.inspect().state, StreamState::Open);
    assert_eq!(stream.write(b"X".to_vec(), None).unwrap().await.unwrap(), 1);
    let mut byte = [0];
    peer.read_exact(&mut byte).await.unwrap();
    assert_eq!(byte, *b"X");
    stream.close().await.unwrap();
    drop((peer, session));
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();
}

#[tokio::test]
async fn abort_both_cancels_an_accepted_send_shutdown_owner() {
    let (fixture, listener) = fixture().await;
    let (session, control) = fixture.session(5000);
    let baseline = control.native_session_bytes();
    let stream = fixture
        .provider
        .start(&session, request(&fixture))
        .unwrap()
        .await
        .unwrap();
    let (mut peer, _) = listener.accept().await.unwrap();
    // Acceptance owns the send slot and original transport before polling;
    // no kernel send-shutdown has been dispatched by this owner yet.
    let send = stream.shutdown(StreamShutdown::Send).unwrap();
    let abort = stream.shutdown(StreamShutdown::Both).unwrap();
    assert_eq!(fixture.provider.usage().unwrap().pending_operations, 2);
    assert_eq!(abort.await.unwrap().state, StreamState::Stopping);
    assert_eq!(fixture.provider.usage().unwrap().pending_operations, 1);
    assert_eq!(fixture.pools.snapshot().unwrap().connections, 1);
    assert!(control.budget.host_memory_bytes() > baseline);
    let failure = tokio::time::timeout(Duration::from_secs(1), send)
        .await
        .expect("the accepted send owner must retire after local abort")
        .err()
        .unwrap();
    assert_eq!(failure.code, StreamErrorCode::Cancelled);
    assert!(!failure.may_have_applied);
    let mut byte = [0];
    assert_eq!(
        tokio::time::timeout(Duration::from_secs(1), peer.read(&mut byte))
            .await
            .expect("the original socket must close after the send owner")
            .unwrap(),
        0
    );
    assert_eq!(fixture.provider.usage().unwrap().connections, 0);
    drop((peer, stream, session));
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();
}

#[tokio::test]
async fn dropped_read_after_consumption_fences_reuse_and_retains_pending_owner() {
    use crate::connection::TestWritePoint;

    let (fixture, listener) = fixture().await;
    let (session, control) = fixture.session(5000);
    let baseline = control.native_session_bytes();
    let stream = fixture
        .provider
        .start(&session, request(&fixture))
        .unwrap()
        .await
        .unwrap();
    let (mut peer, _) = listener.accept().await.unwrap();
    let held_write = stream.write(b"held".to_vec(), None).unwrap();
    let owner = fixture
        .provider
        .inner
        .connections
        .snapshot(0)
        .unwrap()
        .unwrap();
    let (entered, release) = owner.test_write_gate(TestWritePoint::AuditPending);
    drop(owner);
    peer.write_all(b"X").await.unwrap();
    let mut read = stream.read(1, None).unwrap();
    tokio::select! {
        _ = &mut read => panic!("read completed before audit gate"),
        reached = tokio::time::timeout(Duration::from_secs(1), entered) => reached.expect("test gate deadline").unwrap(),
    }
    assert_eq!(stream.inspect().delivered_read_bytes, 1);
    assert_eq!(fixture.provider.usage().unwrap().pending_operations, 2);
    drop(read);
    drop(release);
    assert_eq!(stream.inspect().state, StreamState::Stopping);
    assert_eq!(fixture.provider.usage().unwrap().pending_operations, 1);
    assert_eq!(fixture.pools.snapshot().unwrap().connections, 1);
    assert!(control.budget.host_memory_bytes() > baseline);
    assert_eq!(
        stream.read(1, None).err().unwrap().code,
        StreamErrorCode::Cancelled
    );
    drop(held_write);
    let mut byte = [0];
    assert_eq!(
        tokio::time::timeout(Duration::from_secs(1), peer.read(&mut byte))
            .await
            .unwrap()
            .unwrap(),
        0
    );
    assert_eq!(fixture.provider.usage().unwrap().connections, 0);
    drop((peer, stream, session));
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();
}

#[tokio::test]
async fn failed_read_audit_fences_reuse_after_consuming_bytes() {
    let (fixture, listener) = fixture().await;
    let (session, control) = fixture.session(5000);
    let stream = fixture
        .provider
        .start(&session, request(&fixture))
        .unwrap()
        .await
        .unwrap();
    let (mut peer, _) = listener.accept().await.unwrap();
    let held_write = stream.write(b"held".to_vec(), None).unwrap();
    let owner = fixture
        .provider
        .inner
        .connections
        .snapshot(0)
        .unwrap()
        .unwrap();
    owner.test_fail_audit_once();
    drop(owner);
    peer.write_all(b"X").await.unwrap();
    let failure = stream.read(1, None).unwrap().await.err().unwrap();
    assert_eq!(failure.code, StreamErrorCode::Uncertain);
    assert_eq!(stream.inspect().delivered_read_bytes, 1);
    assert_eq!(stream.inspect().state, StreamState::Stopping);
    assert_eq!(fixture.provider.usage().unwrap().pending_operations, 1);
    assert!(stream.read(1, None).is_err());
    drop(held_write);
    let mut byte = [0];
    assert_eq!(
        tokio::time::timeout(Duration::from_secs(1), peer.read(&mut byte))
            .await
            .unwrap()
            .unwrap(),
        0
    );
    drop((peer, stream, session));
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();
}

#[tokio::test]
async fn dropped_read_before_consumption_keeps_connection_usable() {
    use std::{
        future::{poll_fn, Future},
        pin::Pin,
        task::Poll,
    };

    let (fixture, listener) = fixture().await;
    let (session, control) = fixture.session(5000);
    let stream = fixture
        .provider
        .start(&session, request(&fixture))
        .unwrap()
        .await
        .unwrap();
    let (mut peer, _) = listener.accept().await.unwrap();
    let mut read = stream.read(1, None).unwrap();
    assert!(poll_fn(|cx| Poll::Ready(Pin::new(&mut read).poll(cx)))
        .await
        .is_pending());
    drop(read);
    assert_eq!(stream.inspect().state, StreamState::Open);
    peer.write_all(b"X").await.unwrap();
    let mut output = stream.read(1, None).unwrap().await.unwrap().unwrap();
    let bytes = output.copy_bytes().unwrap();
    assert_eq!(bytes.as_ref(), b"X");
    drop(bytes);
    drop(output);
    stream.close().await.unwrap();
    drop((peer, session));
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();
}

#[tokio::test]
async fn dropped_read_after_socket_consumption_fences_before_currentness_return() {
    use crate::connection::TestWritePoint;

    let (fixture, listener) = fixture().await;
    let (session, control) = fixture.session(5000);
    let stream = fixture
        .provider
        .start(&session, request(&fixture))
        .unwrap()
        .await
        .unwrap();
    let (mut peer, _) = listener.accept().await.unwrap();
    let held_write = stream.write(b"held".to_vec(), None).unwrap();
    let owner = fixture
        .provider
        .inner
        .connections
        .snapshot(0)
        .unwrap()
        .unwrap();
    let (entered, release) = owner.test_write_gate(TestWritePoint::ReadConsumed);
    drop(owner);
    peer.write_all(b"X").await.unwrap();
    let mut read = stream.read(1, None).unwrap();
    tokio::select! {
        _ = &mut read => panic!("read completed before consumption gate"),
        reached = tokio::time::timeout(Duration::from_secs(1), entered) => reached.expect("test gate deadline").unwrap(),
    }
    assert_eq!(stream.inspect().delivered_read_bytes, 0);
    drop(read);
    drop(release);
    assert_eq!(stream.inspect().state, StreamState::Stopping);
    assert_eq!(fixture.provider.usage().unwrap().pending_operations, 1);
    assert!(stream.read(1, None).is_err());
    drop(held_write);
    let mut byte = [0];
    assert_eq!(
        tokio::time::timeout(Duration::from_secs(1), peer.read(&mut byte))
            .await
            .unwrap()
            .unwrap(),
        0
    );
    drop((peer, stream, session));
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();
}

#[tokio::test]
async fn readiness_observation_timeout_keeps_the_same_plain_tcp_owner() {
    let (fixture, listener) = fixture().await;
    let (session, control) = fixture.session(5000);
    let baseline = control.native_session_bytes();
    let stream = fixture
        .provider
        .start(&session, request(&fixture))
        .unwrap()
        .await
        .unwrap();
    let (mut peer, _) = listener.accept().await.unwrap();

    // A prior write remains a real possible external effect, even though the
    // subsequent readiness observation does not consume or submit bytes.
    assert_eq!(stream.write(b"X".to_vec(), None).unwrap().await.unwrap(), 1);
    let mut sent = [0];
    peer.read_exact(&mut sent).await.unwrap();
    assert_eq!(&sent, b"X");
    let failure = stream
        .ready(StreamInterest::Readable, Some(30))
        .unwrap()
        .await
        .err()
        .unwrap();
    assert_eq!(failure.code, StreamErrorCode::Timeout);
    assert!(failure.may_have_applied);
    assert_eq!(failure.accepted_prefix_bytes, 0);
    assert_eq!(stream.inspect().state, StreamState::Open);
    assert_eq!(fixture.provider.usage().unwrap().connections, 1);
    assert_eq!(fixture.provider.usage().unwrap().pending_operations, 0);
    assert!(control.budget.host_memory_bytes() > baseline);

    peer.write_all(b"Y").await.unwrap();
    let mut chunk = stream.read(1, None).unwrap().await.unwrap().unwrap();
    assert_eq!(chunk.copy_bytes().unwrap().as_ref(), b"Y");
    drop(chunk);
    stream.close().await.unwrap();
    drop((peer, session));
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();
}

#[cfg(target_os = "linux")]
#[tokio::test]
async fn readiness_observation_zero_checks_real_socket_without_closing_it() {
    let (fixture, listener) = fixture().await;
    let (session, control) = fixture.session(5000);
    let baseline = control.native_session_bytes();
    let stream = fixture
        .provider
        .start(&session, request(&fixture))
        .unwrap()
        .await
        .unwrap();
    let (mut peer, _) = listener.accept().await.unwrap();

    let failure = stream
        .ready(StreamInterest::Readable, Some(0))
        .unwrap()
        .await
        .err()
        .unwrap();
    assert_eq!(failure.code, StreamErrorCode::Timeout);
    assert!(!failure.may_have_applied);
    assert_eq!(stream.inspect().state, StreamState::Open);
    assert_eq!(fixture.provider.usage().unwrap().connections, 1);
    assert_eq!(fixture.provider.usage().unwrap().pending_operations, 0);
    assert!(control.budget.host_memory_bytes() > baseline);

    assert!(
        stream
            .ready(StreamInterest::Writable, Some(0))
            .unwrap()
            .await
            .unwrap()
            .writable
    );
    peer.write_all(b"Z").await.unwrap();
    assert!(
        stream
            .ready(StreamInterest::Readable, None)
            .unwrap()
            .await
            .unwrap()
            .readable
    );
    assert!(
        stream
            .ready(StreamInterest::Readable, Some(0))
            .unwrap()
            .await
            .unwrap()
            .readable
    );
    let mut chunk = stream.read(1, None).unwrap().await.unwrap().unwrap();
    assert_eq!(chunk.copy_bytes().unwrap().as_ref(), b"Z");
    drop(chunk);
    peer.shutdown().await.unwrap();
    assert!(
        stream
            .ready(StreamInterest::Readable, None)
            .unwrap()
            .await
            .unwrap()
            .readable
    );
    assert!(
        stream
            .ready(StreamInterest::Readable, Some(0))
            .unwrap()
            .await
            .unwrap()
            .readable
    );
    assert!(stream.read(1, None).unwrap().await.unwrap().is_none());
    stream.close().await.unwrap();
    drop((peer, session));
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();
}

#[tokio::test]
async fn readiness_observation_revocation_during_audit_is_terminal() {
    use crate::connection::TestWritePoint;

    let (fixture, listener) = fixture().await;
    let (session, control) = fixture.session(5000);
    let stream = fixture
        .provider
        .start(&session, request(&fixture))
        .unwrap()
        .await
        .unwrap();
    let (mut peer, _) = listener.accept().await.unwrap();
    let owner = fixture
        .provider
        .inner
        .connections
        .snapshot(0)
        .unwrap()
        .unwrap();
    let (entered, release) = owner.test_write_gate(TestWritePoint::AuditPending);
    drop(owner);
    let mut ready = stream.ready(StreamInterest::Readable, Some(10)).unwrap();
    tokio::select! {
        result = &mut ready => panic!("observation completed before audit gate: {result:?}"),
        reached = tokio::time::timeout(Duration::from_secs(1), entered) => reached.unwrap().unwrap(),
    }
    fixture
        .policies
        .mutate(
            MutationRequest {
                tenant: "a",
                actor: "operator",
                id: "p",
                kind: RecordKind::Policy,
                operation_id: "revoke-ready",
                expected_revision: 2,
                document: None,
            },
            Instant::now() + Duration::from_secs(1),
            |_| Ok(()),
        )
        .unwrap();
    release.send(()).unwrap();
    let failure = ready.await.err().unwrap();
    assert_eq!(failure.code, StreamErrorCode::Denied);
    assert_ne!(stream.inspect().state, StreamState::Open);
    drop(stream);
    let mut byte = [0];
    assert_eq!(
        tokio::time::timeout(Duration::from_secs(1), peer.read(&mut byte))
            .await
            .unwrap()
            .unwrap(),
        0
    );
    drop((peer, session));
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();
}

#[tokio::test]
async fn readiness_observation_root_cancel_during_audit_is_terminal() {
    use crate::connection::TestWritePoint;
    use std::sync::atomic::Ordering;

    let (fixture, listener) = fixture().await;
    let (session, control) = fixture.session(5000);
    let stream = fixture
        .provider
        .start(&session, request(&fixture))
        .unwrap()
        .await
        .unwrap();
    let (mut peer, _) = listener.accept().await.unwrap();
    let owner = fixture
        .provider
        .inner
        .connections
        .snapshot(0)
        .unwrap()
        .unwrap();
    let (entered, release) = owner.test_write_gate(TestWritePoint::AuditPending);
    drop(owner);
    let mut ready = stream.ready(StreamInterest::Readable, Some(10)).unwrap();
    tokio::select! {
        result = &mut ready => panic!("observation completed before audit gate: {result:?}"),
        reached = tokio::time::timeout(Duration::from_secs(1), entered) => reached.unwrap().unwrap(),
    }
    control.probe.0.store(true, Ordering::Release);
    release.send(()).unwrap();
    let failure = ready.await.err().unwrap();
    assert_eq!(failure.code, StreamErrorCode::Cancelled);
    assert_ne!(stream.inspect().state, StreamState::Open);
    drop(stream);
    let mut byte = [0];
    assert_eq!(
        tokio::time::timeout(Duration::from_secs(1), peer.read(&mut byte))
            .await
            .unwrap()
            .unwrap(),
        0
    );
    drop((peer, session));
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();
}

#[cfg(target_os = "linux")]
#[tokio::test]
async fn readiness_observation_zero_success_revoked_during_audit_is_terminal() {
    use crate::connection::TestWritePoint;

    let (fixture, listener) = fixture().await;
    let (session, control) = fixture.session(5000);
    let stream = fixture
        .provider
        .start(&session, request(&fixture))
        .unwrap()
        .await
        .unwrap();
    let (mut peer, _) = listener.accept().await.unwrap();
    peer.write_all(b"Z").await.unwrap();
    assert!(
        stream
            .ready(StreamInterest::Readable, None)
            .unwrap()
            .await
            .unwrap()
            .readable
    );
    let owner = fixture
        .provider
        .inner
        .connections
        .snapshot(0)
        .unwrap()
        .unwrap();
    let (entered, release) = owner.test_write_gate(TestWritePoint::AuditPending);
    drop(owner);
    let mut ready = stream.ready(StreamInterest::Readable, Some(0)).unwrap();
    tokio::select! {
        result = &mut ready => panic!("zero observation completed before audit gate: {result:?}"),
        reached = tokio::time::timeout(Duration::from_secs(1), entered) => reached.unwrap().unwrap(),
    }
    fixture
        .policies
        .mutate(
            MutationRequest {
                tenant: "a",
                actor: "operator",
                id: "p",
                kind: RecordKind::Policy,
                operation_id: "revoke-zero-ready",
                expected_revision: 2,
                document: None,
            },
            Instant::now() + Duration::from_secs(1),
            |_| Ok(()),
        )
        .unwrap();
    release.send(()).unwrap();
    assert_eq!(ready.await.err().unwrap().code, StreamErrorCode::Denied);
    assert_ne!(stream.inspect().state, StreamState::Open);
    drop((peer, stream, session));
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();
}

#[tokio::test]
async fn readiness_observation_dropped_during_audit_fences_original_owner() {
    use crate::connection::TestWritePoint;

    let (fixture, listener) = fixture().await;
    let (session, control) = fixture.session(5000);
    let stream = fixture
        .provider
        .start(&session, request(&fixture))
        .unwrap()
        .await
        .unwrap();
    let (mut peer, _) = listener.accept().await.unwrap();
    let owner = fixture
        .provider
        .inner
        .connections
        .snapshot(0)
        .unwrap()
        .unwrap();
    let (entered, release) = owner.test_write_gate(TestWritePoint::AuditPending);
    drop(owner);
    let mut ready = stream.ready(StreamInterest::Readable, Some(10)).unwrap();
    tokio::select! {
        result = &mut ready => panic!("observation completed before audit gate: {result:?}"),
        reached = tokio::time::timeout(Duration::from_secs(1), entered) => reached.unwrap().unwrap(),
    }
    drop(ready);
    drop(release);
    assert_ne!(stream.inspect().state, StreamState::Open);
    assert!(stream.ready(StreamInterest::Readable, None).is_err());
    drop(stream);
    let mut byte = [0];
    assert_eq!(
        tokio::time::timeout(Duration::from_secs(1), peer.read(&mut byte))
            .await
            .unwrap()
            .unwrap(),
        0
    );
    drop((peer, session));
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();
}
