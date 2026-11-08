//! Actual TCP and original broker owners, not an inferred byte-counter barrier.
use super::{config, fixture::Fixture};
use crate::{StreamErrorCode, StreamUsage};
use latent_capabilities::broker::network::{OutboundStreamInvoker, StreamConnectRequest};
use std::{future::Future, task::Poll, time::Duration};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::{TcpListener, TcpStream},
};

async fn bounded(test: impl Future<Output = ()>) {
    tokio::time::timeout(Duration::from_secs(8), test)
        .await
        .expect("bounded original read-owner control");
}

async fn fixture() -> (Fixture, TcpListener) {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let mut configuration = config();
    configuration.destinations[0].endpoint.port = listener.local_addr().unwrap().port();
    (Fixture::new(configuration), listener)
}

fn request(fixture: &Fixture) -> StreamConnectRequest {
    StreamConnectRequest {
        endpoint: fixture.provider.inner.config.destinations[0]
            .endpoint
            .clone(),
        timeout_millis: None,
    }
}

fn progress(fixture: &Fixture, constructed: u8, pending: u8) -> StreamUsage {
    let usage = fixture.provider.usage().unwrap();
    assert_eq!(usage.owners, 1, "isolate the original connection owner");
    assert_eq!(usage.read_admissions, constructed);
    assert_eq!(usage.pending_reads, pending);
    // Development witnesses must not extend the closed operator wire surface.
    let wire = serde_json::to_value(usage).unwrap();
    for field in [
        "readAdmissions",
        "pendingReads",
        "retiredReadDeliveredBytes",
        "readProgress",
    ] {
        assert!(wire.get(field).is_none());
    }
    usage
}

async fn closed(peer: &mut TcpStream) {
    let mut byte = [0];
    match tokio::time::timeout(Duration::from_secs(1), peer.read(&mut byte))
        .await
        .unwrap()
    {
        Ok(0) => (),
        Err(error) if error.kind() == std::io::ErrorKind::ConnectionReset => (),
        other => panic!("actual original peer closure required: {other:?}"),
    }
}

#[tokio::test]
async fn read_progress_distinguishes_unpolled_reads_writes_and_rejected_overlap() {
    bounded(async {
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
        progress(&fixture, 0, 0);
        assert_eq!(
            stream.read(0, None).err().unwrap().code,
            StreamErrorCode::InvalidInput
        );
        let held_write = stream.write(vec![b'x'], None).unwrap();
        assert_eq!(progress(&fixture, 0, 0).pending_operations, 1);
        let first = stream.read(8, None).unwrap();
        assert_eq!(progress(&fixture, 1, 1).pending_operations, 2);
        assert_eq!(
            stream.read(8, None).err().unwrap().code,
            StreamErrorCode::InvalidState
        );
        progress(&fixture, 1, 1);
        drop(first);
        progress(&fixture, 1, 0);
        let second = stream.read(8, None).unwrap();
        progress(&fixture, 2, 1);
        drop(stream);
        assert_eq!(progress(&fixture, 2, 1).connections, 1);
        assert_eq!(fixture.pools.snapshot().unwrap().connections, 1);
        assert!(control.budget.host_memory_bytes() >= 96 * 1024);
        drop(held_write);
        assert_eq!(progress(&fixture, 2, 1).pending_operations, 1);
        drop(second);
        closed(&mut peer).await;
        assert_eq!(fixture.provider.usage().unwrap(), StreamUsage::default());
        assert_eq!(control.budget.host_memory_bytes(), baseline);
        drop(session);
        fixture.clean().await;
        drop(fixture);
        control.assert_native_settled();
    })
    .await;
}

#[tokio::test]
async fn a_real_short_read_precedes_the_second_pending_read_and_retained_result() {
    bounded(async {
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
        let first = stream.read(16, None).unwrap();
        progress(&fixture, 1, 1);
        // No second byte or EOF is issued until after the actual read result.
        peer.write_all(b"p").await.unwrap();
        let mut chunk = first.await.unwrap().unwrap();
        let bytes = chunk.copy_bytes().unwrap();
        assert_eq!(bytes.as_ref(), b"p");
        drop(chunk); // The actual lowering copy must retain the same owner.
        let first_released = progress(&fixture, 1, 0);
        assert_eq!(first_released.delivered_read_bytes, 1);
        assert_eq!(first_released.retained_chunks, 1);
        assert_eq!(first_released.retired_read_delivered_bytes, 1);
        let mut second = Box::pin(stream.read(16, None).unwrap());
        std::future::poll_fn(|cx| {
            assert!(second.as_mut().poll(cx).is_pending());
            Poll::Ready(())
        })
        .await;
        let pending = progress(&fixture, 2, 1);
        assert_eq!(pending.pending_operations, 1);
        assert_eq!(pending.delivered_read_bytes, 1);
        assert_eq!(pending.retired_read_delivered_bytes, 1);
        fixture.provider.retire();
        drop(stream);
        assert_eq!(progress(&fixture, 2, 1).connections, 1);
        assert_eq!(fixture.pools.snapshot().unwrap().connections, 1);
        let error = second.await.err().unwrap();
        assert_eq!(error.code, StreamErrorCode::Revoked);
        assert!(!error.may_have_applied);
        closed(&mut peer).await;
        let released = progress(&fixture, 2, 0);
        assert_eq!(released.connections, 0);
        assert_eq!(released.retained_chunks, 1);
        assert!(control.budget.host_memory_bytes() > baseline);
        assert_eq!(bytes.as_ref(), b"p");
        // Read release is not result/connection/activation retirement evidence.
        drop(bytes);
        let gone = fixture.provider.usage().unwrap();
        assert_eq!(gone.owners, 0);
        assert_eq!(gone.read_admissions, 0);
        assert_eq!(gone.pending_reads, 0);
        assert_eq!(gone.retired_read_delivered_bytes, 0);
        assert_eq!(control.budget.host_memory_bytes(), baseline);
        drop(session);
        fixture.clean().await;
        drop(fixture);
        control.assert_native_settled();
    })
    .await;
}

#[tokio::test]
async fn a_failed_read_window_admission_releases_only_its_original_guard() {
    bounded(async {
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
        peer.write_all(b"a").await.unwrap();
        let first = stream
            .read(16 * 1024, None)
            .unwrap()
            .await
            .unwrap()
            .unwrap();
        let held_write = stream.write(vec![b'x'; 16 * 1024], None).unwrap();
        assert_eq!(
            stream.read(16 * 1024, None).err().unwrap().code,
            StreamErrorCode::Exhausted
        );
        // The old (one byte, one operation) tuple is a write, not read two.
        // Failed buffer/window preparation cannot increment constructed reads.
        let refused = progress(&fixture, 1, 0);
        assert_eq!(refused.delivered_read_bytes, 1);
        assert_eq!(refused.retired_read_delivered_bytes, 1);
        assert_eq!(refused.pending_operations, 1);
        drop(held_write);
        let reading = stream.read(16 * 1024, None).unwrap();
        assert_eq!(progress(&fixture, 2, 1).retired_read_delivered_bytes, 1);
        peer.write_all(b"b").await.unwrap();
        let second = reading.await.unwrap().unwrap();
        assert_eq!(progress(&fixture, 2, 0).retained_chunks, 2);
        assert_eq!(
            stream.read(16 * 1024, None).err().unwrap().code,
            StreamErrorCode::Exhausted
        );
        let refused = progress(&fixture, 2, 0);
        assert_eq!(refused.pending_operations, 0);
        assert_eq!(refused.connections, 1);
        assert_eq!(refused.retained_chunks, 2);
        assert_eq!(refused.retired_read_delivered_bytes, 2);
        stream.close().await.unwrap();
        closed(&mut peer).await;
        let retained = progress(&fixture, 2, 0);
        assert_eq!(retained.connections, 0);
        assert_eq!(retained.retained_chunks, 2);
        assert!(control.budget.host_memory_bytes() > baseline);
        drop(first);
        drop(second);
        assert_eq!(fixture.provider.usage().unwrap(), StreamUsage::default());
        assert_eq!(control.budget.host_memory_bytes(), baseline);
        drop(session);
        fixture.clean().await;
        drop(fixture);
        control.assert_native_settled();
    })
    .await;
}

#[tokio::test]
async fn retired_epoch_observation_keeps_the_original_read_and_then_forgets_its_history() {
    bounded(async {
        let (fixture, listener) = fixture().await;
        let lifecycle = crate::StreamLifecycle::from_installed_for_qualification(
            "streams",
            fixture.provider.clone(),
        )
        .unwrap();
        let (session, control) = fixture.session(5000);
        let baseline = control.native_session_bytes();
        let stream = fixture
            .provider
            .start(&session, request(&fixture))
            .unwrap()
            .await
            .unwrap();
        let (mut peer, _) = listener.accept().await.unwrap();
        let pending = stream.read(16, None).unwrap();
        lifecycle
            .rotate(1, 2, fixture.provider.inner.config.clone())
            .unwrap();
        let retired = lifecycle.status().unwrap();
        assert_eq!(retired.configuration_epoch, 2);
        assert_eq!(retired.retired_generations, 1);
        assert_eq!(retired.usage.owners, 1);
        assert_eq!(retired.usage.connections, 1);
        assert_eq!(retired.usage.read_admissions, 1);
        assert_eq!(retired.usage.pending_reads, 1);
        drop(pending);
        closed(&mut peer).await;
        let released = lifecycle.status().unwrap().usage;
        assert_eq!(released.connections, 0);
        assert_eq!(released.owners, 1);
        assert_eq!(released.read_admissions, 1);
        assert_eq!(released.pending_reads, 0);
        drop(stream);
        assert_eq!(lifecycle.status().unwrap().usage, StreamUsage::default());
        assert_eq!(control.budget.host_memory_bytes(), baseline);
        drop(lifecycle);
        drop(session);
        fixture.clean().await;
        drop(fixture);
        control.assert_native_settled();
    })
    .await;
}

#[tokio::test]
async fn aggregate_first_reads_are_not_a_single_connections_second_read() {
    bounded(async {
        let (fixture, listener) = fixture().await;
        let (session, control) = fixture.session(5000);
        let baseline = control.native_session_bytes();
        let mut streams = Vec::new();
        let mut peers = Vec::new();
        let mut reads = Vec::new();
        for _ in 0..2 {
            let stream = fixture
                .provider
                .start(&session, request(&fixture))
                .unwrap()
                .await
                .unwrap();
            peers.push(listener.accept().await.unwrap().0);
            reads.push(stream.read(1, None).unwrap());
            streams.push(stream);
        }
        let aggregate = fixture.provider.usage().unwrap();
        assert_eq!(aggregate.owners, 2);
        assert_eq!(aggregate.connections, 2);
        assert_eq!(aggregate.pending_operations, 2);
        assert_eq!(aggregate.read_admissions, 2); // Two first reads, not read two.
        assert_eq!(aggregate.pending_reads, 2); // More than one original read owner.
        drop(streams);
        drop(reads);
        for peer in &mut peers {
            closed(peer).await;
        }
        assert_eq!(fixture.provider.usage().unwrap(), StreamUsage::default());
        assert_eq!(control.budget.host_memory_bytes(), baseline);
        drop(session);
        fixture.clean().await;
        drop(fixture);
        control.assert_native_settled();
    })
    .await;
}
