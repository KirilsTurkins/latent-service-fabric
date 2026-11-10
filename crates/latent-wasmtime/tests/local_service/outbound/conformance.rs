//! Shared signed-node negatives. The encoded guest is deliberately not credited
//! as an ordinary language client, protocol parser or kernel final-free probe.
use super::{configured, failure, idle, physical_closure, success};
use crate::fixture::Fixture;
use latent_activation::ActivationOutcome;
use latent_core::{ActivationId, CancelDisposition, PlatformErrorCode, TenantId};
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
async fn signed_stream_output_budget_exhaustion_keeps_fresh_call_independent() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let root = tempfile::tempdir().unwrap();
    let port = listener.local_addr().unwrap().port();
    let mut config = super::configuration(port);
    // Separate input and output ceilings: PING fits the input ceiling, while
    // five response bytes exceed this connection's four-byte output ceiling.
    config.limits.maximum_transfer_bytes = 4;
    let mut fixture = super::configured_with_configuration(root.path(), port, config).await;
    // The exact four-byte boundary must work before the over-limit case; a
    // generic resource refusal cannot satisfy the negative by itself.
    success(
        exchange(
            &fixture,
            &listener,
            "output-budget-boundary",
            0,
            Some(b"PONG"),
        )
        .await,
    );
    idle(&fixture).await;
    let receipt = exchange(
        &fixture,
        &listener,
        "output-budget-exhausted",
        0,
        Some(b"PONGX"),
    )
    .await;
    let ActivationOutcome::Succeeded(result) = receipt.outcome else {
        panic!("the guest must return the catchable stream error");
    };
    // Existing guest ABI: 2000 plus the actual exhausted discriminant (5).
    assert_eq!(
        serde_json::from_slice::<Vec<u32>>(&result.output).unwrap(),
        [2005]
    );
    assert_eq!(result.consumption.outbound_requests, 1);
    drop(result);
    idle(&fixture).await;

    // A fresh activation gets its own unchanged four-byte stream allowance.
    let receipt = exchange(
        &fixture,
        &listener,
        "fresh-after-output-budget",
        0,
        Some(b"OK"),
    )
    .await;
    let ActivationOutcome::Succeeded(result) = receipt.outcome else {
        panic!("fresh bounded work must complete");
    };
    assert_eq!(
        serde_json::from_slice::<Vec<u32>>(&result.output).unwrap(),
        [2]
    );
    assert_eq!(result.consumption.outbound_requests, 1);
    drop(result);
    idle(&fixture).await;
    assert_eq!(fixture.backend.resource_snapshot().stores_created, 3);
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
async fn signed_reset_is_a_stream_error_and_fresh_work_succeeds() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let root = tempfile::tempdir().unwrap();
    let mut fixture = configured(root.path(), listener.local_addr().unwrap().port()).await;
    let invocation = fixture
        .manager
        .start(fixture.request("signed-peer-reset", 0))
        .unwrap();
    let peer = async {
        let (mut socket, _) = listener.accept().await.unwrap();
        // Mode 0 half-closes its send side after one PING; a fifth byte is a
        // failure. Wait for that actual EOF before aborting the reply side.
        let mut input = Vec::with_capacity(5);
        (&mut socket).take(5).read_to_end(&mut input).await.unwrap();
        assert_eq!(input, b"PING");
        socket.set_zero_linger().unwrap();
        assert_eq!(socket.linger().unwrap(), Some(Duration::ZERO));
        drop(socket);
    };
    let receipt = tokio::time::timeout(Duration::from_secs(10), async {
        let (receipt, ()) = tokio::join!(invocation, peer);
        receipt
    })
    .await
    .expect("reset peer and signed invocation must complete");
    let ActivationOutcome::Succeeded(result) = receipt.outcome else {
        panic!("the guest must return the catchable stream error");
    };
    // The existing encoded guest returns 2000 plus the real WIT error-code
    // discriminant. Reset must remain io-failed (11), not a successful EOF.
    assert_eq!(
        serde_json::from_slice::<Vec<u32>>(&result.output).unwrap(),
        [2011]
    );
    assert_eq!(result.consumption.outbound_requests, 1);
    drop(result);
    idle(&fixture).await;
    fresh(&fixture, &listener, "fresh-after-peer-reset").await;
    assert_eq!(fixture.backend.resource_snapshot().stores_created, 2);
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

#[tokio::test]
async fn signed_lost_reply_preserves_peer_mutation_without_implicit_replay() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let root = tempfile::tempdir().unwrap();
    let mut fixture = configured(root.path(), listener.local_addr().unwrap().port()).await;
    let (accepted, accepted_rx) = tokio::sync::oneshot::channel();
    let (first_idle, first_idle_rx) = tokio::sync::oneshot::channel();
    let (checked, checked_rx) = tokio::sync::oneshot::channel();
    let (fresh_idle, fresh_idle_rx) = tokio::sync::oneshot::channel();

    // The peer applies one fixture mutation after receiving the complete PING
    // command, then sends only the first byte of its reply. The reply remains
    // incomplete until the original activation is cancelled and disconnected.
    let peer = async {
        let mut connections = 0_u32;
        let mut mutations = 0_u32;
        let (mut socket, _) = listener.accept().await.unwrap();
        connections += 1;
        let mut command = [0; 4];
        socket.read_exact(&mut command).await.unwrap();
        assert_eq!(&command, b"PING");
        mutations += 1;
        socket.write_all(b"P").await.unwrap();
        accepted.send((connections, mutations)).unwrap();
        physical_closure(&mut socket).await;
        first_idle_rx.await.unwrap();

        // Look for a hidden reconnect only while no new activation exists.
        // The finite observation is not a general proof about arbitrary code.
        assert!(
            tokio::time::timeout(Duration::from_millis(100), listener.accept())
                .await
                .is_err()
        );
        checked.send((connections, mutations)).unwrap();

        // This second connection is independently requested by the test, not
        // a replay. Its complete reply proves fresh work on the same backend.
        let (mut fresh_socket, _) = listener.accept().await.unwrap();
        connections += 1;
        let mut fresh_command = Vec::with_capacity(5);
        (&mut fresh_socket)
            .take(5)
            .read_to_end(&mut fresh_command)
            .await
            .unwrap();
        assert_eq!(fresh_command, b"PING");
        mutations += 1;
        fresh_socket.write_all(b"PONG").await.unwrap();
        fresh_socket.shutdown().await.unwrap();
        fresh_idle_rx.await.unwrap();
        assert!(
            tokio::time::timeout(Duration::from_millis(100), listener.accept())
                .await
                .is_err()
        );
        assert_eq!((connections, mutations), (2, 2));
    };

    let calls = async {
        let id = ActivationId("lost-reply-after-peer-mutation".into());
        let mut invocation = Box::pin(fixture.manager.start(fixture.request(&id.0, 2)).unwrap());
        let count = tokio::select! {
            receipt = &mut invocation => panic!("reply did not remain pending: {:?}", receipt.outcome),
            count = accepted_rx => count.unwrap(),
        };
        assert_eq!(count, (1, 1));
        assert_eq!(fixture.backend.resource_snapshot().live_stores, 1);
        assert_eq!(
            fixture
                .streams
                .as_ref()
                .unwrap()
                .lifecycle
                .status()
                .unwrap()
                .usage
                .owners,
            1
        );
        assert_eq!(
            fixture
                .manager
                .cancel_for(&TenantId("tenant-a".into()), &id, "lost-reply-cancel")
                .unwrap(),
            CancelDisposition::Accepted
        );
        let receipt = invocation.await;
        let ActivationOutcome::Failed {
            error, consumption, ..
        } = receipt.outcome
        else {
            panic!("cancelled operation must retain a failure outcome");
        };
        assert_eq!(error.code, PlatformErrorCode::Cancelled);
        assert_eq!(consumption.outbound_requests, 1);
        idle(&fixture).await;
        first_idle.send(()).unwrap();
        // Cancellation cannot undo the peer-side mutation.
        assert_eq!(checked_rx.await.unwrap(), (1, 1));
        success(
            fixture
                .manager
                .start(fixture.request("fresh-after-lost-reply", 0))
                .unwrap()
                .await,
        );
        idle(&fixture).await;
        fresh_idle.send(()).unwrap();
    };
    // Both owned futures are dropped on a failure or watchdog expiry; a
    // timeout is never recorded as successful physical cleanup.
    tokio::time::timeout(Duration::from_secs(10), async {
        tokio::join!(calls, peer);
    })
    .await
    .expect("lost-reply calls and original peer must complete");
    assert_eq!(fixture.backend.resource_snapshot().stores_created, 2);
    fixture.streams.take().unwrap().shutdown().await;
}
