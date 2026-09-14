use super::*;
fn certificate() -> (Vec<u8>, tokio_rustls::TlsAcceptor) {
    let cert = rcgen::generate_simple_self_signed(vec!["localhost".into()]).unwrap();
    let der = cert.cert.der().clone();
    let key = rustls::pki_types::PrivatePkcs8KeyDer::from(cert.signing_key.serialize_der());
    let mut tls = rustls::ServerConfig::builder_with_provider(Arc::new(
        rustls::crypto::ring::default_provider(),
    ))
    .with_safe_default_protocol_versions()
    .unwrap()
    .with_no_client_auth()
    .with_single_cert(vec![der.clone()], key.into())
    .unwrap();
    tls.alpn_protocols = vec![b"http/1.1".to_vec()];
    (der.to_vec(), tokio_rustls::TlsAcceptor::from(Arc::new(tls)))
}
#[tokio::test]
async fn tls_requires_both_approved_peer_and_correct_trusted_hostname() {
    for mode in ["valid", "untrusted", "wrong-name"] {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let port = listener.local_addr().unwrap().port();
        let (root, acceptor) = certificate();
        let server = tokio::spawn(async move {
            let (stream, _) = listener.accept().await.unwrap();
            match acceptor.accept(stream).await {
                Ok(mut stream) => {
                    assert_eq!(mode, "valid");
                    read_request(&mut stream).await;
                    stream
                        .write_all(
                            b"HTTP/1.1 200 OK\r\nContent-Length: 3\r\nConnection: close\r\n\r\ntls",
                        )
                        .await
                        .unwrap();
                }
                Err(_) => assert_ne!(mode, "valid"),
            }
        });
        let mut cfg = config(port);
        cfg.destinations[0].origin.scheme = "https".into();
        if mode == "wrong-name" {
            cfg.destinations[0].origin.host = "wrong.invalid".into();
        }
        if mode == "untrusted" {
            cfg.extra_roots.push(certificate().0);
        } else {
            cfg.extra_roots.push(root);
        }
        let host = cfg.destinations[0].origin.host.clone();
        let f = Fixture::new(cfg);
        let (session, _) = f.session(5000);
        let mut input = request(port, HttpMethod::Get);
        input.url = format!("https://{host}:{port}/allowed");
        let done = f.provider.start(&session, input).unwrap().await.unwrap();
        if mode == "valid" {
            assert_eq!(done.response.as_ref().ok().unwrap().body(), b"tls");
        } else {
            assert!(matches!(done.response, Err(HttpError::TlsFailed)));
        }
        drop(done);
        drop(session);
        server.await.unwrap();
        f.clean().await;
    }
}
#[tokio::test]
async fn stalled_tls_handshake_cancels_and_closes_without_application_effects() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let (sent, received) = tokio::sync::oneshot::channel();
    let server = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await.unwrap();
        let mut bytes = [0; 4096];
        assert!(stream.read(&mut bytes).await.unwrap() > 0);
        sent.send(()).unwrap();
        assert_eq!(
            tokio::time::timeout(Duration::from_secs(1), stream.read(&mut bytes))
                .await
                .unwrap()
                .unwrap(),
            0
        );
    });
    let mut cfg = config(port);
    cfg.destinations[0].origin.scheme = "https".into();
    cfg.extra_roots.push(certificate().0);
    let f = Fixture::new(cfg);
    let (session, control) = f.session(5000);
    let mut input = request(port, HttpMethod::Get);
    input.url = format!("https://localhost:{port}/allowed");
    let mut operation = f.provider.start(&session, input).unwrap();
    tokio::select! {_=&mut operation=>panic!("TLS peer is stalled"),_=received=>{}}
    control.probe.0.store(true, Ordering::Release);
    let done = operation.await.unwrap();
    assert!(matches!(done.response, Err(HttpError::Cancelled)));
    drop(done);
    drop(session);
    server.await.unwrap();
    f.clean().await;
}
