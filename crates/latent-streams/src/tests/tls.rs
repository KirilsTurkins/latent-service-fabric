//! Real TLS peers and existing broker/Io/activation owners, not language proof.
use super::{config, fixture::Fixture};
use crate::{StreamErrorCode, StreamTlsConfig, StreamTrustRoot};
use latent_capabilities::broker::network::{
    OutboundStreamInvoker, StreamConnectRequest, StreamShutdown,
};
use latent_policy::capability::StreamTransport;
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

#[expect(
    dead_code,
    reason = "prepared actual TLS controls held until the unchanged parser accounting gate is proved"
)]
async fn direct_host_tls_validates_peer_transfers_and_retires_original_charges() {
    let peer = Peer::new().await;
    let fixture = Fixture::new(peer.config());
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

#[expect(
    dead_code,
    reason = "prepared actual TLS controls held until the unchanged parser accounting gate is proved"
)]
async fn wrong_tls_hostname_fails_closed_without_cleartext_fallback() {
    let peer = Peer::new().await;
    let mut configuration = peer.config();
    configuration.destinations[0].endpoint.host = "wrong.stream.test".into();
    configuration.destinations[0]
        .tls
        .as_mut()
        .unwrap()
        .server_name = "wrong.stream.test".into();
    let fixture = Fixture::new(configuration);
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

#[expect(
    dead_code,
    reason = "prepared actual TLS controls held until the unchanged parser accounting gate is proved"
)]
async fn stalled_tls_handshake_uses_original_deadline_and_physical_owner() {
    let peer = Peer::new().await;
    let fixture = Fixture::new(peer.config());
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

#[expect(
    dead_code,
    reason = "prepared actual TLS controls held until the unchanged parser accounting gate is proved"
)]
async fn tls_rotation_preserves_pending_original_owner_until_peer_socket_retires() {
    use crate::StreamLifecycle;
    let peer = Peer::new().await;
    let configuration = peer.config();
    let fixture = Fixture::new(configuration.clone());
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
    let replacement = lifecycle.rotate(1, 2, configuration).unwrap();
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
