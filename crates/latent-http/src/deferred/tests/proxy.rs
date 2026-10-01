//! Owned TLS failure proxy. Faults happen after the actual backend response.
use super::endpoint::{self, read_request, WireRequest};
use super::fixture::WATCHDOG;
use crate::{HttpAddressPolicy, HttpDestination, HttpLimits, HttpProviderConfig, HttpResolution};
use latent_policy::capability::HttpOrigin;
use sha2::{Digest, Sha256};
use std::sync::{
    atomic::{AtomicU64, Ordering},
    Arc, Mutex,
};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::{TcpListener, TcpStream},
    sync::{oneshot, Notify},
};

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Fault {
    Normal,
    LosePostReply,
    LosePostReplyHoldLookupTls,
    HoldPostReply,
    HoldSecondTls,
    MalformedPost,
    OversizedPost,
    StatusPost(u16),
    RedirectPost,
}

pub struct Proxy {
    pub port: u16,
    pub posts: Arc<AtomicU64>,
    pub lookups: Arc<AtomicU64>,
    pub requests: Arc<Mutex<Vec<(String, String, String)>>>,
    root: Vec<u8>,
    entered: Arc<Notify>,
    release: Arc<Notify>,
    stop: oneshot::Sender<()>,
    task: tokio::task::JoinHandle<()>,
}

struct Shared {
    backend: u16,
    fault: Fault,
    posts: Arc<AtomicU64>,
    lookups: Arc<AtomicU64>,
    requests: Arc<Mutex<Vec<(String, String, String)>>>,
    entered: Arc<Notify>,
    release: Arc<Notify>,
}

impl Proxy {
    pub async fn open(backend: u16, fault: Fault) -> Self {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let port = listener.local_addr().unwrap().port();
        let (root, acceptor) = certificate();
        let posts = Arc::new(AtomicU64::new(0));
        let lookups = Arc::new(AtomicU64::new(0));
        let requests = Arc::new(Mutex::new(Vec::with_capacity(64)));
        let entered = Arc::new(Notify::new());
        let release = Arc::new(Notify::new());
        let services = Shared {
            backend,
            fault,
            posts: posts.clone(),
            lookups: lookups.clone(),
            requests: requests.clone(),
            entered: entered.clone(),
            release: release.clone(),
        };
        let (stop, mut closed) = oneshot::channel();
        let task = tokio::spawn(async move {
            let mut connections = 0;
            loop {
                let (stream, _) = tokio::select! {
                    _ = &mut closed => break,
                    accepted = listener.accept() => accepted.unwrap(),
                };
                connections += 1;
                assert!(connections <= 64, "fixture socket admission is finite");
                let services = &services;
                tokio::time::timeout(WATCHDOG, async {
                    if (services.fault == Fault::HoldSecondTls && connections == 2)
                        || (services.fault == Fault::LosePostReplyHoldLookupTls && connections == 4)
                    {
                        services.entered.notify_one();
                        services.release.notified().await;
                    }
                    let Ok(mut stream) = acceptor.accept(stream).await else {
                        return;
                    };
                    let Some(request) = read_request(&mut stream).await else {
                        return;
                    };
                    let Some(reply) = forward(services, request).await else {
                        return;
                    };
                    // Cancellation during a held reply may have closed the real
                    // socket already. A write failure cannot undo the mutation.
                    let _ = stream.write_all(&reply).await;
                    let _ = stream.shutdown().await;
                })
                .await
                .expect("bounded proxy physical work");
            }
        });
        Self {
            port,
            posts,
            lookups,
            requests,
            root,
            entered,
            release,
            stop,
            task,
        }
    }

    pub fn config(&self) -> HttpProviderConfig {
        HttpProviderConfig {
            format_version: 1,
            public_roots: false,
            extra_roots: vec![self.root.clone()],
            limits: HttpLimits::default(),
            destinations: vec![HttpDestination {
                origin: HttpOrigin {
                    scheme: "https".into(),
                    host: "localhost".into(),
                    port: self.port,
                },
                addresses: HttpAddressPolicy {
                    networks: vec!["127.0.0.0/8".parse().unwrap()],
                    special_addresses: vec!["127.0.0.1".parse().unwrap()],
                },
                resolution: HttpResolution::Static {
                    addresses: vec!["127.0.0.1".parse().unwrap()],
                },
                allowed_request_headers: vec![],
                redirect_destinations: vec![],
            }],
        }
    }

    pub async fn wait_gate(&self) {
        tokio::time::timeout(WATCHDOG, self.entered.notified())
            .await
            .unwrap();
    }
    pub fn release(&self) {
        self.release.notify_one();
    }

    pub async fn operator_post(
        &self,
        tls: Arc<rustls::ClientConfig>,
        key: &str,
        body: &[u8],
    ) -> serde_json::Value {
        tokio::time::timeout(WATCHDOG, async {
            let socket = TcpStream::connect(("127.0.0.1", self.port)).await.unwrap();
            let mut stream = tokio_rustls::TlsConnector::from(tls)
                .connect("localhost".try_into().unwrap(), socket)
                .await
                .unwrap();
            let digest = format!("{:x}", latent_core::digest::HexDigest(Sha256::digest(body)));
            let request = WireRequest {
                method: "POST".into(),
                path: "/effect".into(),
                headers: vec![
                    ("host".into(), format!("localhost:{}", self.port)),
                    ("content-type".into(), "text/plain".into()),
                    ("idempotency-key".into(), key.into()),
                    ("lsf-body-sha256".into(), digest),
                    (
                        "lsf-endpoint-contract".into(),
                        super::super::qualification::ENDPOINT_CONTRACT.into(),
                    ),
                    ("lsf-endpoint-incarnation".into(), "c".repeat(64)),
                    ("lsf-idempotency-retention-millis".into(), "10000".into()),
                    (
                        "authorization".into(),
                        "Bearer synthetic-http-reference".into(),
                    ),
                    ("content-length".into(), body.len().to_string()),
                ],
                body: body.to_vec(),
            };
            stream.write_all(&encode(&request)).await.unwrap();
            let mut reply = Vec::new();
            stream.read_to_end(&mut reply).await.unwrap();
            assert!(reply.len() < 16384);
            let split = reply
                .windows(4)
                .position(|bytes| bytes == b"\r\n\r\n")
                .unwrap()
                + 4;
            serde_json::from_slice(&reply[split..]).unwrap()
        })
        .await
        .unwrap()
    }

    pub async fn finish(self) {
        let _ = self.stop.send(());
        tokio::time::timeout(WATCHDOG, self.task)
            .await
            .unwrap()
            .unwrap();
    }
}

async fn forward(services: &Shared, request: WireRequest) -> Option<Vec<u8>> {
    let is_post = request.method == "POST";
    let is_lookup = request.path.starts_with("/receipts/");
    let first_post = is_post && services.posts.fetch_add(1, Ordering::AcqRel) == 0;
    if is_lookup {
        services.lookups.fetch_add(1, Ordering::AcqRel);
    }
    {
        let mut observed = services.requests.lock().unwrap();
        assert!(observed.len() < 64);
        observed.push((
            request.method.clone(),
            request.header("idempotency-key").into(),
            request.header("lsf-body-sha256").into(),
        ));
    }
    let mut backend = TcpStream::connect(("127.0.0.1", services.backend))
        .await
        .unwrap();
    backend.write_all(&encode(&request)).await.unwrap();
    let mut reply = Vec::new();
    backend.read_to_end(&mut reply).await.unwrap();
    assert!(reply.len() < 16384);
    drop(backend);
    if !first_post {
        return Some(reply);
    }
    match services.fault {
        Fault::LosePostReply | Fault::LosePostReplyHoldLookupTls => None,
        Fault::HoldPostReply => {
            services.entered.notify_one();
            services.release.notified().await;
            Some(reply)
        }
        Fault::MalformedPost => Some(endpoint::response(200, &"c".repeat(64), b"{not-json")),
        Fault::OversizedPost => Some(endpoint::response(200, &"c".repeat(64), &[b'x'; 2049])),
        Fault::StatusPost(status) => Some(endpoint::response(status, &"c".repeat(64), b"{}")),
        Fault::RedirectPost => {
            let mut reply = endpoint::response(302, &"c".repeat(64), b"{}");
            let split = reply
                .windows(4)
                .position(|bytes| bytes == b"\r\n\r\n")
                .unwrap();
            reply.splice(
                split..split,
                b"\r\nLocation: https://169.254.169.254/secret"
                    .iter()
                    .copied(),
            );
            Some(reply)
        }
        Fault::Normal | Fault::HoldSecondTls => Some(reply),
    }
}

fn encode(request: &WireRequest) -> Vec<u8> {
    let mut bytes = format!("{} {} HTTP/1.1\r\n", request.method, request.path).into_bytes();
    for (name, value) in &request.headers {
        bytes.extend_from_slice(format!("{name}: {value}\r\n").as_bytes());
    }
    bytes.extend_from_slice(b"\r\n");
    bytes.extend_from_slice(&request.body);
    bytes
}

fn certificate() -> (Vec<u8>, tokio_rustls::TlsAcceptor) {
    let certificate = rcgen::generate_simple_self_signed(vec!["localhost".into()]).unwrap();
    let der = certificate.cert.der().clone();
    let key = rustls::pki_types::PrivatePkcs8KeyDer::from(certificate.signing_key.serialize_der());
    let mut config = rustls::ServerConfig::builder_with_provider(Arc::new(
        rustls::crypto::ring::default_provider(),
    ))
    .with_safe_default_protocol_versions()
    .unwrap()
    .with_no_client_auth()
    .with_single_cert(vec![der.clone()], key.into())
    .unwrap();
    config.alpn_protocols = vec![b"http/1.1".to_vec()];
    (
        der.to_vec(),
        tokio_rustls::TlsAcceptor::from(Arc::new(config)),
    )
}
