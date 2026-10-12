fn exact_certificate(params: &rcgen::CertificateParams, key: &rcgen::KeyPair,
                     issuer: Option<&rcgen::Issuer<'_, rcgen::KeyPair>>,
                     wanted: usize) -> rcgen::Certificate {
    let mut payload = wanted - 512;
    for _ in 0..4 {
        let mut params = params.clone();
        let mut content = vec![4, 0x82, (payload >> 8) as u8, payload as u8];
        content.resize(payload + 4, 0);
        params.custom_extensions = vec![rcgen::CustomExtension::from_oid_content(
            &[1, 3, 6, 1, 4, 1, 55555, 1], content)];
        let cert = match issuer {
            Some(issuer) => params.signed_by(key, issuer).unwrap(),
            None => params.self_signed(key).unwrap(),
        };
        if cert.der().len() == wanted { return cert; }
        payload = if cert.der().len() < wanted { payload + wanted - cert.der().len() }
                  else { payload - (cert.der().len() - wanted) };
    }
    panic!("fixed Ed25519 certificate size did not converge");
}

fn authority_params(name: &str) -> rcgen::CertificateParams {
    let mut params = rcgen::CertificateParams::new(Vec::<String>::new()).unwrap();
    params.distinguished_name.push(rcgen::DnType::CommonName, name);
    params.is_ca = rcgen::IsCa::Ca(rcgen::BasicConstraints::Unconstrained);
    params.key_usages = vec![rcgen::KeyUsagePurpose::KeyCertSign, rcgen::KeyUsagePurpose::CrlSign,
                            rcgen::KeyUsagePurpose::DigitalSignature];
    params
}

#[tokio::test]
async fn private_maximum_valid_chain_roots_and_stapled_extension_retire_actual_owners() {
    use std::os::unix::fs::PermissionsExt;
    for tls12 in [false, true] {
        let directory = tempfile::tempdir().unwrap();
        std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
        let mut roots = Vec::new();
        let mut root_certificate = None;
        let mut root_issuer = None;
        for ordinal in 0..8 {
            let params = authority_params(&format!("profile-root-{ordinal}"));
            let key = rcgen::KeyPair::generate_for(&rcgen::PKCS_ED25519).unwrap();
            let cert = exact_certificate(&params, &key, None, 4096);
            let file = directory.path().join(format!("root-{ordinal}.der"));
            std::fs::write(&file, cert.der()).unwrap();
            std::fs::set_permissions(&file, std::fs::Permissions::from_mode(0o600)).unwrap();
            roots.push(crate::StreamTrustRoot { file, sha256: format!("sha256:{:x}",
                latent_core::digest::HexDigest(Sha256::digest(cert.der()))) });
            if ordinal == 0 {
                root_certificate = Some(cert.der().clone());
                root_issuer = Some(rcgen::Issuer::new(params, key));
            }
        }
        assert_eq!(roots.len(), 8);
        assert_eq!(roots.iter().map(|root| std::fs::metadata(&root.file).unwrap().len()).sum::<u64>(), 32768);
        let mut issuer = root_issuer.unwrap();
        let mut chain = vec![root_certificate.unwrap()];
        // Exact pinned webpki permits six subordinate CAs; leaf+six+root fills
        // the captured TLS parser's eight-entry profile without a fake chain.
        for ordinal in 0..6 {
            let params = authority_params(&format!("profile-intermediate-{ordinal}"));
            let key = rcgen::KeyPair::generate_for(&rcgen::PKCS_ED25519).unwrap();
            let cert = exact_certificate(&params, &key, Some(&issuer), 3300);
            chain.insert(0, cert.der().clone());
            issuer = rcgen::Issuer::new(params, key);
        }
        let mut params = rcgen::CertificateParams::new(vec!["stream.test".into()]).unwrap();
        params.extended_key_usages = vec![rcgen::ExtendedKeyUsagePurpose::ServerAuth];
        let key = rcgen::KeyPair::generate().unwrap();
        let leaf = exact_certificate(&params, &key, Some(&issuer), 3300);
        chain.insert(0, leaf.der().clone());
        assert_eq!(chain.len(), 8);
        let key = rustls::pki_types::PrivateKeyDer::Pkcs8(
            rustls::pki_types::PrivatePkcs8KeyDer::from(key.serialize_der()));
        let version = if tls12 { &rustls::version::TLS12 } else { &rustls::version::TLS13 };
        // TLS1.3 per-entry encoded extension overhead is eight bytes, so 4088
        // OCSP payload bytes fill the unchanged 4096-byte entry-extension cap.
        let mut server = rustls::ServerConfig::builder_with_provider(Arc::new(
            rustls::crypto::ring::default_provider())).with_protocol_versions(&[version]).unwrap()
            .with_no_client_auth().with_single_cert_with_ocsp(chain, key, vec![0; 4088]).unwrap();
        server.send_tls13_tickets = 0;
        let acceptor = TlsAcceptor::from(Arc::new(server));
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let port = listener.local_addr().unwrap().port();
        let mut configuration = config();
        configuration.destinations[0].endpoint.host = "stream.test".into();
        configuration.destinations[0].endpoint.port = port;
        configuration.destinations[0].endpoint.transport = StreamTransport::HostTls;
        configuration.destinations[0].tls = Some(crate::StreamTlsConfig { server_name: "stream.test".into(), roots });
        let fixture = Fixture::new(configuration);
        let peer = tokio::spawn(async move {
            let (socket, _) = listener.accept().await.unwrap();
            let mut tls = acceptor.accept(socket).await.unwrap();
            assert_eq!(tls.get_ref().1.protocol_version(), Some(if tls12 {
                rustls::ProtocolVersion::TLSv1_2 } else { rustls::ProtocolVersion::TLSv1_3 }));
            let mut message = [0; 4];
            tls.read_exact(&mut message).await.unwrap();
            assert_eq!(&message, b"PING");
            tls.write_all(b"PONG").await.unwrap();
            tls.shutdown().await.unwrap();
        });
        let (session, control) = fixture.session(5000);
        let stream = fixture.provider.start(&session, request(&fixture)).unwrap().await.unwrap();
        assert!(control.budget.host_memory_bytes() >= 256 * 1024);
        assert_eq!(stream.write(b"PING".to_vec(), None).unwrap().await.unwrap(), 4);
        let mut body = Vec::new();
        while let Some(mut chunk) = stream.read(2, None).unwrap().await.unwrap() {
            body.extend(chunk.copy_bytes().unwrap());
        }
        assert_eq!(body, b"PONG");
        stream.close().await.unwrap();
        tokio::time::timeout(Duration::from_secs(2), peer).await.unwrap().unwrap();
        assert_eq!(control.budget.host_memory_bytes(), 0);
        drop(session);
        fixture.clean().await;
    }
}
