//! Real TLS sockets with deterministic S3 fault responses and finite request
//! counts. The pinned MinIO suite separately checks the server's actual API.
use super::*;
use latent_blobs::s3::{S3Recovery, S3RecoveryMode};
use rcgen::{BasicConstraints, CertificateParams, IsCa, KeyPair};
use std::{net::IpAddr, sync::atomic::AtomicUsize};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::TcpListener,
    sync::{oneshot, Notify},
};
use tokio_rustls::TlsAcceptor;

#[derive(Clone, Copy)]
enum Fault {
    LostCreate,
    LatePart,
    CompletionError,
    CorruptRange,
    CleanupUnavailable,
}
struct Server {
    config: latent_blobs::s3::S3Config,
    event: Arc<Notify>,
    release: Arc<Notify>,
    count: Arc<AtomicUsize>,
    stop: oneshot::Sender<()>,
    task: tokio::task::JoinHandle<()>,
}
impl Server {
    async fn new(fault: Fault) -> Self {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let port = listener.local_addr().unwrap().port();
        let ca_key = KeyPair::generate().unwrap();
        let mut params = CertificateParams::new(vec![]).unwrap();
        params.is_ca = IsCa::Ca(BasicConstraints::Unconstrained);
        let ca = params.self_signed(&ca_key).unwrap();
        let server_key = KeyPair::generate().unwrap();
        let mut params = CertificateParams::new(vec![]).unwrap();
        params.subject_alt_names.push(rcgen::SanType::IpAddress(
            "127.0.0.1".parse::<IpAddr>().unwrap(),
        ));
        let issuer = rcgen::Issuer::new(CertificateParams::new(vec![]).unwrap(), &ca_key);
        // Use the issuer constructed from the exact CA parameters so its name
        // agrees with the retained trust root.
        let cert = params.signed_by(&server_key, &issuer).unwrap();
        let server = rustls::ServerConfig::builder_with_provider(Arc::new(
            rustls::crypto::ring::default_provider(),
        ))
        .with_safe_default_protocol_versions()
        .unwrap()
        .with_no_client_auth()
        .with_single_cert(
            vec![cert.der().clone()],
            rustls::pki_types::PrivateKeyDer::Pkcs8(server_key.serialize_der().into()),
        )
        .unwrap();
        let acceptor = TlsAcceptor::from(Arc::new(server));
        let event = Arc::new(Notify::new());
        let release = Arc::new(Notify::new());
        let count = Arc::new(AtomicUsize::new(0));
        let (stop, stopped) = oneshot::channel();
        let (signal, resume, observed) = (event.clone(), release.clone(), count.clone());
        let task = tokio::spawn(async move {
            tokio::pin!(stopped);
            for _ in 0..24 {
                let (stream, _) = tokio::select! { value = listener.accept() => value.unwrap(), _ = &mut stopped => return };
                let mut stream = acceptor.accept(stream).await.unwrap();
                let request = read(&mut stream).await;
                observed.fetch_add(1, Ordering::AcqRel);
                let method = request.split_whitespace().next().unwrap();
                let target = request.split_whitespace().nth(1).unwrap();
                let key = target
                    .strip_prefix("/lsf-test-bucket/")
                    .unwrap_or("")
                    .split('?')
                    .next()
                    .unwrap();
                let (status, headers, body) = if target.contains("uploads=") && method == "POST" {
                    if matches!(fault, Fault::LostCreate) {
                        signal.notify_one();
                        continue;
                    }
                    (200, "", format!("<InitiateMultipartUploadResult><Bucket>lsf-test-bucket</Bucket><Key>{key}</Key><UploadId>upload-1</UploadId></InitiateMultipartUploadResult>"))
                } else if method == "PUT" {
                    if matches!(fault, Fault::LatePart | Fault::CleanupUnavailable) {
                        signal.notify_one();
                        tokio::time::timeout(Duration::from_secs(5), resume.notified())
                            .await
                            .unwrap();
                    }
                    (
                        200,
                        "ETag: \"00000000000000000000000000000000\"\r\n",
                        String::new(),
                    )
                } else if method == "POST" {
                    if matches!(fault, Fault::CompletionError) {
                        (200, "", "<Error><Code>InternalError</Code></Error>".into())
                    } else {
                        (200, "X-Amz-Version-Id: version-1\r\n", format!("<CompleteMultipartUploadResult><Bucket>lsf-test-bucket</Bucket><Key>{key}</Key><ETag>not-a-digest</ETag></CompleteMultipartUploadResult>"))
                    }
                } else if method == "DELETE" {
                    if matches!(fault, Fault::CleanupUnavailable) {
                        (503, "", "<Error><Code>Unavailable</Code></Error>".into())
                    } else {
                        (204, "", String::new())
                    }
                } else if target.contains("versionId=") {
                    (
                        206,
                        "X-Amz-Version-Id: version-1\r\nContent-Range: bytes 0-3/4\r\n",
                        "evil".into(),
                    )
                } else if target.contains("uploads=") {
                    (200, "", "<ListMultipartUploadsResult><Bucket>lsf-test-bucket</Bucket><IsTruncated>false</IsTruncated></ListMultipartUploadsResult>".into())
                } else {
                    (404, "", "<Error><Code>NoSuchUpload</Code></Error>".into())
                };
                let wire = format!("HTTP/1.1 {status} Test\r\nContent-Length: {}\r\nConnection: close\r\n{headers}\r\n{body}", body.len());
                // A late response can fail because the LSF side really closed.
                let _ = stream.write_all(wire.as_bytes()).await;
            }
            panic!("test exceeded its finite server request bound");
        });
        Self {
            config: setup::config(port, ca.der().to_vec()),
            event,
            release,
            count,
            stop,
            task,
        }
    }
    async fn close(self) {
        let _ = self.stop.send(());
        self.task.await.unwrap();
    }
}
async fn read(stream: &mut (impl tokio::io::AsyncRead + Unpin)) -> String {
    let mut headers = Vec::new();
    while !headers.ends_with(b"\r\n\r\n") {
        assert!(headers.len() < 16384);
        let mut byte = [0];
        stream.read_exact(&mut byte).await.unwrap();
        headers.push(byte[0]);
    }
    let request = String::from_utf8(headers).unwrap();
    assert!(request
        .to_lowercase()
        .contains("authorization: aws4-hmac-sha256 "));
    let length = request
        .lines()
        .find_map(|l| l.strip_prefix("content-length: "))
        .unwrap()
        .parse::<usize>()
        .unwrap();
    assert!(length < 32768);
    let mut body = vec![0; length];
    stream.read_exact(&mut body).await.unwrap();
    request
}
async fn fixture(server: &Server, root: &std::path::Path) -> Fixture<S3BlobProvider> {
    setup::fixture_at(
        server.config.clone(),
        "LSFPUBLICS3TEST\nsynthetic-secret".into(),
        root.join("inventory"),
    )
    .await
}
async fn writer(
    f: &Fixture<S3BlobProvider>,
    session: &CapabilitySession,
) -> Box<dyn blob::BlobWriter> {
    let mut writer = f
        .provider
        .create(session, "text/plain".into(), Some(4))
        .unwrap()
        .await
        .unwrap();
    writer.write(0, b"data".to_vec()).unwrap().await.unwrap();
    writer
}
#[tokio::test]
async fn lost_create_and_embedded_completion_error_remain_uncertain() {
    for fault in [Fault::LostCreate, Fault::CompletionError] {
        let server = Server::new(fault).await;
        let root = tempfile::TempDir::new().unwrap();
        let f = fixture(&server, root.path()).await;
        let (session, _) = f.session("unknown-seal");
        assert!(matches!(
            writer(&f, &session).await.seal().unwrap().await,
            Err(BlobError::Uncertain)
        ));
        let pending = f.provider.inventory().pending().unwrap();
        assert_eq!(pending.len(), 1);
        assert!(!pending[0].active);
        let before = server.count.load(Ordering::Acquire);
        assert!(matches!(
            writer(&f, &session).await.seal().unwrap().await,
            Err(BlobError::Uncertain)
        ));
        assert_eq!(server.count.load(Ordering::Acquire), before);
        assert_eq!(
            f.provider
                .reconcile(
                    &pending[0].id,
                    Instant::now() + Duration::from_secs(2),
                    2,
                    S3RecoveryMode::Observe
                )
                .await
                .unwrap(),
            S3Recovery::Unresolved
        );
        drop(session);
        assert!(f
            .pools
            .shutdown(Instant::now() + Duration::from_secs(2))
            .await
            .unwrap()
            .is_clean());
        assert_eq!(
            f.provider
                .inventory()
                .snapshot()
                .unwrap()
                .remote_reserved_bytes,
            4
        );
        drop(f);
        server.close().await;
    }
}
#[tokio::test]
async fn unverified_range_bytes_never_become_a_guest_chunk() {
    let server = Server::new(Fault::CorruptRange).await;
    let root = tempfile::TempDir::new().unwrap();
    let f = fixture(&server, root.path()).await;
    let (session, _) = f.session("bad-checksum");
    let sealed = writer(&f, &session).await.seal().unwrap().await.unwrap();
    let reference = sealed.reference;
    drop(sealed.owner);
    let mut reader = f.provider.open(&session, reference).unwrap().await.unwrap();
    let error = reader.read(0, 4).unwrap().await.err();
    assert_eq!(error, Some(BlobError::ChecksumMismatch));
    assert_eq!(f.io.snapshot().result_bytes, 0);
    drop((reader, session));
    assert!(f
        .pools
        .shutdown(Instant::now() + Duration::from_secs(2))
        .await
        .unwrap()
        .is_clean());
    f.idle();
    drop(f);
    server.close().await;
}
#[tokio::test]
async fn late_part_restart_and_unavailable_cleanup_keep_the_inventory_charged() {
    for fault in [Fault::LatePart, Fault::CleanupUnavailable] {
        let server = Server::new(fault).await;
        let root = tempfile::TempDir::new().unwrap();
        let f = fixture(&server, root.path()).await;
        let (session, control) = f.session("cancel-inflight-part");
        let sealing = writer(&f, &session).await.seal().unwrap();
        tokio::pin!(sealing);
        tokio::select! { value = &mut sealing => panic!("part did not wait: {:?}", value.err()), _ = server.event.notified() => () }
        assert_eq!(f.provider.inventory().snapshot().unwrap().active_uploads, 1);
        control.probe.0.store(true, Ordering::Release);
        assert!(matches!(sealing.await, Err(BlobError::Uncertain)));
        assert_eq!(f.pools.snapshot().unwrap().connections, 0);
        let pending = f.provider.inventory().pending().unwrap();
        assert_eq!(pending.len(), 1);
        assert_eq!(
            f.provider
                .inventory()
                .snapshot()
                .unwrap()
                .remote_reserved_bytes,
            4
        );
        server.release.notify_one(); // The actual remote test handler may now finish its late part.
        drop(session);
        assert!(f
            .pools
            .shutdown(Instant::now() + Duration::from_secs(2))
            .await
            .unwrap()
            .is_clean());
        drop(f);
        let f = fixture(&server, root.path()).await;
        assert_eq!(
            f.provider
                .reconcile(
                    &pending[0].id,
                    Instant::now() + Duration::from_secs(2),
                    2,
                    S3RecoveryMode::Observe
                )
                .await
                .unwrap(),
            S3Recovery::Unresolved
        );
        assert_eq!(
            f.provider
                .inventory()
                .snapshot()
                .unwrap()
                .remote_reserved_bytes,
            4
        );
        let result = f
            .provider
            .reconcile(
                &pending[0].id,
                Instant::now() + Duration::from_secs(2),
                1,
                S3RecoveryMode::AfterOperatorConfirmedQuiescence,
            )
            .await
            .unwrap();
        assert_eq!(
            result,
            if matches!(fault, Fault::LatePart) {
                S3Recovery::Retired
            } else {
                S3Recovery::Unresolved
            }
        );
        assert!(f
            .pools
            .shutdown(Instant::now() + Duration::from_secs(2))
            .await
            .unwrap()
            .is_clean());
        drop(f);
        server.close().await;
    }
}

#[tokio::test]
async fn revocation_and_exhausted_request_budget_reject_before_s3_dispatch() {
    let server = Server::new(Fault::LostCreate).await;
    let root = tempfile::TempDir::new().unwrap();
    let f = fixture(&server, root.path()).await;
    let (session, control) = f.session("no-network-budget");
    let ready = writer(&f, &session).await;
    control
        .budget
        .consume(latent_core::BudgetDimension::OutboundRequests, 64)
        .unwrap();
    assert!(matches!(
        ready.seal().unwrap().await,
        Err(BlobError::BudgetExhausted)
    ));
    assert!(f.provider.inventory().pending().unwrap().is_empty());
    drop(session);
    let (session, _) = f.session("revoked-writer");
    let mut ready = f
        .provider
        .create(&session, "text/plain".into(), Some(4))
        .unwrap()
        .await
        .unwrap();
    f.revoke();
    let result = match ready.write(0, b"data".to_vec()) {
        Ok(future) => future.await,
        Err(error) => Err(error),
    };
    assert_eq!(result, Err(BlobError::PermissionDenied));
    drop((ready, session));
    assert_eq!(server.count.load(Ordering::Acquire), 0);
    assert_eq!(f.provider.inventory().snapshot().unwrap().stages, 0);
    assert!(f
        .pools
        .shutdown(Instant::now() + Duration::from_secs(2))
        .await
        .unwrap()
        .is_clean());
    f.idle();
    drop(f);
    server.close().await;
}
