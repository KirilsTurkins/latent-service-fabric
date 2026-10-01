//! Controlled TLS failure proxy v1: a single fixed backend, at most one lost
//! PUT response and no retry/routing authority. Test-only, never node startup.
use super::*;
use tokio::net::{TcpListener, TcpStream};
use tokio_rustls::TlsConnector;

#[derive(Clone, Copy)]
pub(super) enum Loss {
    AfterApply,
    BeforeForward,
}

pub(super) struct Proxy {
    pub port: u16,
    pub root_certificate: Vec<u8>,
    pub dropped: Arc<AtomicU64>,
    stop: tokio::sync::oneshot::Sender<()>,
    task: tokio::task::JoinHandle<()>,
}

impl Proxy {
    pub async fn new(endpoint: &Endpoint, loss: Loss) -> Self {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let port = listener.local_addr().unwrap().port();
        let (root_certificate, acceptor) = certificate();
        let mut roots = rustls::RootCertStore::empty();
        roots
            .add(rustls::pki_types::CertificateDer::from(
                endpoint.root_certificate.clone(),
            ))
            .unwrap();
        let tls = rustls::ClientConfig::builder_with_provider(Arc::new(
            rustls::crypto::ring::default_provider(),
        ))
        .with_safe_default_protocol_versions()
        .unwrap()
        .with_root_certificates(roots)
        .with_no_client_auth();
        let connector = TlsConnector::from(Arc::new(tls));
        let backend = endpoint.port;
        let dropped = Arc::new(AtomicU64::new(0));
        let count = dropped.clone();
        let (stop, mut stopped) = tokio::sync::oneshot::channel();
        let task = tokio::spawn(async move {
            loop {
                let socket = tokio::select! {
                    socket = listener.accept() => socket.unwrap().0,
                    _ = &mut stopped => break,
                };
                let Ok(mut socket) = watched(acceptor.accept(socket)).await else {
                    continue;
                };
                let Some(request) = endpoint::read_wire(&mut socket).await else {
                    continue;
                };
                let lose = request.method == "PUT" && count.load(Ordering::SeqCst) == 0;
                if lose && matches!(loss, Loss::BeforeForward) {
                    count.fetch_add(1, Ordering::SeqCst);
                    continue;
                }
                let upstream = TcpStream::connect(("127.0.0.1", backend)).await.unwrap();
                let name = rustls::pki_types::ServerName::try_from("localhost").unwrap();
                let mut upstream = watched(connector.connect(name, upstream)).await.unwrap();
                let mut wire =
                    format!("{} {} HTTP/1.1\r\n", request.method, request.path).into_bytes();
                for (name, value) in request.headers {
                    wire.extend_from_slice(format!("{name}: {value}\r\n").as_bytes());
                }
                wire.extend_from_slice(b"\r\n");
                wire.extend_from_slice(&request.body);
                watched(upstream.write_all(&wire)).await.unwrap();
                let mut reply = Vec::with_capacity(2048);
                let mut chunk = [0; 1024];
                loop {
                    let Ok(length) = watched(upstream.read(&mut chunk)).await else {
                        break;
                    };
                    if length == 0 {
                        break;
                    }
                    assert!(reply.len() + length <= 32_768, "fixed proxy reply bound");
                    reply.extend_from_slice(&chunk[..length]);
                }
                if lose {
                    count.fetch_add(1, Ordering::SeqCst);
                    // The remote transaction has flushed before these bytes
                    // are discarded. Only a later GET can recover its receipt.
                    continue;
                }
                let _ = socket.write_all(&reply).await;
                let _ = socket.shutdown().await;
            }
        });
        Self {
            port,
            root_certificate,
            dropped,
            stop,
            task,
        }
    }

    pub async fn finish(self) {
        assert_eq!(self.dropped.load(Ordering::SeqCst), 1);
        let _ = self.stop.send(());
        watched(self.task).await.unwrap();
    }
}
