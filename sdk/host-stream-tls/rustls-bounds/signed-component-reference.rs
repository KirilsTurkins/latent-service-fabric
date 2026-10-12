async fn configured_private_tls(root: &std::path::Path, port: u16, trust: latent_streams::StreamTrustRoot) -> Fixture {
    let caller = packages::outbound_streams(component::bytes_with_contract(
        port,
        super::component::CALLER,
    ));
    let callee = packages::callee(42);
    let signers = package::Signers::new(latent_signing::PROVENANCE_BUILD_TYPE);
    let mut config = configuration(port);
    config.destinations[0].endpoint.transport = StreamTransport::HostTls;
    config.destinations[0].tls = Some(latent_streams::StreamTlsConfig {
        server_name: "127.0.0.1".into(), roots: vec![trust]
    });
    let mut uploads = vec![];
    for bundle in [&caller, &callee] {
        let mut observation = provenance::observation();
        observation.source.repository =
            "https://github.com/KirilsTurkins/latent-service-fabric".into();
        observation.component_digest = bundle.layout().component_release().unwrap().0;
        observation.component_size = bundle.blob("component.wasm").unwrap().len() as u64;
        let mut source = include_bytes!("../outbound_streams/component.rs").to_vec();
        source.extend_from_slice(include_bytes!("component.rs"));
        source.extend_from_slice(include_bytes!("packages.rs"));
        source.extend_from_slice(include_bytes!("outbound/owners.rs"));
        source.extend_from_slice(include_bytes!(
            "../../../../wit/platform/network/package.wit"
        ));
        source.extend_from_slice(&serde_json::to_vec(&config).unwrap());
        observation.source.snapshot_digest =
            latent_artifacts::package::artifact_blob_digest(&source).into_string();
        let material = observation
            .materials
            .iter_mut()
            .find(|material| material.name == "source-snapshot")
            .unwrap();
        material
            .digest
            .clone_from(&observation.source.snapshot_digest);
        material.size = source.len() as u64;
        uploads.push(signers.upload(bundle, &observation));
    }
    let catalog = package::catalog(root, signers.policy, Some(packages::budget().memory_bytes));
    for upload in uploads {
        catalog
            .admit_package(&TenantId("tenant-a".into()), upload, &mut |_| Ok(()))
            .await
            .unwrap();
    }
    Box::pin(Fixture::with_outbound_streams(
        1,
        (catalog, caller, callee),
        config,
    ))
    .await
}


#[tokio::test]
async fn private_signed_host_tls_node_admission_fresh_cells_and_physical_retirement() {
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
    let trust = latent_streams::StreamTrustRoot { file,
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
    let root = tempfile::tempdir().unwrap();
    let mut f = configured_private_tls(root.path(), port, trust).await;
    for ordinal in 0..3 {
        success(f.manager.start(f.request(&format!("private-signed-tls-{ordinal}"), 2)).unwrap().await);
        idle(&f).await;
    }
    peer.await.unwrap();
    assert_eq!(f.backend.resource_snapshot().stores_created, 3);
    f.streams.take().unwrap().shutdown().await;
}
