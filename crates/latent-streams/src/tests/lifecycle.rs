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
    let control_session_bytes = control.native_session_bytes();
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
    assert_eq!(control.budget.host_memory_bytes(), control_session_bytes);
    assert_eq!(observed(&fixture).live_accepted_write_bytes, 0);
    assert_eq!(observed(&fixture).owners, 0);
    drop(replacement);
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
    drop(fixture);
    control.assert_native_settled();
}

// Leave exactly the requested bytes in the original pool, with each test-only
// filler obeying the existing per-reservation limit.
fn reserve_except(
    fixture: &Fixture,
    available: usize,
) -> Vec<latent_capabilities::broker::pools::ProviderMetadata> {
    let maximum = fixture.pools.limits().unwrap().maximum_metadata_bytes;
    let current = fixture.pools.snapshot().unwrap().metadata_bytes;
    let mut remaining = maximum.checked_sub(current + available).unwrap();
    let mut reservations = Vec::new();
    while remaining != 0 {
        let bytes = remaining.min(1024 * 1024);
        reservations.push(fixture.pools.reserve_protocol_metadata(bytes).unwrap());
        remaining -= bytes;
    }
    assert_eq!(
        maximum - fixture.pools.snapshot().unwrap().metadata_bytes,
        available
    );
    reservations
}

#[tokio::test]
async fn refused_initial_install_never_publishes_an_unusable_epoch() {
    let configuration = config();
    let fixture = Fixture::new(configuration.clone());
    let before = fixture.pools.snapshot().unwrap();
    let original = fixture.provider.reference();
    // The original ordering could pay configuration (128 KiB), pool epoch
    // (4096 bytes), and new ProviderUse (1024 bytes), then fail the registry.
    let reservations = reserve_except(&fixture, 128 * 1024 + 4096 + 1024);
    let failure = match crate::StreamProvider::install_for_qualification(
        fixture.pools.clone(),
        "not-published",
        1,
        0,
        configuration.clone(),
    ) {
        Ok(_) => panic!("unexpected successful install"),
        Err(error) => error,
    };
    assert_eq!(failure.code, StreamErrorCode::Exhausted);
    let installed = fixture.pools.provider("not-published");
    let current = fixture.pools.provider("streams").unwrap().reference();
    let original_retired = fixture.provider.inner.installed.is_retired();
    drop(reservations);
    assert!(
        installed.is_err(),
        "refused install published an unusable epoch"
    );
    assert!(!original_retired);
    assert!(current.same_installation(&original));
    assert_eq!(
        fixture.pools.snapshot().unwrap().metadata_bytes,
        before.metadata_bytes
    );
    assert_eq!(
        fixture.pools.snapshot().unwrap().configurations,
        before.configurations
    );
    let retry = crate::StreamProvider::install_for_qualification(
        fixture.pools.clone(),
        "not-published",
        1,
        0,
        configuration,
    )
    .unwrap();
    assert_eq!(retry.reference().configuration_epoch(), 1);
    retry.retire();
    drop(retry);
    drop(installed);
    drop(current);
    drop(original);
    fixture.clean().await;
}

#[tokio::test]
async fn refused_rotation_preserves_original_epoch_connection_and_new_admissions() {
    tokio::time::timeout(Duration::from_secs(15), async {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let mut configuration = config();
        configuration.destinations[0].endpoint.port = listener.local_addr().unwrap().port();
        let request = || StreamConnectRequest {
            endpoint: configuration.destinations[0].endpoint.clone(),
            timeout_millis: None,
        };
        let fixture = Fixture::new(configuration.clone());
        let lifecycle = Arc::new(
            StreamLifecycle::from_installed_for_qualification("streams", fixture.provider.clone())
                .unwrap(),
        );
        let original = fixture.provider.reference();
        let (session, control) = fixture.session(10_000);
        let stream = lifecycle.start(&session, request()).unwrap().await.unwrap();
        let (mut peer, _) = listener.accept().await.unwrap();
        assert_eq!(
            stream
                .write(b"before".to_vec(), None)
                .unwrap()
                .await
                .unwrap(),
            6
        );
        let mut bytes = [0; 6];
        peer.read_exact(&mut bytes).await.unwrap();
        assert_eq!(&bytes, b"before");
        let before = fixture.pools.snapshot().unwrap();
        // The original ordering paid configuration and the replacement epoch,
        // then failed the still-unfunded registry after retiring the old epoch.
        let reservations = reserve_except(&fixture, 128 * 1024 + 4096);
        let failure = match lifecycle.rotate(1, 2, configuration.clone()) {
            Ok(_) => panic!("unexpected successful rotation"),
            Err(error) => error,
        };
        assert_eq!(failure.code, StreamErrorCode::Exhausted);
        let pool_reference = fixture.pools.provider("streams").unwrap().reference();
        let old_retired = fixture.provider.inner.installed.is_retired();
        drop(reservations);
        assert!(!old_retired, "refused rotation retired the original epoch");
        assert!(
            pool_reference.same_installation(&original),
            "refused rotation published epoch {}",
            pool_reference.configuration_epoch()
        );
        assert_eq!(lifecycle.reference().unwrap().configuration_epoch(), 1);
        assert_eq!(
            fixture.pools.snapshot().unwrap().metadata_bytes,
            before.metadata_bytes
        );
        assert_eq!(
            stream
                .write(b"after".to_vec(), None)
                .unwrap()
                .await
                .unwrap(),
            5
        );
        let mut bytes = [0; 5];
        peer.read_exact(&mut bytes).await.unwrap();
        assert_eq!(&bytes, b"after");
        // A new connection must still be admitted by the same original grant.
        let fresh = lifecycle.start(&session, request()).unwrap().await.unwrap();
        let (_fresh_peer, _) = listener.accept().await.unwrap();
        fresh.close().await.unwrap();
        stream.close().await.unwrap();
        let replacement = lifecycle.rotate(1, 2, configuration.clone()).unwrap();
        assert_eq!(replacement.configuration_epoch(), 2);
        assert!(fixture.provider.inner.installed.is_retired());
        assert!(lifecycle.start(&session, request()).is_err());
        drop(replacement);
        drop(pool_reference);
        drop(original);
        drop(lifecycle);
        drop(session);
        fixture.clean().await;
        drop(fixture);
        control.assert_native_settled();
    })
    .await
    .expect("bounded real-peer rotation test");
}

fn observed(fixture: &Fixture) -> latent_capabilities::broker::network::StreamNodeUsage {
    fixture
        .broker
        .inspect_node_usage()
        .unwrap()
        .streams
        .unwrap()
}
