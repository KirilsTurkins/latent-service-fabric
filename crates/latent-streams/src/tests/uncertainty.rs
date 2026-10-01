//! A real peer mutates once and deliberately loses its reply. The shared host
//! preserves transport uncertainty and never reconnects or replays the command.
use super::{
    config,
    fixture::{Control, Fixture},
};
use crate::StreamErrorCode;
use latent_capabilities::broker::{
    network::{OutboundStreamInvoker, StreamConnectRequest},
    CapabilitySession,
};
use std::{
    sync::{
        atomic::{AtomicUsize, Ordering},
        Arc,
    },
    time::{Duration, Instant},
};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::TcpListener,
};

fn session(f: &Fixture, id: &str) -> (CapabilitySession, Control) {
    let (request, control) = f.request(id, 5000);
    (
        f.broker
            .open_session(f.plan.clone(), &request, &control, &f.publication)
            .unwrap(),
        control,
    )
}
fn request(f: &Fixture) -> StreamConnectRequest {
    StreamConnectRequest {
        endpoint: f.provider.inner.config.destinations[0].endpoint.clone(),
        timeout_millis: None,
    }
}

async fn mutation_peer(
    listener: TcpListener,
    attempts: Arc<AtomicUsize>,
    mutations: Arc<AtomicUsize>,
    mutated: tokio::sync::oneshot::Sender<()>,
    retired: tokio::sync::oneshot::Sender<()>,
) {
    let (mut socket, _) = listener.accept().await.unwrap();
    attempts.fetch_add(1, Ordering::AcqRel);
    let mut command = [0; 6];
    socket.read_exact(&mut command).await.unwrap();
    assert_eq!(&command, b"MUTATE");
    mutations.fetch_add(1, Ordering::AcqRel);
    mutated.send(()).unwrap();
    let mut byte = [0];
    assert_eq!(socket.read(&mut byte).await.unwrap(), 0);
    assert!(
        tokio::time::timeout(Duration::from_millis(50), listener.accept())
            .await
            .is_err()
    );
    retired.send(()).unwrap();
    let (mut fresh, _) = listener.accept().await.unwrap();
    attempts.fetch_add(1, Ordering::AcqRel);
    let mut input = Vec::new();
    fresh.read_to_end(&mut input).await.unwrap();
    assert_eq!(input, b"FRESH");
    fresh.write_all(b"OK").await.unwrap();
    fresh.shutdown().await.unwrap();
}

#[tokio::test]
async fn lost_mutation_reply_preserves_typed_uncertainty_and_never_replays() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let mut configuration = config();
    configuration.destinations[0].endpoint.port = listener.local_addr().unwrap().port();
    let f = Fixture::new(configuration);
    let attempts = Arc::new(AtomicUsize::new(0));
    let mutations = Arc::new(AtomicUsize::new(0));
    let (mutated, observed) = tokio::sync::oneshot::channel();
    let (retired, retirement) = tokio::sync::oneshot::channel();
    let peer = tokio::spawn(mutation_peer(
        listener,
        attempts.clone(),
        mutations.clone(),
        mutated,
        retired,
    ));
    let (original, control) = session(&f, "uncertain-mutation-root");
    let stream = f
        .provider
        .start(&original, request(&f))
        .unwrap()
        .await
        .unwrap();
    assert_eq!(
        stream
            .write(b"MUTATE".to_vec(), None)
            .unwrap()
            .await
            .unwrap(),
        6
    );
    observed.await.unwrap();
    let failure = stream.read(4, Some(50)).unwrap().await.err().unwrap();
    assert_eq!(failure.code, StreamErrorCode::Timeout);
    assert!(failure.may_have_applied);
    assert_eq!(failure.accepted_prefix_bytes, 0);
    assert_eq!(stream.inspect().accepted_write_bytes, 6);
    assert!(stream.inspect().application_write_attempted);
    let mut copied = false;
    let stopped = stream
        .write_from(1, None, &mut || {
            copied = true;
            Ok(vec![0])
        })
        .err()
        .unwrap();
    assert_eq!(stopped.code, StreamErrorCode::Timeout);
    assert!(stopped.may_have_applied);
    assert!(!copied);
    retirement.await.unwrap();
    assert_eq!(attempts.load(Ordering::Acquire), 1);
    assert_eq!(mutations.load(Ordering::Acquire), 1);
    assert_eq!(f.provider.usage().unwrap().connections, 0);
    assert_eq!(f.provider.usage().unwrap().owners, 1);
    assert!(control.budget.host_memory_bytes() > 0);
    let terminal = control.budget.finalize_at(None, Instant::now());
    assert_eq!(terminal.consumption().outbound_requests, 1);
    drop(stream);
    assert_eq!(control.budget.host_memory_bytes(), 0);
    assert_eq!(
        control.budget.snapshot_at(Instant::now()),
        *terminal.consumption()
    );
    drop(original);

    let (fresh, budget) = session(&f, "fresh-after-uncertainty");
    let stream = f
        .provider
        .start(&fresh, request(&f))
        .unwrap()
        .await
        .unwrap();
    assert_eq!(
        stream
            .write(b"FRESH".to_vec(), None)
            .unwrap()
            .await
            .unwrap(),
        5
    );
    stream
        .shutdown(latent_capabilities::broker::network::StreamShutdown::Send)
        .unwrap()
        .await
        .unwrap();
    let mut reply = Vec::new();
    while let Some(mut chunk) = stream.read(2, None).unwrap().await.unwrap() {
        reply.extend_from_slice(&chunk.copy_bytes().unwrap());
    }
    assert_eq!(&reply, b"OK");
    stream.close().await.unwrap();
    peer.await.unwrap();
    assert_eq!(attempts.load(Ordering::Acquire), 2);
    assert_eq!(mutations.load(Ordering::Acquire), 1);
    assert_eq!(
        budget.budget.snapshot_at(Instant::now()).outbound_requests,
        1
    );
    assert_eq!(budget.budget.host_memory_bytes(), 0);
    drop(fresh);
    f.clean().await;
}
