use super::fixture::*;
use serde_json::json;
use std::{sync::Arc, time::Duration};
use tempfile::TempDir;
use tokio::io::{AsyncReadExt, AsyncWriteExt};

#[tokio::test]
async fn malformed_and_denied_http_requests_never_accept_an_activation() {
    let root = TempDir::new().unwrap();
    let value = config(&root);
    let fixture = Fixture::start(root, value, None).await;
    for (raw, expected) in [
        (format!("GET / HTTP/1.1\r\nHost: {AUTHORITY}\r\n\r\n"), 401),
        (request("GET", "/", "wrong-credential", 0, true), 401),
        (format!("GET / HTTP/1.1\r\nHost: {AUTHORITY}\r\nContent-Length: 0\r\nContent-Length: 0\r\n\r\n"), 400),
        (format!("GET / HTTP/1.1\r\nHost: {AUTHORITY}\r\nConnection: authorization\r\n\r\n"), 400),
        (format!("GET / HTTP/1.1\r\nHost: {AUTHORITY}\r\nForwarded: for=admin\r\n\r\n"), 400),
        (format!("GET / HTTP/1.1\r\nHost: {AUTHORITY}\r\nX-LSF-Tenant: other\r\n\r\n"), 400),
        (format!("POST / HTTP/1.1\r\nHost: {AUTHORITY}\r\nTransfer-Encoding: chunked\r\n\r\n"), 400),
        (format!("GET / HTTP/1.1\r\nHost: {AUTHORITY}\r\nHost: other.example.test\r\n\r\n"), 400),
        (format!("POST / HTTP/1.1\r\nHost: {AUTHORITY}\r\nContent-Length: 65537\r\n\r\n"), 413),
        (format!("GET / HTTP/1.1\r\nHost: {AUTHORITY}\r\nExpect: 100-continue\r\n\r\n"), 417),
        (format!("GET / HTTP/1.1\r\nHost: {AUTHORITY}\r\nAuthorization: Bearer {TOKEN}\r\nAuthorization: Bearer {OTHER}\r\n\r\n"), 400),
        (format!("GET / HTTP/1.1\nHost: {AUTHORITY}\r\n\r\n"), 400),
        (format!("GET / HTTP/1.1\r\nHost: {AUTHORITY}\r\nX-Data: {}\r\n\r\n", "z".repeat(16 * 1024)), 431),
        (format!("GET / HTTP/1.1\r\nHost: {AUTHORITY}\r\nX-Data: {}", "z".repeat(32 * 1024)), 431),
        (request("GET", "/", TOKEN, 0, true), 404),
    ] {
        let mut socket = fixture.connect().await;
        socket.write_all(raw.as_bytes()).await.unwrap();
        let (status, headers, _) = response(&mut socket).await;
        assert_eq!(status, expected);
        assert!(headers.contains("Connection: close"));
        drop(socket);
        fixture.idle().await;
        assert_eq!(fixture.node.manager.journal().snapshot().terminal, 0);
    }
    let inventory = fixture.node.inventory().unwrap();
    assert!(format!("{inventory:?}").contains("http-listener"));
    fixture.shutdown().await;
}
#[tokio::test]
async fn silent_and_trickling_connections_are_reclaimed_under_global_saturation() {
    let root = TempDir::new().unwrap();
    let mut value = config(&root);
    value["httpIngress"]["limits"]["maximumConnections"] = json!(2);
    let fixture = Fixture::start(root, value, None).await;
    let mut silent = fixture.connect().await;
    let mut slow = fixture.connect().await;
    slow.write_all(b"G").await.unwrap();
    wait(|| fixture.node.http_snapshot().unwrap().connections == 2).await;
    let mut excess = fixture.connect().await;
    assert!(matches!(
        tokio::time::timeout(Duration::from_secs(2), excess.read_u8()).await,
        Ok(Err(_))
    ));
    // Keep transmitting beyond the original head deadline. An idle-only timer
    // that resets on each byte would fail this bounded reclamation check.
    trickle_until_closed(slow, Duration::from_secs(1)).await;
    fixture.idle().await;
    assert!(silent.read_u8().await.is_err());
    assert_eq!(call(&fixture, "/").await.0, 404);
    fixture.shutdown().await;
}

#[tokio::test]
async fn proxy_peers_are_explicit_and_forwarded_headers_never_supply_identity() {
    for allowed in [false, true] {
        let root = TempDir::new().unwrap();
        let mut value = config(&root);
        value["httpIngress"]["transport"] = json!({"mode":"trusted-proxy", "peers":[if allowed { "127.0.0.1" } else { "127.0.0.2" }]});
        let fixture = Fixture::start(root, value, None).await;
        let mut socket = fixture.connect().await;
        if allowed {
            socket.write_all(format!("GET / HTTP/1.1\r\nHost: {AUTHORITY}\r\nForwarded: for=administrator;proto=https\r\nX-Forwarded-User: administrator\r\n\r\n").as_bytes()).await.unwrap();
            assert_eq!(response(&mut socket).await.0, 401);
        } else {
            assert!(
                tokio::time::timeout(Duration::from_secs(2), socket.read_u8())
                    .await
                    .unwrap()
                    .is_err()
            );
        }
        drop(socket);
        fixture.idle().await;
        fixture.shutdown().await;
    }
}

pub(super) fn tls_files(root: &TempDir) -> (std::path::PathBuf, std::path::PathBuf) {
    use std::os::unix::fs::PermissionsExt;
    let certificate = root.path().join("certificate.pem");
    let key = root.path().join("key.pem");
    let result = std::process::Command::new("openssl")
        .args([
            "req",
            "-x509",
            "-newkey",
            "ec",
            "-pkeyopt",
            "ec_paramgen_curve:P-256",
            "-nodes",
            "-days",
            "1",
            "-subj",
            "/CN=localhost",
            "-addext",
            "subjectAltName=DNS:localhost,DNS:web.example.test",
            "-addext",
            "basicConstraints=critical,CA:FALSE",
            "-keyout",
        ])
        .arg(&key)
        .arg("-out")
        .arg(&certificate)
        .output()
        .expect("OpenSSL test prerequisite");
    assert!(result.status.success());
    std::fs::set_permissions(&key, std::fs::Permissions::from_mode(0o600)).unwrap();
    (certificate, key)
}
pub(super) fn connector(certificate: &std::path::Path) -> tokio_rustls::TlsConnector {
    use rustls::pki_types::{pem::PemObject, CertificateDer};
    let mut roots = rustls::RootCertStore::empty();
    roots
        .add(CertificateDer::from_pem_slice(&std::fs::read(certificate).unwrap()).unwrap())
        .unwrap();
    let mut config = rustls::ClientConfig::builder_with_provider(Arc::new(
        rustls::crypto::ring::default_provider(),
    ))
    .with_protocol_versions(&[&rustls::version::TLS13])
    .unwrap()
    .with_root_certificates(roots)
    .with_no_client_auth();
    config.alpn_protocols = vec![b"http/1.1".to_vec()];
    tokio_rustls::TlsConnector::from(Arc::new(config))
}
#[tokio::test]
async fn tls_handshake_and_established_inactivity_expire_and_secure_client_recovers() {
    let root = TempDir::new().unwrap();
    let mut value = config(&root);
    let (certificate, key) = tls_files(&root);
    value["httpIngress"]["transport"] =
        json!({"mode":"tls", "certificateFile":certificate, "privateKeyFile":key});
    let fixture = Fixture::start(root, value, None).await;
    let mut silent = fixture.connect().await;
    let mut incomplete = fixture.connect().await;
    incomplete.write_all(&[22, 3, 3, 0, 99, 1]).await.unwrap();
    wait(|| fixture.node.http_snapshot().unwrap().connections == 2).await;
    fixture.idle().await;
    assert!(silent.read_u8().await.is_err());
    assert!(incomplete.read_u8().await.is_err());
    let client = connector(&certificate);
    let mut idle = client
        .connect("localhost".try_into().unwrap(), fixture.connect().await)
        .await
        .unwrap();
    fixture.idle().await;
    assert!(idle.read_u8().await.is_err());
    let mut socket = client
        .connect("localhost".try_into().unwrap(), fixture.connect().await)
        .await
        .unwrap();
    socket
        .write_all(request("GET", "/", TOKEN, 0, true).as_bytes())
        .await
        .unwrap();
    assert_eq!(response(&mut socket).await.0, 404);
    drop(socket);
    fixture.idle().await;
    fixture.shutdown().await;
}
