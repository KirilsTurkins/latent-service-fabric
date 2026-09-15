use super::{input, package, run, support};
#[path = "../streaming_http/component.rs"]
#[allow(dead_code, unused_imports)]
mod component;
#[path = "../streaming_http/fixture.rs"]
#[allow(dead_code, unused_imports)]
mod fixture;
#[path = "../streaming_http/packages.rs"]
#[allow(dead_code, unused_imports)]
mod packages;
use fixture::*;

use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::TcpListener,
};
#[tokio::test]
#[ignore = "Requires compiled guest SDK fixtures"]
async fn streaming_ownership_and_independent_chunks_survive_body_drop() {
    let root = tempfile::tempdir().unwrap();
    let publication = package::publish(root.path(), "rust-streaming").await;
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let server = tokio::spawn(async move {
        for index in 0..4 {
            let (mut stream, _) = listener.accept().await.unwrap();
            if index == 3 {
                let mut partial = vec![];
                tokio::time::timeout(
                    Duration::from_secs(2),
                    stream.take(4097).read_to_end(&mut partial),
                )
                .await
                .unwrap()
                .unwrap();
                assert!(partial.len() <= 4096);
                assert!(!partial.ends_with(b"data"));
                continue;
            }
            let request = super::http::read_request(&mut stream, 4).await;
            assert!(request.ends_with(b"data"));
            let _ = stream
                .write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 4\r\nConnection: close\r\n\r\ndata")
                .await;
        }
    });
    let f = Fixture::with_publication(port, "/allowed", Some(publication)).await;
    for (which, expected) in [(0, 4), (2, 2), (3, 4), (1, 1)] {
        let (mut request, control) = f.request("sdk-stream", 0);
        input(
            &mut request,
            which,
            &format!("http://localhost:{port}/allowed"),
            0,
        );
        assert_eq!(run(&f.backend, request, &control).await, expected);
        f.idle();
        assert_eq!(
            f.io.snapshot(),
            latent_capabilities::broker::io::IoSnapshot::default()
        );
    }
    server.await.unwrap();
    let (mut request, control) = f.request("sdk-stream-denied", 0);
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
