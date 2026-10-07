use super::{config, fixture::Fixture};
use crate::{StreamErrorCode, StreamLifecycle, StreamResolution};
use hickory_proto::{
    op::{Message, MessageType, OpCode},
    rr::{rdata::A, RData, Record, RecordType},
};
use latent_capabilities::broker::network::{
    OutboundStreamInvoker, StreamConnectRequest, StreamState,
};
use std::{
    sync::Arc,
    time::{Duration, Instant},
};
use tokio::{
    io::AsyncReadExt,
    net::{TcpListener, UdpSocket},
};

#[expect(
    clippy::too_many_lines,
    reason = "real DNS/socket and affine retirement barriers"
)]
async fn expiry(dns: bool) {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let mut configuration = config();
    configuration.destinations[0].endpoint.port = listener.local_addr().unwrap().port();
    let dns_peer = if dns {
        let udp = UdpSocket::bind("127.0.0.1:0").await.unwrap();
        configuration.destinations[0].endpoint.host = "registry.test".into();
        configuration.destinations[0].resolution = StreamResolution::Dns {
            server: udp.local_addr().unwrap(),
            maximum_ttl_seconds: 1,
        };
        Some(tokio::spawn(async move {
            for _ in 0..2 {
                let mut packet = [0; 512];
                let (length, sender) = udp.recv_from(&mut packet).await.unwrap();
                let query = Message::from_vec(&packet[..length]).unwrap();
                let mut reply =
                    Message::new(query.metadata.id, MessageType::Response, OpCode::Query);
                reply.add_query(query.queries[0].clone());
                if query.queries[0].query_type() == RecordType::A {
                    reply.add_answer(Record::from_rdata(
                        query.queries[0].name().clone(),
                        1,
                        RData::A(A("127.0.0.1".parse().unwrap())),
                    ));
                }
                udp.send_to(&reply.to_vec().unwrap(), sender).await.unwrap();
            }
        }))
    } else {
        configuration.limits.idle_timeout_millis = 50;
        None
    };
    let fixture = Fixture::new(configuration);
    let lifecycle = Arc::new(
        StreamLifecycle::from_installed_for_qualification("streams", fixture.provider.clone())
            .unwrap(),
    );
    let baseline = fixture.pools.snapshot().unwrap().metadata_bytes;
    let unpolled = lifecycle.maintenance().unwrap();
    let stop = unpolled.stop_handle();
    assert_eq!(
        lifecycle.maintenance().err().unwrap().code,
        StreamErrorCode::Exhausted
    );
    stop.stop();
    assert_eq!(lifecycle.status().unwrap().maintenance_owners, 1);
    assert_eq!(
        fixture.pools.snapshot().unwrap().metadata_bytes,
        baseline + 8192
    );
    drop(unpolled);
    assert_eq!(lifecycle.status().unwrap().maintenance_owners, 0);
    assert_eq!(
        fixture.pools.snapshot().unwrap().metadata_bytes,
        baseline + 8192
    );
    drop(stop);
    assert_eq!(fixture.pools.snapshot().unwrap().metadata_bytes, baseline);

    let maintenance = lifecycle.maintenance().unwrap();
    let stop = maintenance.stop_handle();
    let driver = tokio::spawn(maintenance.run());
    let (session, control) = fixture.session(5000);
    let stream = lifecycle
        .start(
            &session,
            StreamConnectRequest {
                endpoint: fixture.provider.inner.config.destinations[0]
                    .endpoint
                    .clone(),
                timeout_millis: None,
            },
        )
        .unwrap()
        .await
        .unwrap();
    let (mut peer, _) = listener.accept().await.unwrap();
    assert_eq!(stream.inspect().state, StreamState::Open);
    let native_before = control.budget.host_memory_bytes();
    assert!(native_before >= 96 * 1024);
    let started = Instant::now();
    let mut byte = [0];
    assert_eq!(
        tokio::time::timeout(Duration::from_secs(2), peer.read(&mut byte))
            .await
            .unwrap()
            .unwrap(),
        0
    );
    assert!(started.elapsed() < Duration::from_secs(2));
    assert_eq!(stream.inspect().state, StreamState::Failed);
    let failure = match stream.write(b"NEVER".to_vec(), None) {
        Ok(write) => write.await.err().unwrap(),
        Err(failure) => failure,
    };
    assert_eq!(failure.code, StreamErrorCode::Timeout);
    assert!(!stream.inspect().application_write_attempted);
    assert_eq!(stream.inspect().accepted_write_bytes, 0);
    assert_eq!(lifecycle.status().unwrap().usage.connections, 0);
    assert_eq!(fixture.pools.snapshot().unwrap().connections, 0);
    assert_eq!(fixture.pools.snapshot().unwrap().running_requests, 1);
    assert!(control.budget.host_memory_bytes() > 0);
    assert!(control.budget.host_memory_bytes() < native_before);
    drop(stream);
    assert_eq!(control.budget.host_memory_bytes(), 0);
    assert_eq!(lifecycle.status().unwrap().usage.owners, 0);
    stop.stop();
    driver.await.unwrap().unwrap();
    assert_eq!(lifecycle.status().unwrap().maintenance_owners, 0);
    drop(stop);
    if let Some(peer) = dns_peer {
        peer.await.unwrap();
    }
    drop(session);
    fixture.clean().await;
}

#[tokio::test]
async fn idle_expiry_retires_inactive_socket_on_one_weak_owned_driver() {
    expiry(false).await;
}

#[tokio::test]
async fn dns_authority_expiry_retires_inactive_socket_without_another_guest_call() {
    expiry(true).await;
}
