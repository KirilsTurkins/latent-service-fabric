use super::{input, package, run, support};
#[path = "../http/component.rs"]
#[allow(dead_code, unused_imports)]
mod component;
#[path = "../http/fixture.rs"]
#[allow(dead_code, unused_imports)]
mod fixture;
#[path = "../http/packages.rs"]
#[allow(dead_code, unused_imports)]
mod packages;
use fixture::*;

use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::TcpListener,
};
#[tokio::test]
#[ignore = "Requires compiled guest SDK fixtures"]
async fn buffered_http_success_and_denial_use_the_real_provider() {
    for language in super::languages() {
        let root = tempfile::tempdir().unwrap();
        let publication = package::publish(root.path(), &format!("{language}-http")).await;
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let port = listener.local_addr().unwrap().port();
        let server = tokio::spawn(async move {
            for method in ["GET", "HEAD", "POST"] {
                let (mut stream, _) = listener.accept().await.unwrap();
                let request = read_request(&mut stream, 7).await;
                assert!(request.starts_with(format!("{method} /allowed HTTP/1.1").as_bytes()));
                assert!(request.ends_with(b"payload"));
                stream
                    .write_all(
                        b"HTTP/1.1 201 Created\r\nContent-Length: 2\r\nConnection: close\r\n\r\n",
                    )
                    .await
                    .unwrap();
                if method != "HEAD" {
                    stream.write_all(b"ok").await.unwrap();
                }
            }
        });
        let f = Fixture::with_publication(port, "/allowed", Some(publication)).await;
        for which in 0..3 {
            let (mut request, control) = f.request("sdk-http", 0);
            input(
                &mut request,
                which,
                &format!("http://localhost:{port}/allowed"),
                0,
            );
            assert_eq!(
                run(&f.backend, request, &control).await,
                if which == 1 { 201 } else { 2201 }
            );
            f.idle();
        }
        server.await.unwrap();
        let (mut request, control) = f.request("sdk-http-denied", 0);
        input(
            &mut request,
            0,
            &format!("http://localhost:{port}/denied"),
            0,
        );
        assert_eq!(run(&f.backend, request, &control).await, 10);
        f.idle();
        assert!(f
            .pools
            .shutdown(Instant::now() + Duration::from_secs(2))
            .await
            .unwrap()
            .is_clean());
    }
}

pub(super) async fn read_request(stream: &mut tokio::net::TcpStream, length: usize) -> Vec<u8> {
    let mut bytes = Vec::new();
    loop {
        assert!(bytes.len() < 8192);
        let mut buf = [0; 1024];
        let count = tokio::time::timeout(Duration::from_secs(2), stream.read(&mut buf))
            .await
            .unwrap()
            .unwrap();
        if count == 0 {
            return bytes;
        }
        bytes.extend_from_slice(&buf[..count]);
        if let Some(end) = bytes.windows(4).position(|w| w == b"\r\n\r\n") {
            if bytes.len() >= end + 4 + length {
                return bytes;
            }
        }
    }
}
