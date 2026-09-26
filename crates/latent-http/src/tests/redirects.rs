use super::*;
use latent_capabilities::broker::pools::ProviderPoolLimits;
#[tokio::test]
async fn redirects_reauthorize_and_strip_credentials_without_one_slot_deadlock() {
    let a = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let ap = a.local_addr().unwrap().port();
    let b = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let bp = b.local_addr().unwrap().port();
    let server_a = tokio::spawn(async move {
        for n in 0..2 {
            let (mut stream, _) = a.accept().await.unwrap();
            let wire = String::from_utf8(read_request(&mut stream).await).unwrap();
            if n == 0 {
                assert!(wire.contains("authorization: configured-a"));
                assert!(wire.contains("x-test: guest-secret"));
                stream.write_all(format!("HTTP/1.1 302 Found\r\nLocation: http://localhost:{bp}/allowed/b\r\nContent-Length: 0\r\nConnection: close\r\n\r\n").as_bytes()).await.unwrap();
            } else {
                assert!(!wire.contains("configured-"));
                assert!(!wire.contains("guest-secret"));
                stream
                    .write_all(
                        b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok",
                    )
                    .await
                    .unwrap();
            }
        }
    });
    let server_b = tokio::spawn(async move {
        let (mut stream, _) = b.accept().await.unwrap();
        let wire = String::from_utf8(read_request(&mut stream).await).unwrap();
        assert!(!wire.contains("configured-"));
        assert!(!wire.contains("guest-secret"));
        stream.write_all(format!("HTTP/1.1 307 Temporary Redirect\r\nLocation: http://localhost:{ap}/allowed/back\r\nContent-Length: 0\r\nConnection: close\r\n\r\n").as_bytes()).await.unwrap();
    });
    let mut cfg = config(ap);
    cfg.limits.maximum_redirects = 2;
    cfg.destinations[0].redirect_destinations = vec![1];
    let mut next = config(bp).destinations.remove(0);
    next.redirect_destinations = vec![0];
    cfg.destinations.push(next);
    let f = Fixture::configured(
        cfg,
        &[
            HttpCredential {
                destination: 0,
                name: "authorization",
                value: "configured-a",
            },
            HttpCredential {
                destination: 1,
                name: "authorization",
                value: "configured-b",
            },
        ],
        ProviderPoolLimits {
            maximum_running_requests: 1,
            maximum_running_per_provider: 1,
            maximum_running_per_tenant: 1,
            ..ProviderPoolLimits::default()
        },
        None,
    );
    let (session, control) = f.session(5000);
    let mut input = request(ap, HttpMethod::Get);
    input.headers.push(HttpHeader {
        name: "x-test".into(),
        value: "guest-secret".into(),
    });
    let done = f.provider.start(&session, input).unwrap().await.unwrap();
    assert_eq!(done.response.as_ref().ok().unwrap().body(), b"ok");
    assert_eq!(
        control
            .budget
            .remaining_at(std::time::Instant::now())
            .outbound_requests,
        29
    );
    drop(done);
    drop(session);
    server_a.await.unwrap();
    server_b.await.unwrap();
    f.clean().await;
}
#[tokio::test]
async fn redirected_path_is_checked_and_mutations_are_not_followed() {
    for method in [HttpMethod::Get, HttpMethod::Post] {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let port = listener.local_addr().unwrap().port();
        let server = tokio::spawn(async move {
            let (mut stream, _) = listener.accept().await.unwrap();
            read_request(&mut stream).await;
            stream.write_all(b"HTTP/1.1 302 Found\r\nLocation: /forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n").await.unwrap();
            drop(stream);
            assert!(
                tokio::time::timeout(Duration::from_millis(80), listener.accept())
                    .await
                    .is_err()
            );
        });
        let mut cfg = config(port);
        cfg.limits.maximum_redirects = 1;
        let f = Fixture::new(cfg);
        let (session, _) = f.session(5000);
        let done = f
            .provider
            .start(&session, request(port, method))
            .unwrap()
            .await;
        if method == HttpMethod::Get {
            assert!(matches!(done, Err(HttpError::PermissionDenied)));
        } else {
            let done = done.unwrap();
            assert_eq!(done.response.as_ref().ok().unwrap().status(), 302);
            drop(done);
        }
        drop(session);
        server.await.unwrap();
        f.clean().await;
    }
}
