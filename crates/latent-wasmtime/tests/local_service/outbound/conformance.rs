//! Shared signed-node negatives. The encoded guest is deliberately not credited
//! as an ordinary language client, protocol parser or kernel final-free probe.
use super::{configured, failure, idle, success};
use crate::fixture::Fixture;
use latent_activation::ActivationOutcome;
use latent_core::PlatformErrorCode;
use latent_node::ActivationReceipt;
use std::time::Duration;
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::TcpListener,
};

async fn exchange(
    fixture: &Fixture,
    listener: &TcpListener,
    id: &str,
    mode: u32,
    reply: Option<&[u8]>,
) -> ActivationReceipt {
    let invocation = fixture.manager.start(fixture.request(id, mode)).unwrap();
    let peer = async {
        let (mut socket, _) = listener.accept().await.unwrap();
        // A fifth request byte is a failure, not an unbounded read_to_end.
        // For the reply scenarios this EOF is the approved send half-close;
        // it is not evidence of final provider or kernel retirement.
        let mut input = Vec::with_capacity(5);
        let read = (&mut socket).take(5).read_to_end(&mut input).await;
        match read {
            Ok(_) => {}
            Err(error)
                if reply.is_none() && error.kind() == std::io::ErrorKind::ConnectionReset => {}
            Err(error) => panic!("unexpected peer read failure: {error}"),
        }
        if let Some(reply) = reply {
            assert_eq!(input, b"PING");
            socket.write_all(reply).await.unwrap();
            socket.shutdown().await.unwrap();
        } else {
            assert!(
                input.is_empty(),
                "rejected operation sent application bytes"
            );
        }
    };
    // Both futures are owned by this scope. Failure drops them together; no
    // detached peer survives a failed assertion. The watchdog never passes.
    tokio::time::timeout(Duration::from_secs(10), async {
        let (receipt, ()) = tokio::join!(invocation, peer);
        receipt
    })
    .await
    .expect("signed invocation and original peer must both complete")
}

async fn fresh(fixture: &Fixture, listener: &TcpListener, id: &str) {
    success(exchange(fixture, listener, id, 0, Some(b"PONG")).await);
    idle(fixture).await;
}

#[tokio::test]
async fn signed_terminal_trap_retires_socket_and_store_before_cell_reuse() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let root = tempfile::tempdir().unwrap();
    let mut fixture = configured(root.path(), listener.local_addr().unwrap().port()).await;
    let receipt = exchange(&fixture, &listener, "terminal-stream-trap", 1, None).await;
    assert_eq!(failure(receipt).code, PlatformErrorCode::GuestTrap);
    // Mode 1 traps immediately after connect without running guest destructors.
    idle(&fixture).await;
    assert_eq!(fixture.backend.resource_snapshot().stores_created, 1);
    fresh(&fixture, &listener, "fresh-after-terminal-stream-trap").await;
    assert_eq!(fixture.backend.resource_snapshot().stores_created, 2);
    fixture.streams.take().unwrap().shutdown().await;
}

#[tokio::test]
async fn signed_wrong_kind_chunk_and_consumed_handle_traps_retire_original_owners() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let root = tempfile::tempdir().unwrap();
    let mut fixture = configured(root.path(), listener.local_addr().unwrap().port()).await;
    // Mode 5 misuses a still-owned chunk as a connection, abandoning its
    // resident bytes. Mode 6 tries to consume an already closed connection.
    for mode in [5, 6] {
        let receipt = exchange(
            &fixture,
            &listener,
            &format!("resource-trap-{mode}"),
            mode,
            Some(b"PONG"),
        )
        .await;
        assert_eq!(failure(receipt).code, PlatformErrorCode::GuestTrap);
        idle(&fixture).await;
        fresh(
            &fixture,
            &listener,
            &format!("fresh-after-resource-trap-{mode}"),
        )
        .await;
    }
    assert_eq!(fixture.backend.resource_snapshot().stores_created, 4);
    fixture.streams.take().unwrap().shutdown().await;
}

#[tokio::test]
async fn signed_oversized_write_is_rejected_without_payload_and_fresh_work_succeeds() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let root = tempfile::tempdir().unwrap();
    let mut fixture = configured(root.path(), listener.local_addr().unwrap().port()).await;
    let receipt = exchange(&fixture, &listener, "oversized-signed-write", 4, None).await;
    let ActivationOutcome::Succeeded(result) = receipt.outcome else {
        panic!("oversized input must be a catchable typed stream error");
    };
    // The encoded guest returns the actual WIT error discriminant (invalid-input).
    assert_eq!(
        serde_json::from_slice::<Vec<u32>>(&result.output).unwrap(),
        [0]
    );
    assert_eq!(result.consumption.outbound_requests, 1);
    drop(result);
    idle(&fixture).await;
    fresh(&fixture, &listener, "fresh-after-oversized-signed-write").await;
    assert_eq!(fixture.backend.resource_snapshot().stores_created, 2);
    fixture.streams.take().unwrap().shutdown().await;
}

#[tokio::test]
async fn signed_partial_frames_and_eof_do_not_invent_bytes_or_reuse_stream_state() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let root = tempfile::tempdir().unwrap();
    let mut fixture = configured(root.path(), listener.local_addr().unwrap().port()).await;
    for reply in [
        b"".as_slice(),
        b"P".as_slice(),
        b"PO".as_slice(),
        b"PON".as_slice(),
    ] {
        let receipt = exchange(
            &fixture,
            &listener,
            &format!("partial-frame-{}", reply.len()),
            0,
            Some(reply),
        )
        .await;
        let ActivationOutcome::Succeeded(result) = receipt.outcome else {
            panic!("transport EOF must not invent a complete protocol reply");
        };
        assert_eq!(
            serde_json::from_slice::<Vec<u32>>(&result.output).unwrap(),
            [u32::try_from(reply.len()).unwrap()]
        );
        assert_eq!(result.consumption.outbound_requests, 1);
        drop(result);
        idle(&fixture).await;
        fresh(
            &fixture,
            &listener,
            &format!("fresh-after-partial-{}", reply.len()),
        )
        .await;
    }
    assert_eq!(fixture.backend.resource_snapshot().stores_created, 8);
    fixture.streams.take().unwrap().shutdown().await;
}
