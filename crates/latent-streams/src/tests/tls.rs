//! Real TLS peers and existing broker/Io/activation owners, not language proof.
use super::{config, fixture::Fixture};
use crate::{StreamErrorCode, StreamTlsConfig, StreamTrustRoot};
use latent_capabilities::broker::network::{
    OutboundStreamInvoker, StreamConnectRequest, StreamShutdown,
};
use latent_policy::capability::StreamTransport;
// Peer fixtures keep the ordinary upstream TLS type; only the provider is bounded.
use rustls_upstream as rustls;
use sha2::{Digest, Sha256};
use std::{
    sync::Arc,
    time::{Duration, Instant},
};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::TcpListener,
};
use tokio_rustls::TlsAcceptor;

struct Peer {
    listener: TcpListener,
    acceptor: TlsAcceptor,
    directory: tempfile::TempDir,
    root: StreamTrustRoot,
}
impl Peer {
    async fn new() -> Self {
        use std::os::unix::fs::PermissionsExt;
        let certified = rcgen::generate_simple_self_signed(vec!["stream.test".into()]).unwrap();
        let key = rustls::pki_types::PrivateKeyDer::Pkcs8(
            rustls::pki_types::PrivatePkcs8KeyDer::from(certified.signing_key.serialize_der()),
        );
        let mut server = rustls::ServerConfig::builder_with_provider(Arc::new(
            rustls::crypto::ring::default_provider(),
        ))
        .with_safe_default_protocol_versions()
        .unwrap()
        .with_no_client_auth()
        .with_single_cert(vec![certified.cert.der().clone()], key)
        .unwrap();
        server.send_tls13_tickets = 0;
        let directory = tempfile::tempdir().unwrap();
        std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
        let path = directory.path().join("root.der");
        std::fs::write(&path, certified.cert.der()).unwrap();
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600)).unwrap();
        let root = StreamTrustRoot {
            file: path,
            sha256: format!(
                "sha256:{:x}",
                latent_core::digest::HexDigest(Sha256::digest(certified.cert.der()))
            ),
        };
        Self {
            listener: TcpListener::bind("127.0.0.1:0").await.unwrap(),
            acceptor: TlsAcceptor::from(Arc::new(server)),
            directory,
            root,
        }
    }
    fn config(&self) -> crate::StreamProviderConfig {
        let mut value = config();
        let destination = &mut value.destinations[0];
        destination.endpoint.host = "stream.test".into();
        destination.endpoint.port = self.listener.local_addr().unwrap().port();
        destination.endpoint.transport = StreamTransport::HostTls;
        destination.tls = Some(StreamTlsConfig {
            server_name: "stream.test".into(),
            roots: vec![self.root.clone()],
        });
        value
    }
}
fn request(fixture: &Fixture) -> StreamConnectRequest {
    StreamConnectRequest {
        endpoint: fixture.provider.inner.config.destinations[0]
            .endpoint
            .clone(),
        timeout_millis: None,
    }
}

#[tokio::test]
async fn unqualified_tls_installation_fails_before_contact_and_leaves_no_owner() {
    let peer = Peer::new().await;
    let fixture = Fixture::new(config());
    let before = fixture.pools.snapshot().unwrap();
    let failure = crate::StreamProvider::install_for_qualification(
        fixture.pools.clone(),
        "tls-unqualified",
        1,
        0,
        peer.config(),
    )
    .err()
    .unwrap();
    assert_eq!(failure.code, StreamErrorCode::Unsupported);
    assert!(
        tokio::time::timeout(Duration::from_millis(20), peer.listener.accept())
            .await
            .is_err()
    );
    assert_eq!(
        fixture.io.snapshot(),
        latent_capabilities::broker::io::IoSnapshot::default()
    );
    assert_eq!(fixture.pools.snapshot().unwrap(), before);
    fixture.clean().await;
}

#[tokio::test]
async fn direct_host_tls_validates_peer_transfers_and_retires_original_charges() {
    let peer = Peer::new().await;
    let fixture = Fixture::for_tls_accounting(peer.config());
    let original = fixture.provider.reference();
    let server = tokio::spawn(async move {
        let (socket, _) = peer.listener.accept().await.unwrap();
        let mut tls = peer.acceptor.accept(socket).await.unwrap();
        let mut message = [0; 4];
        tls.read_exact(&mut message).await.unwrap();
        assert_eq!(&message, b"PING");
        tls.write_all(b"one").await.unwrap();
        tls.write_all(b"two").await.unwrap();
        tls.shutdown().await.unwrap();
        drop(peer.directory);
    });
    let (session, control) = fixture.session(5000);
    let stream = fixture
        .provider
        .start(&session, request(&fixture))
        .unwrap()
        .await
        .unwrap();
    assert!(control.budget.host_memory_bytes() >= 256 * 1024);
    assert_eq!(
        stream.write(b"PING".to_vec(), None).unwrap().await.unwrap(),
        4
    );
    assert_eq!(
        stream.shutdown(StreamShutdown::Send).err().unwrap().code,
        StreamErrorCode::Unsupported
    );
    let mut bytes = Vec::new();
    while let Some(mut chunk) = stream.read(2, None).unwrap().await.unwrap() {
        bytes.extend(chunk.copy_bytes().unwrap());
    }
    assert_eq!(bytes, b"onetwo");
    assert_eq!(stream.inspect().accepted_write_bytes, 4);
    assert_eq!(
        fixture.provider.reference().configuration_digest(),
        original.configuration_digest()
    );
    stream.close().await.unwrap();
    tokio::time::timeout(Duration::from_secs(1), server)
        .await
        .unwrap()
        .unwrap();
    assert_eq!(control.budget.host_memory_bytes(), 0);
    drop(session);
    fixture.clean().await;
}

#[tokio::test]
async fn wrong_tls_hostname_fails_closed_without_cleartext_fallback() {
    let peer = Peer::new().await;
    let mut configuration = peer.config();
    configuration.destinations[0].endpoint.host = "wrong.stream.test".into();
    configuration.destinations[0]
        .tls
        .as_mut()
        .unwrap()
        .server_name = "wrong.stream.test".into();
    let fixture = Fixture::for_tls_accounting(configuration);
    let server = tokio::spawn(async move {
        let (socket, _) = peer.listener.accept().await.unwrap();
        assert!(peer.acceptor.accept(socket).await.is_err());
    });
    let (session, control) = fixture.session(5000);
    let result = fixture
        .provider
        .start(&session, request(&fixture))
        .unwrap()
        .await;
    assert_eq!(result.err().unwrap().code, StreamErrorCode::TlsFailed);
    tokio::time::timeout(Duration::from_secs(1), server)
        .await
        .unwrap()
        .unwrap();
    assert_eq!(control.budget.host_memory_bytes(), 0);
    assert_eq!(fixture.provider.usage().unwrap().connections, 0);
    drop(session);
    fixture.clean().await;
}

#[tokio::test]
async fn protected_root_replacement_digest_and_link_denials_precede_contact() {
    use std::os::unix::{fs::symlink, fs::PermissionsExt};
    let peer = Peer::new().await;
    let mut configuration = peer.config();
    let tls = configuration.destinations[0].tls.as_mut().unwrap();
    tls.roots[0].sha256 = format!("sha256:{}", "0".repeat(64));
    assert_eq!(
        crate::tls::configure(tls).err().unwrap().code,
        StreamErrorCode::TlsFailed
    );
    tls.roots[0] = peer.root.clone();
    let alias = peer.directory.path().join("alias.der");
    symlink(&peer.root.file, &alias).unwrap();
    tls.roots[0].file = alias;
    assert_eq!(
        crate::tls::configure(tls).err().unwrap().code,
        StreamErrorCode::TlsFailed
    );
    tls.roots[0] = peer.root.clone();
    std::fs::set_permissions(&peer.root.file, std::fs::Permissions::from_mode(0o622)).unwrap();
    assert_eq!(
        crate::tls::configure(tls).err().unwrap().code,
        StreamErrorCode::TlsFailed
    );
    assert!(
        tokio::time::timeout(Duration::from_millis(20), peer.listener.accept())
            .await
            .is_err()
    );
}

#[tokio::test]
async fn stalled_tls_handshake_uses_original_deadline_and_physical_owner() {
    let peer = Peer::new().await;
    let fixture = Fixture::for_tls_accounting(peer.config());
    let server = tokio::spawn(async move {
        let (mut socket, _) = peer.listener.accept().await.unwrap();
        let mut bytes = Vec::new();
        socket.read_to_end(&mut bytes).await.unwrap();
        assert!(!bytes.is_empty()); // A single real ClientHello, no fallback.
    });
    let (session, control) = fixture.session(200);
    let began = Instant::now();
    let result = fixture
        .provider
        .start(&session, request(&fixture))
        .unwrap()
        .await;
    assert!(matches!(
        result.err().unwrap().code,
        StreamErrorCode::Timeout | StreamErrorCode::Cancelled
    ));
    assert!(began.elapsed() < Duration::from_secs(2));
    tokio::time::timeout(Duration::from_secs(1), server)
        .await
        .unwrap()
        .unwrap();
    assert_eq!(control.budget.host_memory_bytes(), 0);
    drop(session);
    fixture.clean().await;
}

#[tokio::test]
async fn tls_rotation_preserves_pending_original_owner_until_peer_socket_retires() {
    use crate::StreamLifecycle;
    let peer = Peer::new().await;
    let configuration = peer.config();
    let fixture = Fixture::for_tls_accounting(configuration.clone());
    let lifecycle =
        StreamLifecycle::from_installed_for_qualification("streams", fixture.provider.clone())
            .unwrap();
    let (entered, acknowledged) = tokio::sync::oneshot::channel();
    let server = tokio::spawn(async move {
        let (socket, _) = peer.listener.accept().await.unwrap();
        let mut tls = peer.acceptor.accept(socket).await.unwrap();
        entered.send(()).unwrap();
        let mut byte = [0];
        assert!(matches!(tls.read(&mut byte).await, Ok(0) | Err(_)));
    });
    let (session, control) = fixture.session(5000);
    let stream = lifecycle
        .start(&session, request(&fixture))
        .unwrap()
        .await
        .unwrap();
    acknowledged.await.unwrap();
    let pending = stream.read(4096, None).unwrap();
    assert_eq!(lifecycle.status().unwrap().usage.pending_operations, 1);
    let replacement = lifecycle
        .rotate_tls_for_accounting_reference(1, 2, configuration)
        .unwrap();
    assert_eq!(replacement.configuration_epoch(), 2);
    assert_eq!(fixture.pools.snapshot().unwrap().connections, 1);
    assert!(control.budget.host_memory_bytes() >= 256 * 1024);
    assert!(lifecycle.start(&session, request(&fixture)).is_err());
    assert_eq!(pending.await.err().unwrap().code, StreamErrorCode::Revoked);
    tokio::time::timeout(Duration::from_secs(1), server)
        .await
        .unwrap()
        .unwrap();
    assert_eq!(lifecycle.status().unwrap().usage.connections, 0);
    assert!(control.budget.host_memory_bytes() > 0);
    drop(stream);
    assert_eq!(control.budget.host_memory_bytes(), 0);
    drop(session);
    drop(lifecycle);
    fixture.clean().await;
}

fn exact_certificate(
    params: &rcgen::CertificateParams,
    key: &rcgen::KeyPair,
    issuer: Option<&rcgen::Issuer<'_, rcgen::KeyPair>>,
    wanted: usize,
) -> rcgen::Certificate {
    let mut payload = wanted - 512;
    for _ in 0..4 {
        let mut params = params.clone();
        let [high, low] = u16::try_from(payload)
            .expect("bounded extension")
            .to_be_bytes();
        let mut content = vec![4, 0x82, high, low];
        content.resize(payload + 4, 0);
        params.custom_extensions = vec![rcgen::CustomExtension::from_oid_content(
            &[1, 3, 6, 1, 4, 1, 55555, 1],
            content,
        )];
        let cert = match issuer {
            Some(issuer) => params.signed_by(key, issuer).unwrap(),
            None => params.self_signed(key).unwrap(),
        };
        if cert.der().len() == wanted {
            return cert;
        }
        payload = if cert.der().len() < wanted {
            payload + wanted - cert.der().len()
        } else {
            payload - (cert.der().len() - wanted)
        };
    }
    panic!("fixed Ed25519 certificate size did not converge");
}

fn authority_params(name: &str) -> rcgen::CertificateParams {
    let mut params = rcgen::CertificateParams::new(Vec::<String>::new()).unwrap();
    params
        .distinguished_name
        .push(rcgen::DnType::CommonName, name);
    params.is_ca = rcgen::IsCa::Ca(rcgen::BasicConstraints::Unconstrained);
    params.key_usages = vec![
        rcgen::KeyUsagePurpose::KeyCertSign,
        rcgen::KeyUsagePurpose::CrlSign,
        rcgen::KeyUsagePurpose::DigitalSignature,
    ];
    params
}

#[expect(
    clippy::too_many_lines,
    reason = "one real maximum-valid profile preserves every setup and retirement barrier"
)]
#[tokio::test]
async fn current_maximum_valid_chain_roots_and_stapled_extension_retire_actual_owners() {
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
            roots.push(crate::StreamTrustRoot {
                file,
                sha256: format!(
                    "sha256:{:x}",
                    latent_core::digest::HexDigest(Sha256::digest(cert.der()))
                ),
            });
            if ordinal == 0 {
                root_certificate = Some(cert.der().clone());
                root_issuer = Some(rcgen::Issuer::new(params, key));
            }
        }
        assert_eq!(roots.len(), 8);
        assert_eq!(
            roots
                .iter()
                .map(|root| std::fs::metadata(&root.file).unwrap().len())
                .sum::<u64>(),
            32768
        );
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
            rustls::pki_types::PrivatePkcs8KeyDer::from(key.serialize_der()),
        );
        let version = if tls12 {
            &rustls::version::TLS12
        } else {
            &rustls::version::TLS13
        };
        // TLS1.3 per-entry encoded extension overhead is eight bytes, so 4088
        // OCSP payload bytes fill the unchanged 4096-byte entry-extension cap.
        let mut server = rustls::ServerConfig::builder_with_provider(Arc::new(
            rustls::crypto::ring::default_provider(),
        ))
        .with_protocol_versions(&[version])
        .unwrap()
        .with_no_client_auth()
        .with_single_cert_with_ocsp(chain, key, vec![0; 4088])
        .unwrap();
        server.send_tls13_tickets = 0;
        let acceptor = TlsAcceptor::from(Arc::new(server));
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let port = listener.local_addr().unwrap().port();
        let mut configuration = config();
        configuration.destinations[0].endpoint.host = "stream.test".into();
        configuration.destinations[0].endpoint.port = port;
        configuration.destinations[0].endpoint.transport = StreamTransport::HostTls;
        configuration.destinations[0].tls = Some(crate::StreamTlsConfig {
            server_name: "stream.test".into(),
            roots,
        });
        let fixture = Fixture::for_tls_accounting(configuration);
        let peer = tokio::spawn(async move {
            let (socket, _) = listener.accept().await.unwrap();
            let mut tls = acceptor.accept(socket).await.unwrap();
            assert_eq!(
                tls.get_ref().1.protocol_version(),
                Some(if tls12 {
                    rustls::ProtocolVersion::TLSv1_2
                } else {
                    rustls::ProtocolVersion::TLSv1_3
                })
            );
            let mut message = [0; 4];
            tls.read_exact(&mut message).await.unwrap();
            assert_eq!(&message, b"PING");
            tls.write_all(b"PONG").await.unwrap();
            tls.shutdown().await.unwrap();
        });
        let (session, control) = fixture.session(5000);
        let stream = fixture
            .provider
            .start(&session, request(&fixture))
            .unwrap()
            .await
            .unwrap();
        assert!(control.budget.host_memory_bytes() >= 256 * 1024);
        assert_eq!(
            stream.write(b"PING".to_vec(), None).unwrap().await.unwrap(),
            4
        );
        let mut body = Vec::new();
        while let Some(mut chunk) = stream.read(2, None).unwrap().await.unwrap() {
            body.extend(chunk.copy_bytes().unwrap());
        }
        assert_eq!(body, b"PONG");
        stream.close().await.unwrap();
        tokio::time::timeout(Duration::from_secs(2), peer)
            .await
            .unwrap()
            .unwrap();
        assert_eq!(control.budget.host_memory_bytes(), 0);
        drop(session);
        fixture.clean().await;
    }
}

#[tokio::test]
async fn retained_trust_configuration_refunds_only_after_the_last_physical_owner() {
    let peer = Peer::new().await;
    let fixture = Fixture::for_tls_accounting(peer.config());
    let pools = Arc::clone(&fixture.pools);
    let io = Arc::clone(&fixture.io);
    let retained = Arc::clone(fixture.provider.inner.tls[0].as_ref().unwrap());
    fixture.provider.retire();
    drop(fixture);
    assert_eq!(Arc::strong_count(&retained), 1);
    assert_eq!(Arc::strong_count(&retained.config), 1);
    assert!(
        tokio::time::timeout(Duration::from_millis(20), peer.listener.accept())
            .await
            .is_err()
    );
    let held = pools.snapshot().unwrap().metadata_bytes;
    assert!(held >= crate::tls::ROOT_ALLOWANCE);
    drop(retained);
    assert_eq!(
        pools.snapshot().unwrap().metadata_bytes,
        held - crate::tls::ROOT_ALLOWANCE
    );
    let final_state = pools
        .shutdown(Instant::now() + Duration::from_secs(2))
        .await
        .unwrap();
    assert!(final_state.is_clean());
    assert_eq!(
        io.snapshot(),
        latent_capabilities::broker::io::IoSnapshot::default()
    );
}
