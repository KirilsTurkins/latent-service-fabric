use super::{
    named,
    peer::{wait_until, Peer},
    pull, HttpOciRegistry, RegistryResolution,
};
use hickory_proto::{
    op::{Message, MessageType, OpCode},
    rr::{
        rdata::{A, AAAA},
        RData, Record, RecordType,
    },
};
use latent_core::PlatformErrorCode;
use std::{
    net::{IpAddr, SocketAddr},
    sync::{
        atomic::{AtomicBool, AtomicUsize, Ordering},
        Arc, Mutex,
    },
    time::Duration,
};
use tokio::{net::UdpSocket, sync::Semaphore, task::JoinHandle, time::Instant};

pub(super) struct DnsPeer {
    pub(super) address: SocketAddr,
    answer: Arc<Mutex<IpAddr>>,
    pub(super) count: Arc<AtomicUsize>,
    pub(super) hold: Arc<AtomicBool>,
    pub(super) release: Arc<Semaphore>,
    worker: JoinHandle<()>,
}

impl DnsPeer {
    pub(super) async fn new() -> Self {
        let socket = UdpSocket::bind("127.0.0.1:0").await.unwrap();
        let address = socket.local_addr().unwrap();
        let answer = Arc::new(Mutex::new("127.0.0.1".parse::<IpAddr>().unwrap()));
        let count = Arc::new(AtomicUsize::new(0));
        let hold = Arc::new(AtomicBool::new(false));
        let release = Arc::new(Semaphore::new(0));
        let state = (
            Arc::clone(&answer),
            Arc::clone(&count),
            Arc::clone(&hold),
            Arc::clone(&release),
        );
        let worker = tokio::spawn(async move {
            let mut packet = [0; 513];
            loop {
                let (length, peer) = socket.recv_from(&mut packet).await.unwrap();
                assert!(length <= 512);
                let request = Message::from_vec(&packet[..length]).unwrap();
                assert_eq!(request.queries.len(), 1);
                state.1.fetch_add(1, Ordering::AcqRel);
                if state.2.load(Ordering::Acquire) {
                    state.3.acquire().await.unwrap().forget();
                }
                let query = &request.queries[0];
                let mut response =
                    Message::new(request.metadata.id, MessageType::Response, OpCode::Query);
                response.add_query(query.clone());
                let address = *state.0.lock().unwrap();
                let record = match (query.query_type(), address) {
                    (RecordType::A, IpAddr::V4(address)) => Some(RData::A(A(address))),
                    (RecordType::AAAA, IpAddr::V6(address)) => Some(RData::AAAA(AAAA(address))),
                    _ => None,
                };
                if let Some(record) = record {
                    response.add_answer(Record::from_rdata(query.name().clone(), 1, record));
                }
                socket
                    .send_to(&response.to_vec().unwrap(), peer)
                    .await
                    .unwrap();
            }
        });
        Self {
            address,
            answer,
            count,
            hold,
            release,
            worker,
        }
    }

    pub(super) async fn close(mut self) {
        self.worker.abort();
        assert!((&mut self.worker).await.unwrap_err().is_cancelled());
    }
}

impl Drop for DnsPeer {
    fn drop(&mut self) {
        self.worker.abort();
    }
}

#[tokio::test]
async fn shared_dns_cache_expires_and_rebinding_never_reaches_the_tls_peer() {
    let dns = DnsPeer::new().await;
    let peer = Peer::with_names(vec!["registry.test".into()]).await;
    let (config, mut network) = named(&peer, "registry.test");
    network.destinations[0].resolution = RegistryResolution::Dns {
        server: dns.address,
        maximum_ttl_seconds: 1,
    };
    let origin = config.origin.clone();
    let client = HttpOciRegistry::new_with_network(config, network).unwrap();
    let mut calls = Vec::new();
    for _ in 0..4 {
        let client = client.clone();
        let origin = origin.clone();
        calls.push(tokio::spawn(async move { pull(&client, &origin).await }));
    }
    for call in calls {
        assert_eq!(call.await.unwrap().unwrap(), b"abc");
    }
    assert_eq!(dns.count.load(Ordering::Acquire), 2);
    assert_eq!(client.usage().network.unwrap().retained_dns_answers, 1);
    let reads = peer.state.reads.load(Ordering::Acquire);
    *dns.answer.lock().unwrap() = "169.254.169.254".parse().unwrap();
    tokio::time::sleep(Duration::from_millis(1100)).await;
    assert_eq!(
        pull(&client, &origin).await.unwrap_err().code,
        PlatformErrorCode::PermissionDenied
    );
    assert_eq!(peer.state.reads.load(Ordering::Acquire), reads);
    assert_eq!(client.usage().network.unwrap().active_resolvers, 0);
    client
        .shutdown(Instant::now() + Duration::from_secs(1))
        .await
        .unwrap();
    assert_eq!(client.usage().network.unwrap().retained_dns_answers, 0);
}

#[tokio::test]
async fn cancellation_and_deadline_retire_dns_sockets_without_background_jobs() {
    let dns = DnsPeer::new().await;
    dns.hold.store(true, Ordering::Release);
    let peer = Peer::with_names(vec!["registry.test".into()]).await;
    let (mut config, mut network) = named(&peer, "registry.test");
    config.limits.operation_timeout = Duration::from_millis(200);
    network.destinations[0].resolution = RegistryResolution::Dns {
        server: dns.address,
        maximum_ttl_seconds: 1,
    };
    let origin = config.origin.clone();
    let client = HttpOciRegistry::new_with_network(config, network).unwrap();
    let first = client.clone();
    let first_origin = origin.clone();
    let call = tokio::spawn(async move { pull(&first, &first_origin).await });
    wait_until(|| client.usage().network.unwrap().active_resolvers == 1).await;
    call.abort();
    assert!(call.await.unwrap_err().is_cancelled());
    let usage = client.usage().network.unwrap();
    assert_eq!(usage.connections, 0);
    assert_eq!(usage.active_resolvers, 0);
    assert_eq!(usage.reserved_connection_bytes, 0);
    assert_eq!(
        pull(&client, &origin).await.unwrap_err().code,
        PlatformErrorCode::DeadlineExceeded
    );
    assert_eq!(client.usage().network.unwrap().connections, 0);
    assert_eq!(peer.state.tokens.load(Ordering::Acquire), 0);
    dns.release.add_permits(4);
}
