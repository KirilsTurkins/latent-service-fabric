//! Local abort controls on real, version-pinned TLS peers. These use the
//! accounting-only fixture, not production installation or kernel retirement proof.
use super::{request, Fixture, Peer};
use crate::StreamErrorCode;
use latent_capabilities::broker::{
    network::{OutboundStream, OutboundStreamInvoker, StreamInterest, StreamShutdown, StreamState},
    CapabilitySession,
};
use rustls_upstream as rustls;
use std::{
    future::{poll_fn, Future},
    pin::Pin,
    task::Poll,
    time::Duration,
};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::TcpStream,
};
use tokio_rustls::server::TlsStream;

fn versions() -> [(
    &'static rustls::SupportedProtocolVersion,
    rustls::ProtocolVersion,
); 2] {
    [
        (&rustls::version::TLS12, rustls::ProtocolVersion::TLSv1_2),
        (&rustls::version::TLS13, rustls::ProtocolVersion::TLSv1_3),
    ]
}

async fn connect_peer(
    peer: &Peer,
    fixture: &Fixture,
    session: &CapabilitySession,
    expected: rustls::ProtocolVersion,
) -> (Box<dyn OutboundStream>, TlsStream<TcpStream>) {
    let connect = fixture.provider.start(session, request(fixture)).unwrap();
    let (stream, server) = tokio::time::timeout(Duration::from_secs(2), async {
        tokio::join!(connect, async {
            let (socket, _) = peer.listener.accept().await.unwrap();
            peer.acceptor.accept(socket).await.unwrap()
        })
    })
    .await
    .expect("both original TLS handshake owners must complete");
    assert_eq!(server.get_ref().1.protocol_version(), Some(expected));
    (stream.unwrap(), server)
}

async fn assert_pending<F: Future + Unpin>(future: &mut F) {
    assert!(poll_fn(|cx| Poll::Ready(Pin::new(&mut *future).poll(cx)))
        .await
        .is_pending());
}

async fn assert_aborted_wire(server: &mut TlsStream<TcpStream>) {
    // The handshake and any successful application write have already been
    // consumed. Read the raw wire so even an unexpected encrypted close-notify
    // is visible: Both must abort locally, not dispatch a graceful TLS shutdown.
    let mut byte = [0];
    assert_eq!(
        tokio::time::timeout(Duration::from_secs(1), server.get_mut().0.read(&mut byte))
            .await
            .expect("the last original transport owner must close the socket")
            .unwrap(),
        0
    );
}

#[tokio::test]
async fn dropped_write_with_synthetically_held_tls_ciphertext_retains_original_owners() {
    use crate::connection::TestWritePoint;

    for (version, expected) in versions() {
        let peer = Peer::with_versions(&[version]).await;
        let fixture = Fixture::for_tls_accounting(peer.config());
        let (session, control) = fixture.session(5000);
        let baseline = control.native_session_bytes();
        let (stream, mut server) = connect_peer(&peer, &fixture, &session, expected).await;
        let held_read = stream.read(1, None).unwrap();
        let owner = fixture
            .provider
            .inner
            .connections
            .snapshot(0)
            .unwrap()
            .unwrap();
        // This test-only wire stall keeps real accepted ciphertext inside the
        // same rustls connection; it does not claim kernel backpressure.
        owner.test_hold_tls_flush();
        let (entered, release) = owner.test_write_gate(TestWritePoint::FlushPending);
        drop(owner);
        let mut write = stream.write(b"ONCE".to_vec(), None).unwrap();
        tokio::select! {
            result = &mut write => panic!("write completed before the TLS flush gate: {result:?}"),
            reached = tokio::time::timeout(Duration::from_secs(1), entered) => reached.expect("test gate deadline").unwrap(),
        }
        assert_eq!(stream.inspect().accepted_write_bytes, 0);
        assert_eq!(fixture.provider.usage().unwrap().pending_operations, 2);
        drop(write);
        drop(release);
        assert_eq!(stream.inspect().state, StreamState::Stopping);
        assert_eq!(stream.inspect().accepted_write_bytes, 4);
        assert!(stream.inspect().application_write_attempted);
        assert_eq!(fixture.provider.usage().unwrap().pending_operations, 1);
        assert_eq!(fixture.pools.snapshot().unwrap().connections, 1);
        assert!(control.budget.host_memory_bytes() > baseline);
        let failure = stream.write(b"RETRY".to_vec(), None).err().unwrap();
        assert_eq!(failure.code, StreamErrorCode::Cancelled);
        assert!(failure.may_have_applied);
        drop(held_read);
        assert_aborted_wire(&mut server).await;
        assert_eq!(fixture.provider.usage().unwrap().connections, 0);
        assert!(
            tokio::time::timeout(Duration::from_millis(20), peer.listener.accept())
                .await
                .is_err()
        );
        drop((server, stream, session));
        fixture.clean().await;
        drop(fixture);
        control.assert_native_settled();
    }
}

#[tokio::test]
async fn abort_both_wakes_tls_waiters_and_retains_held_write() {
    for (version, expected) in versions() {
        for attempted in [false, true] {
            let peer = Peer::with_versions(&[version]).await;
            let fixture = Fixture::for_tls_accounting(peer.config());
            let (session, control) = fixture.session(5000);
            let baseline = control.native_session_bytes();
            let (stream, mut server) = connect_peer(&peer, &fixture, &session, expected).await;
            if attempted {
                assert_eq!(
                    stream.write(b"PAID".to_vec(), None).unwrap().await.unwrap(),
                    4
                );
                let mut received = [0; 4];
                server.read_exact(&mut received).await.unwrap();
                assert_eq!(&received, b"PAID");
            }
            let mut read = stream.read(1, None).unwrap();
            assert_pending(&mut read).await;
            let mut ready = stream.ready(StreamInterest::Readable, None).unwrap();
            assert_pending(&mut ready).await;
            // Accepted but deliberately unpolled: this owner holds the input
            // and send slot without claiming a dispatched ciphertext/FIN race.
            let write = stream.write(b"NEVER".to_vec(), None).unwrap();
            let abort = stream.shutdown(StreamShutdown::Both).unwrap();
            assert_eq!(fixture.provider.usage().unwrap().pending_operations, 4);
            assert_eq!(
                stream.shutdown(StreamShutdown::Both).err().unwrap().code,
                StreamErrorCode::InvalidState
            );
            assert_eq!(
                tokio::time::timeout(Duration::from_secs(1), abort)
                    .await
                    .expect("abort must not wait for the held send owner")
                    .unwrap()
                    .state,
                StreamState::Stopping
            );
            let failure = tokio::time::timeout(Duration::from_secs(1), read)
                .await
                .expect("local abort must wake the original TLS read")
                .err()
                .unwrap();
            assert_eq!(failure.code, StreamErrorCode::Cancelled);
            assert_eq!(failure.may_have_applied, attempted);
            let failure = tokio::time::timeout(Duration::from_secs(1), ready)
                .await
                .expect("local abort must wake the original readiness owner")
                .err()
                .unwrap();
            assert_eq!(failure.code, StreamErrorCode::Cancelled);
            assert_eq!(failure.may_have_applied, attempted);
            assert_eq!(fixture.provider.usage().unwrap().pending_operations, 1);
            assert_eq!(fixture.pools.snapshot().unwrap().connections, 1);
            assert!(control.budget.host_memory_bytes() > baseline);
            assert_eq!(stream.inspect().application_write_attempted, attempted);
            assert_eq!(
                stream.inspect().accepted_write_bytes,
                if attempted { 4 } else { 0 }
            );
            drop(stream);
            assert_eq!(fixture.pools.snapshot().unwrap().connections, 1);
            assert!(control.budget.host_memory_bytes() > baseline);
            drop(write);
            assert_aborted_wire(&mut server).await;
            assert_eq!(fixture.provider.usage().unwrap().pending_operations, 0);
            assert_eq!(fixture.provider.usage().unwrap().connections, 0);
            assert_eq!(control.budget.host_memory_bytes(), baseline);
            assert!(
                tokio::time::timeout(Duration::from_millis(20), peer.listener.accept())
                    .await
                    .is_err()
            );
            drop((server, session));
            fixture.clean().await;
            drop(fixture);
            control.assert_native_settled();
        }
    }
}

#[tokio::test]
async fn abort_both_unpolled_tls_control_releases_slot_without_dispatch() {
    for (version, expected) in versions() {
        let peer = Peer::with_versions(&[version]).await;
        let fixture = Fixture::for_tls_accounting(peer.config());
        let (session, control) = fixture.session(5000);
        let baseline = control.native_session_bytes();
        let (stream, mut server) = connect_peer(&peer, &fixture, &session, expected).await;
        let connected_bytes = control.budget.host_memory_bytes();
        let abort = stream.shutdown(StreamShutdown::Both).unwrap();
        let mut produced = false;
        assert_eq!(
            stream
                .write_from(1, None, &mut || {
                    produced = true;
                    Ok(vec![0])
                })
                .err()
                .unwrap()
                .code,
            StreamErrorCode::InvalidState
        );
        assert!(!produced);
        for how in [StreamShutdown::Send, StreamShutdown::Receive] {
            assert_eq!(
                stream.shutdown(how).err().unwrap().code,
                StreamErrorCode::Unsupported
            );
        }
        assert_eq!(
            stream.shutdown(StreamShutdown::Both).err().unwrap().code,
            StreamErrorCode::InvalidState
        );
        assert_eq!(fixture.provider.usage().unwrap().pending_operations, 1);
        drop(abort);
        assert_eq!(fixture.provider.usage().unwrap().pending_operations, 0);
        assert_eq!(stream.inspect().state, StreamState::Open);
        assert!(!stream.inspect().application_write_attempted);
        assert_eq!(control.budget.host_memory_bytes(), connected_bytes);
        assert_eq!(
            stream.write(b"LIVE".to_vec(), None).unwrap().await.unwrap(),
            4
        );
        let mut received = [0; 4];
        server.read_exact(&mut received).await.unwrap();
        assert_eq!(&received, b"LIVE");
        assert_eq!(
            stream
                .shutdown(StreamShutdown::Both)
                .unwrap()
                .await
                .unwrap()
                .state,
            StreamState::Closed
        );
        assert_aborted_wire(&mut server).await;
        assert_eq!(fixture.provider.usage().unwrap().connections, 0);
        drop(stream);
        assert_eq!(control.budget.host_memory_bytes(), baseline);
        drop((server, session));
        fixture.clean().await;
        drop(fixture);
        control.assert_native_settled();
    }
}

#[tokio::test]
async fn abort_both_after_tls_peer_close_notify_retires_original_owner() {
    for (version, expected) in versions() {
        let peer = Peer::with_versions(&[version]).await;
        let fixture = Fixture::for_tls_accounting(peer.config());
        let (session, control) = fixture.session(5000);
        let baseline = control.native_session_bytes();
        let (stream, mut server) = connect_peer(&peer, &fixture, &session, expected).await;
        server.shutdown().await.unwrap();
        assert!(stream.read(1, None).unwrap().await.unwrap().is_none());
        assert_eq!(stream.inspect().state, StreamState::ReadEof);
        assert!(!stream.inspect().application_write_attempted);
        assert_eq!(
            stream.shutdown(StreamShutdown::Send).err().unwrap().code,
            StreamErrorCode::Unsupported
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
        assert_aborted_wire(&mut server).await;
        assert_eq!(fixture.provider.usage().unwrap().pending_operations, 0);
        assert_eq!(fixture.provider.usage().unwrap().connections, 0);
        drop(stream);
        assert_eq!(control.budget.host_memory_bytes(), baseline);
        drop((server, session));
        fixture.clean().await;
        drop(fixture);
        control.assert_native_settled();
    }
}

#[tokio::test]
async fn abort_both_cancels_tls_ciphertext_flush_under_real_backpressure() {
    for (version, expected) in versions() {
        let peer = Peer::with_versions(&[version]).await;
        let fixture = Fixture::for_tls_accounting(peer.config());
        let (session, control) = fixture.session(5000);
        let baseline = control.native_session_bytes();
        let (stream, mut server) = connect_peer(&peer, &fixture, &session, expected).await;
        socket2::SockRef::from(server.get_ref().0)
            .set_recv_buffer_size(16 * 1024)
            .unwrap();
        // The peer deliberately stops reading. Keep the original future when
        // its accepted plaintext cannot finish flushing to the real TCP wire.
        let mut completed = 0_u64;
        let mut blocked = None;
        for _ in 0..24 {
            let mut write = stream.write(vec![0x5a; 16 * 1024], None).unwrap();
            if let Ok(result) = tokio::time::timeout(Duration::from_millis(20), &mut write).await {
                completed += u64::from(result.unwrap());
            } else {
                blocked = Some(write);
                break;
            }
        }
        let blocked = blocked.expect("the non-reading TLS peer must apply real backpressure");
        assert!(completed > 0);
        assert_eq!(fixture.provider.usage().unwrap().pending_operations, 1);
        assert_eq!(stream.inspect().accepted_write_bytes, completed);
        assert!(stream.inspect().application_write_attempted);
        let abort = stream.shutdown(StreamShutdown::Both).unwrap();
        assert_eq!(fixture.provider.usage().unwrap().pending_operations, 2);
        assert_eq!(
            tokio::time::timeout(Duration::from_secs(1), abort)
                .await
                .expect("abort must not wait for ciphertext or the non-reading peer")
                .unwrap()
                .state,
            StreamState::Stopping
        );
        assert_eq!(fixture.provider.usage().unwrap().pending_operations, 1);
        assert_eq!(fixture.pools.snapshot().unwrap().connections, 1);
        assert!(control.budget.host_memory_bytes() > baseline);
        let failure = tokio::time::timeout(Duration::from_secs(1), blocked)
            .await
            .expect("the original ciphertext flush must observe local cancellation")
            .unwrap_err();
        assert_eq!(failure.code, StreamErrorCode::Cancelled);
        assert!(failure.may_have_applied);
        // A nonzero plaintext prefix proves this was an actually dispatched
        // TLS write, not merely an accepted future waiting for authorization.
        assert!(failure.accepted_prefix_bytes > 0);
        assert!(failure.accepted_prefix_bytes <= 16 * 1024);
        let accepted = completed + u64::from(failure.accepted_prefix_bytes);
        assert_eq!(stream.inspect().accepted_write_bytes, accepted);
        assert_eq!(fixture.provider.usage().unwrap().pending_operations, 0);
        assert_eq!(fixture.provider.usage().unwrap().connections, 0);
        let received = tokio::time::timeout(Duration::from_secs(2), async {
            let mut received = 0_u64;
            let mut bytes = [0; 16 * 1024];
            loop {
                match server.read(&mut bytes).await {
                    Ok(0) => panic!("local abort must not emit a TLS close-notify"),
                    Ok(count) => {
                        assert!(bytes[..count].iter().all(|byte| *byte == 0x5a));
                        received += count as u64;
                        assert!(received <= accepted, "no plaintext replay after abort");
                    }
                    Err(failure) => {
                        assert_eq!(failure.kind(), std::io::ErrorKind::UnexpectedEof);
                        return received;
                    }
                }
            }
        })
        .await
        .expect("the peer must observe original socket closure without a graceful alert");
        assert!(received >= completed);
        assert!(
            tokio::time::timeout(Duration::from_millis(20), peer.listener.accept())
                .await
                .is_err()
        );
        drop(stream);
        assert_eq!(control.budget.host_memory_bytes(), baseline);
        drop((server, session));
        fixture.clean().await;
        drop(fixture);
        control.assert_native_settled();
    }
}
