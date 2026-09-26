use super::{AddressPolicy, NetworkError, Resolver};
use hickory_proto::{
    op::{Message, MessageType, OpCode},
    rr::{rdata::A, RData, Record, RecordType},
};
use std::{net::SocketAddr, time::Duration};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::{TcpListener, UdpSocket},
    task::JoinHandle,
    time::Instant,
};

fn resolver(server: SocketAddr) -> Resolver {
    Resolver::new(
        "registry.test".into(),
        server,
        30,
        AddressPolicy {
            networks: vec!["127.0.0.1/32".parse().unwrap()],
            special_addresses: vec!["127.0.0.1".parse().unwrap()],
        },
        1,
    )
    .unwrap()
}

async fn truncated_fixture(oversized: bool) -> (SocketAddr, JoinHandle<()>) {
    let tcp = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = tcp.local_addr().unwrap();
    let udp = UdpSocket::bind(address).await.unwrap();
    let worker = tokio::spawn(async move {
        for _ in 0..if oversized { 1 } else { 2 } {
            let mut packet = [0; 512];
            let (length, sender) = udp.recv_from(&mut packet).await.unwrap();
            let query = Message::from_vec(&packet[..length]).unwrap();
            let mut reply = Message::new(query.metadata.id, MessageType::Response, OpCode::Query);
            reply.metadata.truncation = true;
            reply.add_query(query.queries[0].clone());
            udp.send_to(&reply.to_vec().unwrap(), sender).await.unwrap();
            let (mut socket, _) = tcp.accept().await.unwrap();
            let mut prefix = [0; 2];
            socket.read_exact(&mut prefix).await.unwrap();
            let length = usize::from(u16::from_be_bytes(prefix));
            assert!(length <= 512);
            let mut packet = vec![0; length];
            socket.read_exact(&mut packet).await.unwrap();
            let repeated = Message::from_vec(&packet).unwrap();
            assert_eq!(repeated.metadata.id, query.metadata.id);
            assert_eq!(repeated.queries, query.queries);
            if oversized {
                socket.write_all(&4097u16.to_be_bytes()).await.unwrap();
                return;
            }
            reply.metadata.truncation = false;
            if query.queries[0].query_type() == RecordType::A {
                reply.add_answer(Record::from_rdata(
                    query.queries[0].name().clone(),
                    30,
                    RData::A(A("127.0.0.1".parse().unwrap())),
                ));
            }
            let packet = reply.to_vec().unwrap();
            socket
                .write_all(&u16::try_from(packet.len()).unwrap().to_be_bytes())
                .await
                .unwrap();
            socket.write_all(&packet).await.unwrap();
        }
    });
    (address, worker)
}

#[tokio::test]
async fn truncated_udp_uses_only_the_same_explicit_tcp_resolver_and_fixed_cache() {
    let (server, worker) = truncated_fixture(false).await;
    let resolver = resolver(server);
    let answers = resolver
        .resolve(Instant::now() + Duration::from_secs(2))
        .await
        .unwrap();
    assert_eq!(
        answers.iter().collect::<Vec<_>>(),
        vec!["127.0.0.1".parse::<std::net::IpAddr>().unwrap()]
    );
    worker.await.unwrap();
    assert_eq!(resolver.usage().active, 0);
    assert_eq!(resolver.usage().cached_answers, 1);
    assert!(resolver
        .resolve(Instant::now() + Duration::from_secs(1))
        .await
        .is_ok());
    resolver.close().unwrap();
    assert_eq!(resolver.usage().cached_answers, 0);
    assert_eq!(
        resolver
            .resolve(Instant::now() + Duration::from_secs(1))
            .await
            .unwrap_err(),
        NetworkError::Closed
    );
}

#[tokio::test]
async fn tcp_length_is_rejected_before_unbounded_read_or_allocation() {
    let (server, worker) = truncated_fixture(true).await;
    let resolver = resolver(server);
    assert_eq!(
        resolver
            .resolve(Instant::now() + Duration::from_secs(2))
            .await
            .unwrap_err(),
        NetworkError::DnsFailed
    );
    worker.await.unwrap();
    assert_eq!(resolver.usage().active, 0);
    assert_eq!(resolver.usage().cached_answers, 0);
}

#[test]
fn broad_networks_do_not_authorize_special_or_mapped_metadata_addresses() {
    let policy = AddressPolicy {
        networks: vec!["0.0.0.0/0".parse().unwrap(), "::/0".parse().unwrap()],
        special_addresses: vec![],
    };
    policy.validate().unwrap();
    for address in [
        "127.0.0.1",
        "10.1.2.3",
        "169.254.169.254",
        "168.63.129.16",
        "::ffff:169.254.169.254",
        "::ffff:127.0.0.1",
        "::1",
        "fe80::1",
        "fd00::1",
        "2001:db8::1",
        "2002:a00:1::",
    ] {
        assert!(!policy.permits(address.parse().unwrap()), "{address}");
    }
    assert!(policy.permits("8.8.8.8".parse().unwrap()));
    assert!(policy.permits("2606:4700:4700::1111".parse().unwrap()));
}
