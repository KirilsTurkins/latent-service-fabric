use super::{config, fixture::Fixture};
use crate::{StreamErrorCode, StreamLifecycle};
use latent_capabilities::broker::network::{OutboundStreamInvoker, StreamConnectRequest};
use std::{
    sync::Arc,
    time::{Duration, Instant},
};
use tokio::{io::AsyncReadExt, net::TcpListener};

#[tokio::test]
async fn rotation_fences_old_grants_and_drain_reports_actual_retained_owners() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let mut config = config();
    config.destinations[0].endpoint.port = listener.local_addr().unwrap().port();
    let request = || StreamConnectRequest {
        endpoint: config.destinations[0].endpoint.clone(),
        timeout_millis: None,
    };
    let fixture = Fixture::new(config.clone());
    let lifecycle = Arc::new(
        StreamLifecycle::from_installed_for_qualification("streams", fixture.provider.clone())
            .unwrap(),
    );
    let weak = Arc::downgrade(&lifecycle);
    let runtime = fixture.runtime();
    runtime.install_outbound_streams(lifecycle.clone()).unwrap();
    assert!(runtime.install_outbound_streams(lifecycle.clone()).is_err());
    assert_eq!(observed(&fixture).configuration_epoch, 1);
    assert_eq!(observed(&fixture).owners, 0);
    let (session, control) = fixture.session(5000);
    let stream = lifecycle.start(&session, request()).unwrap().await.unwrap();
    let (mut peer, _) = listener.accept().await.unwrap();
    assert_eq!(
        stream.write(b"PING".to_vec(), None).unwrap().await.unwrap(),
        4
    );
    let mut sent = [0; 4];
    peer.read_exact(&mut sent).await.unwrap();
    assert_eq!(&sent, b"PING");
    assert_eq!(observed(&fixture).live_accepted_write_bytes, 4);
    let pending = stream.read(16 * 1024, None).unwrap();
    assert_eq!(lifecycle.status().unwrap().usage.connections, 1);
    let replacement = lifecycle.rotate(1, 2, config.clone()).unwrap();
    assert_eq!(replacement.configuration_epoch(), 2);
    assert_eq!(lifecycle.status().unwrap().retired_generations, 1);
    assert_eq!(lifecycle.status().unwrap().usage.owners, 1);
    let usage = observed(&fixture);
    assert_eq!(usage.configuration_epoch, 2);
    assert_eq!(usage.retired_generations, 1);
    assert_eq!(usage.connections, 1);
    assert_eq!(usage.pending_operations, 1);
    assert_eq!(fixture.pools.snapshot().unwrap().connections, 1);
    assert!(control.budget.host_memory_bytes() >= 96 * 1024);
    assert!(lifecycle.start(&session, request()).is_err());
    assert_eq!(
        control.budget.snapshot_at(Instant::now()).outbound_requests,
        1
    );
    assert_eq!(
        lifecycle.rotate(1, 3, config).err().unwrap().code,
        StreamErrorCode::Revoked
    );
    assert_eq!(pending.await.err().unwrap().code, StreamErrorCode::Revoked);
    let mut byte = [0];
    match tokio::time::timeout(Duration::from_secs(1), peer.read(&mut byte))
        .await
        .unwrap()
    {
        Ok(0) => {}
        Err(error) if error.kind() == std::io::ErrorKind::ConnectionReset => {}
        value => panic!("physical closure expected: {value:?}"),
    }
    let status = lifecycle
        .drain(Instant::now() + Duration::from_millis(20))
        .await
        .unwrap();
    assert!(status.stopped);
    assert_eq!(status.usage.owners, 1);
    assert_eq!(status.usage.connections, 0);
    assert_eq!(fixture.pools.snapshot().unwrap().running_requests, 1);
    let usage = observed(&fixture);
    assert!(usage.stopped);
    assert_eq!(usage.owners, 1);
    assert_eq!(usage.connections, 0);
    assert_eq!(usage.pending_operations, 0);
    assert_eq!(usage.live_accepted_write_bytes, 4);
    assert!(control.budget.host_memory_bytes() > 0);
    drop(stream);
    assert_eq!(
        lifecycle
            .drain(Instant::now() + Duration::from_secs(1))
            .await
            .unwrap()
            .usage
            .owners,
        0
    );
    assert_eq!(control.budget.host_memory_bytes(), 0);
    assert_eq!(observed(&fixture).live_accepted_write_bytes, 0);
    assert_eq!(observed(&fixture).owners, 0);
    drop(runtime);
    drop(lifecycle);
    assert!(weak.upgrade().is_none());
    assert!(fixture
        .broker
        .inspect_node_usage()
        .unwrap()
        .streams
        .is_none());
    drop(session);
    fixture.clean().await;
}

fn observed(fixture: &Fixture) -> latent_capabilities::broker::network::StreamNodeUsage {
    fixture
        .broker
        .inspect_node_usage()
        .unwrap()
        .streams
        .unwrap()
}
