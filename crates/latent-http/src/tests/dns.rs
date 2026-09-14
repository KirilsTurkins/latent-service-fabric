use super::*;
use hickory_proto::{
    op::{Message, MessageType, OpCode},
    rr::{rdata::A, RData, Record, RecordType},
};
use tokio::net::UdpSocket;
fn answer(packet: &[u8], ip: &str, ttl: u32) -> Vec<u8> {
    let query = Message::from_vec(packet).unwrap();
    let question = query.queries[0].clone();
    let mut reply = Message::new(query.metadata.id, MessageType::Response, OpCode::Query);
    if question.query_type() == RecordType::A {
        reply.add_answer(Record::from_rdata(
            question.name().clone(),
            ttl,
            RData::A(A(ip.parse().unwrap())),
        ));
    }
    reply.add_query(question);
    reply.to_vec().unwrap()
}
#[tokio::test]
async fn expired_dns_cannot_reuse_an_idle_socket_after_rebinding_to_metadata() {
    let dns = UdpSocket::bind("127.0.0.1:0").await.unwrap();
    let dns_addr = dns.local_addr().unwrap();
    let resolver = tokio::spawn(async move {
        let mut packet = [0; 512];
        for n in 0..3 {
            let (len, peer) = dns.recv_from(&mut packet).await.unwrap();
            let bytes = answer(
                &packet[..len],
                if n < 2 {
                    "127.0.0.1"
                } else {
                    "169.254.169.254"
                },
                0,
            );
            dns.send_to(&bytes, peer).await.unwrap();
        }
    });
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let server = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await.unwrap();
        read_request(&mut stream).await;
        stream
            .write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")
            .await
            .unwrap();
        let mut byte = [0];
        assert_eq!(
            tokio::time::timeout(Duration::from_secs(2), stream.read(&mut byte))
                .await
                .unwrap()
                .unwrap(),
            0
        );
    });
    let mut cfg = config(port);
    cfg.destinations[0].resolution = HttpResolution::Dns {
        server: dns_addr,
        maximum_ttl_seconds: 60,
    };
    let f = Fixture::new(cfg);
    let (session, _) = f.session(5000);
    let done = f
        .provider
        .start(&session, request(port, HttpMethod::Get))
        .unwrap()
        .await
        .unwrap();
    assert_eq!(done.response.as_ref().ok().unwrap().body(), b"ok");
    drop(done);
    let done = f
        .provider
        .start(&session, request(port, HttpMethod::Get))
        .unwrap()
        .await
        .unwrap();
    assert!(matches!(done.response, Err(HttpError::PermissionDenied)));
    drop(done);
    drop(session);
    resolver.await.unwrap();
    f.clean().await;
    server.await.unwrap();
}
#[tokio::test]
async fn cached_dns_is_shared_bounded_and_uses_no_system_resolution() {
    let dns = UdpSocket::bind("127.0.0.1:0").await.unwrap();
    let dns_addr = dns.local_addr().unwrap();
    let resolver = tokio::spawn(async move {
        let mut packet = [0; 512];
        for _ in 0..2 {
            let (len, peer) = dns.recv_from(&mut packet).await.unwrap();
            dns.send_to(&answer(&packet[..len], "127.0.0.1", 30), peer)
                .await
                .unwrap();
        }
        assert!(
            tokio::time::timeout(Duration::from_millis(150), dns.recv_from(&mut packet))
                .await
                .is_err()
        );
    });
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let server = tokio::spawn(async move {
        for _ in 0..2 {
            let (mut stream, _) = listener.accept().await.unwrap();
            read_request(&mut stream).await;
            stream
                .write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
                .await
                .unwrap();
        }
    });
    let mut cfg = config(port);
    cfg.destinations[0].origin.host = "only-explicit.invalid".into();
    cfg.destinations[0].resolution = HttpResolution::Dns {
        server: dns_addr,
        maximum_ttl_seconds: 60,
    };
    let f = Fixture::new(cfg);
    let (session, _) = f.session(5000);
    for _ in 0..2 {
        let mut input = request(port, HttpMethod::Get);
        input.url = format!("http://only-explicit.invalid:{port}/allowed");
        let done = f.provider.start(&session, input).unwrap().await.unwrap();
        assert!(done.response.is_ok());
        drop(done);
    }
    drop(session);
    server.await.unwrap();
    resolver.await.unwrap();
    f.clean().await;
}
#[tokio::test]
async fn dns_wait_cancels_and_refunds_its_actual_socket() {
    let dns = UdpSocket::bind("127.0.0.1:0").await.unwrap();
    let dns_addr = dns.local_addr().unwrap();
    let mut cfg = config(12345);
    cfg.destinations[0].resolution = HttpResolution::Dns {
        server: dns_addr,
        maximum_ttl_seconds: 60,
    };
    let f = Fixture::new(cfg);
    let (session, control) = f.session(5000);
    let mut operation = f
        .provider
        .start(&session, request(12345, HttpMethod::Get))
        .unwrap();
    let mut packet = [0; 512];
    tokio::select! {_=&mut operation=>panic!("DNS is stalled"),_=dns.recv_from(&mut packet)=>{}}
    assert_eq!(f.pools.snapshot().unwrap().connections, 1);
    control.probe.0.store(true, Ordering::Release);
    let done = operation.await.unwrap();
    assert!(matches!(done.response, Err(HttpError::Cancelled)));
    drop(done);
    drop(session);
    assert_eq!(f.pools.snapshot().unwrap().connections, 0);
    f.clean().await;
}
#[tokio::test]
async fn truncated_udp_falls_back_only_to_same_tcp_resolver() {
    let tcp = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = tcp.local_addr().unwrap();
    let udp = UdpSocket::bind(address).await.unwrap();
    let resolver = tokio::spawn(async move {
        for _ in 0..2 {
            let mut packet = [0; 512];
            let (len, peer) = udp.recv_from(&mut packet).await.unwrap();
            let mut truncated =
                Message::from_vec(&answer(&packet[..len], "127.0.0.1", 10)).unwrap();
            truncated.answers.clear();
            truncated.metadata.truncation = true;
            udp.send_to(&truncated.to_vec().unwrap(), peer)
                .await
                .unwrap();
            let (mut stream, _) = tcp.accept().await.unwrap();
            let mut length = [0; 2];
            stream.read_exact(&mut length).await.unwrap();
            let n = usize::from(u16::from_be_bytes(length));
            assert!(n < 512);
            stream.read_exact(&mut packet[..n]).await.unwrap();
            let response = answer(&packet[..n], "127.0.0.1", 10);
            stream
                .write_all(&u16::try_from(response.len()).unwrap().to_be_bytes())
                .await
                .unwrap();
            stream.write_all(&response).await.unwrap();
        }
    });
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let server = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await.unwrap();
        read_request(&mut stream).await;
        stream
            .write_all(b"HTTP/1.1 204 No Content\r\nConnection: close\r\n\r\n")
            .await
            .unwrap();
    });
    let mut cfg = config(port);
    cfg.destinations[0].resolution = HttpResolution::Dns {
        server: address,
        maximum_ttl_seconds: 10,
    };
    let f = Fixture::new(cfg);
    let (session, _) = f.session(5000);
    let done = f
        .provider
        .start(&session, request(port, HttpMethod::Get))
        .unwrap()
        .await
        .unwrap();
    assert_eq!(done.response.as_ref().ok().unwrap().status(), 204);
    drop(done);
    drop(session);
    server.await.unwrap();
    resolver.await.unwrap();
    f.clean().await;
}
