use super::*;
#[tokio::test]
async fn every_method_preserves_status_and_buffer_ownership() {
    for method in [
        HttpMethod::Get,
        HttpMethod::Head,
        HttpMethod::Post,
        HttpMethod::Put,
        HttpMethod::Patch,
        HttpMethod::Delete,
        HttpMethod::Options,
    ] {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let port = listener.local_addr().unwrap().port();
        let server = tokio::spawn(async move {
            let (mut stream, _) = listener.accept().await.unwrap();
            let wire = read_request(&mut stream).await;
            assert!(
                wire.starts_with(format!("{} /allowed HTTP/1.1\r\n", method.as_str()).as_bytes())
            );
            assert!(wire.ends_with(b"payload"));
            let body = if method == HttpMethod::Head { "" } else { "no" };
            stream.write_all(format!("HTTP/1.1 429 Too Many Requests\r\nContent-Length: 2\r\nContent-Type: text/plain\r\nConnection: close\r\n\r\n{body}").as_bytes()).await.unwrap();
        });
        let f = Fixture::new(config(port));
        let (session, _) = f.session(5000);
        let observer = session.observer();
        let mut input = request(port, method);
        input.body = Some(b"payload".to_vec());
        let completion = f.provider.start(&session, input).unwrap().await.unwrap();
        let response = completion.response.unwrap();
        assert_eq!(response.status(), 429);
        assert_eq!(
            response.body(),
            if method == HttpMethod::Head {
                b"".as_slice()
            } else {
                b"no".as_slice()
            }
        );
        assert_eq!(response.body_media_type(), Some("text/plain"));
        assert!(!response
            .headers()
            .any(|(n, _)| n == "connection" || n == "content-length"));
        drop(completion.owner);
        drop(session);
        assert!(!observer.is_quiescent());
        assert!(f.io.snapshot().result_bytes > 0);
        drop(response);
        assert!(observer.is_quiescent());
        server.await.unwrap();
        f.clean().await;
    }
}
#[tokio::test]
async fn policy_and_budget_reject_before_any_connection() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let f = Fixture::new(config(port));
    let (session, _) = f.session(5000);
    let mut denied = request(port, HttpMethod::Get);
    denied.url = format!("http://localhost:{port}/forbidden");
    assert!(matches!(
        f.provider.start(&session, denied).unwrap().await,
        Err(HttpError::PermissionDenied)
    ));
    let (mut execution, control) = f.request("tenant-mismatch", 5000);
    execution.activation.principal.tenant = Some(latent_core::TenantId("b".into()));
    assert!(f
        .broker
        .open_session(f.plan.clone(), &execution, &control, &f.publication)
        .is_err());
    assert!(
        tokio::time::timeout(Duration::from_millis(30), listener.accept())
            .await
            .is_err()
    );
    drop(session);
    f.clean().await;
}
#[tokio::test]
async fn lost_mutation_reply_is_uncertain_and_never_retried() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let server = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await.unwrap();
        let wire = read_request(&mut stream).await;
        assert!(String::from_utf8(wire)
            .unwrap()
            .contains("idempotency-key: explicit"));
        drop(stream);
        assert!(
            tokio::time::timeout(Duration::from_millis(100), listener.accept())
                .await
                .is_err()
        );
    });
    let f = Fixture::new(config(port));
    let (session, _) = f.session(5000);
    let mut input = request(port, HttpMethod::Post);
    input.idempotency_key = Some("explicit".into());
    let done = f.provider.start(&session, input).unwrap().await.unwrap();
    assert!(matches!(done.response, Err(HttpError::Uncertain)));
    drop(done);
    drop(session);
    server.await.unwrap();
    f.clean().await;
}
#[tokio::test]
async fn dropping_live_request_closes_socket_before_refund() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let (sent, received) = tokio::sync::oneshot::channel();
    let server = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await.unwrap();
        read_request(&mut stream).await;
        sent.send(()).unwrap();
        let mut byte = [0];
        assert_eq!(
            tokio::time::timeout(Duration::from_secs(1), stream.read(&mut byte))
                .await
                .unwrap()
                .unwrap(),
            0
        );
    });
    let f = Fixture::new(config(port));
    let (session, _) = f.session(5000);
    let observer = session.observer();
    let mut operation = f
        .provider
        .start(&session, request(port, HttpMethod::Get))
        .unwrap();
    tokio::select! { _=&mut operation=>panic!("unexpected response"), _=received=>{} }
    assert_eq!(f.pools.snapshot().unwrap().running_requests, 1);
    drop(operation);
    drop(session);
    assert!(observer.is_quiescent());
    server.await.unwrap();
    f.clean().await;
}
