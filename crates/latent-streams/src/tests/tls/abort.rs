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

fn versions() -> [(&'static rustls::SupportedProtocolVersion, rustls::ProtocolVersion); 2] {
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
