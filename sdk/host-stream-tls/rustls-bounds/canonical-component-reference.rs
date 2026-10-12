#[tokio::test]
async fn private_canonical_host_tls_round_trip_and_fresh_store_retire_actual_owners() {
    use std::{os::unix::fs::PermissionsExt, sync::Arc};
    use sha2::{Digest, Sha256};
    let certified = rcgen::generate_simple_self_signed(vec!["127.0.0.1".into()]).unwrap();
    let key = rustls::pki_types::PrivateKeyDer::Pkcs8(
        rustls::pki_types::PrivatePkcs8KeyDer::from(certified.signing_key.serialize_der()));
    let mut configuration = rustls::ServerConfig::builder_with_provider(Arc::new(
        rustls::crypto::ring::default_provider()))
        .with_protocol_versions(&[&rustls::version::TLS13]).unwrap()
        .with_no_client_auth().with_single_cert(vec![certified.cert.der().clone()], key).unwrap();
    configuration.send_tls13_tickets = 0;
    let protected = tempfile::tempdir().unwrap();
    std::fs::set_permissions(protected.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
    let file = protected.path().join("root.der");
    std::fs::write(&file, certified.cert.der()).unwrap();
    std::fs::set_permissions(&file, std::fs::Permissions::from_mode(0o600)).unwrap();
    let root = latent_streams::StreamTrustRoot { file,
        sha256: format!("sha256:{:x}", latent_core::digest::HexDigest(Sha256::digest(certified.cert.der()))) };
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let acceptor = tokio_rustls::TlsAcceptor::from(Arc::new(configuration));
    let peer = tokio::spawn(async move {
        for _ in 0..3 {
            let (socket, _) = listener.accept().await.unwrap();
            let mut tls = acceptor.accept(socket).await.unwrap();
            assert_eq!(tls.get_ref().1.protocol_version(), Some(rustls::ProtocolVersion::TLSv1_3));
            let mut message = [0; 4];
            tls.read_exact(&mut message).await.unwrap();
            assert_eq!(&message, b"PING");
            tls.write_all(b"PONG").await.unwrap();
            tls.shutdown().await.unwrap();
        }
    });
    let fixture = Fixture::with_private_tls(port, None, Some(root)).await;
    for ordinal in 0..3 {
        let (request, control) = fixture.request(&format!("private-host-tls-{ordinal}"), 2);
        let report = fixture.backend.invoke_contained(request, &control).await;
        let GuestOutcome::Returned { output, consumption, .. } = report.outcome.unwrap() else {
            panic!("actual canonical TLS guest must return")
        };
        assert_eq!(serde_json::from_slice::<serde_json::Value>(&output).unwrap(), serde_json::json!([4]));
        assert_eq!(report.cleanup, ExecutionCleanup::Reusable);
        let finalized = control.budget.finalize_at(Some(&consumption), Instant::now());
        assert!(finalized.violation().is_none());
        fixture.idle();
        assert_eq!(fixture.io.snapshot(), IoSnapshot::default());
        assert_eq!(control.budget.host_memory_bytes(), 0);
        assert_eq!(fixture.pools.snapshot().unwrap().connections, 0);
    }
    peer.await.unwrap();
    assert!(fixture.pools.shutdown(Instant::now() + Duration::from_secs(2)).await.unwrap().is_clean());
}
