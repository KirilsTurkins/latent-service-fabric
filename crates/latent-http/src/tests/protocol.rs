use super::*;
use crate::protocol::{
    ProtocolBody, ProtocolHeader, ProtocolPage, ProtocolRequest, ProtocolScope, ProtocolTransport,
};
use http_body_util::BodyExt;
use std::time::Instant;
use zeroize::Zeroizing;

fn configured(port: u16, root: Vec<u8>) -> (Fixture, ProtocolTransport) {
    let mut cfg = config(port);
    cfg.destinations[0].origin.scheme = "https".into();
    cfg.destinations[0].allowed_request_headers.clear();
    cfg.destinations[0].redirect_destinations.clear();
    cfg.extra_roots.push(root);
    let f = Fixture::new(cfg.clone());
    let transport =
        ProtocolTransport::new(f.pools.clone(), &f.provider.inner.installed, cfg).unwrap();
    (f, transport)
}
fn input(port: u16, body: ProtocolBody) -> ProtocolRequest {
    ProtocolRequest {
        method: "POST".into(),
        path_and_query: "/allowed?uploads=".into(),
        headers: vec![ProtocolHeader {
            name: "host".into(),
            value: Zeroizing::new(format!("localhost:{port}")),
            sensitive: false,
        }],
        body,
    }
}
#[tokio::test]
async fn pages_stream_exact_ranges_and_outlive_dropped_body_owners() {
    let f = Fixture::new(config(12345));
    let baseline = f.pools.snapshot().unwrap().metadata_bytes;
    assert!(ProtocolPage::allocate(&f.pools, 65537).is_err());
    let mut page = ProtocolPage::allocate(&f.pools, 4096).unwrap();
    page.append(&[7; 4096]).unwrap();
    assert!(page.append(&[8]).is_err());
    let pages = vec![Arc::new(page)];
    assert!(ProtocolBody::from_pages(&f.pools, &pages, 0..4097).is_err());
    let mut body = ProtocolBody::from_pages(&f.pools, &pages, 4090..4096).unwrap();
    let frame = body.frame().await.unwrap().unwrap().into_data().unwrap();
    assert_eq!(frame.as_ref(), &[7; 6]);
    assert!(body.frame().await.is_none());
    drop((body, pages));
    assert!(f.pools.snapshot().unwrap().metadata_bytes > baseline);
    drop(frame);
    assert_eq!(f.pools.snapshot().unwrap().metadata_bytes, baseline);
    f.clean().await;
}
#[tokio::test]
async fn operator_protocol_uses_real_tls_and_closes_the_actual_connection() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let (root, acceptor) = super::tls::certificate();
    let server = tokio::spawn(async move {
        let (stream, _) = listener.accept().await.unwrap();
        let mut stream = acceptor.accept(stream).await.unwrap();
        let received = read_request(&mut stream).await;
        let split = received.windows(4).position(|b| b == b"\r\n\r\n").unwrap() + 4;
        assert!(std::str::from_utf8(&received[..split])
            .unwrap()
            .to_lowercase()
            .contains("content-length: 4110"));
        let body = &received[split..];
        assert_eq!(&body[..6], &[b'a'; 6]);
        assert_eq!(&body[6..4102], &[b'b'; 4096]);
        assert_eq!(&body[4102..], &[b'c'; 8]);
        stream.write_all(b"HTTP/1.1 206 Partial Content\r\nContent-Length: 3\r\nX-Amz-Version-Id: exact-version\r\n\r\nabc").await.unwrap();
        let ended = tokio::time::timeout(Duration::from_secs(1), stream.read(&mut [0]))
            .await
            .unwrap();
        assert!(matches!(ended, Ok(0)) || ended.is_err());
    });
    let (f, transport) = configured(port, root);
    let mut pages = Vec::new();
    for value in *b"abc" {
        let mut page = ProtocolPage::allocate(&f.pools, 4096).unwrap();
        page.append(&vec![value; 4096]).unwrap();
        pages.push(Arc::new(page));
    }
    let body = ProtocolBody::from_pages(&f.pools, &pages, 4090..8200).unwrap();
    let permit = transport
        .maintenance(Instant::now() + Duration::from_secs(2), 1)
        .unwrap();
    let request = permit.begin_request().unwrap();
    let mut received = Vec::new();
    let response = transport
        .exchange(
            ProtocolScope::Maintenance(&request),
            input(port, body),
            3,
            &mut |b| {
                received.extend_from_slice(b);
                Ok(())
            },
        )
        .await
        .unwrap();
    assert_eq!(response.status, 206);
    assert_eq!(response.body_bytes, 3);
    assert_eq!(received, b"abc");
    assert!(response
        .headers
        .contains(&("x-amz-version-id".into(), "exact-version".into())));
    assert_eq!(f.pools.snapshot().unwrap().connections, 0);
    assert_eq!(f.pools.snapshot().unwrap().idle_connections, 0);
    drop((response, request, permit, pages, transport));
    server.await.unwrap();
    f.clean().await;
}
#[tokio::test]
async fn protocol_deadline_retains_uncertainty_after_an_actual_request_write() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let (root, acceptor) = super::tls::certificate();
    let server = tokio::spawn(async move {
        let (stream, _) = listener.accept().await.unwrap();
        let mut stream = acceptor.accept(stream).await.unwrap();
        read_request(&mut stream).await;
        let ended = tokio::time::timeout(Duration::from_secs(1), stream.read(&mut [0]))
            .await
            .unwrap();
        assert!(matches!(ended, Ok(0)) || ended.is_err());
    });
    let (f, transport) = configured(port, root);
    let permit = transport
        .maintenance(Instant::now() + Duration::from_millis(500), 1)
        .unwrap();
    let request = permit.begin_request().unwrap();
    let result = transport
        .exchange(
            ProtocolScope::Maintenance(&request),
            input(port, ProtocolBody::empty(&f.pools).unwrap()),
            32,
            &mut |_| Ok(()),
        )
        .await;
    let Err(failure) = result else {
        panic!("unanswered mutation must not succeed")
    };
    assert_eq!(failure.error, HttpError::DeadlineExceeded);
    assert!(failure.request_started);
    assert_eq!(f.pools.snapshot().unwrap().connections, 0);
    drop((request, permit, transport));
    server.await.unwrap();
    f.clean().await;
}
