use crate::http::{
    BearerIdentity, RegistryActions, RegistryConfig, RegistryCredentials, RegistryLimits,
};
use latent_core::TenantId;
use rustls::pki_types::PrivatePkcs8KeyDer;
use std::{
    net::SocketAddr,
    sync::{
        atomic::{AtomicBool, AtomicUsize, Ordering},
        Arc, Mutex,
    },
    time::Duration,
};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::TcpListener,
    sync::{oneshot, Semaphore},
    task::{JoinHandle, JoinSet},
    time::timeout,
};
use tokio_rustls::{server::TlsStream, TlsAcceptor};

pub(in crate::http) struct State {
    pub tokens: AtomicUsize,
    pub reads: AtomicUsize,
    pub writes: AtomicUsize,
    pub disconnected: AtomicUsize,
    pub hold: AtomicBool,
    pub release: Semaphore,
    pub token_body: Mutex<Option<Vec<u8>>>,
    pub challenge: Mutex<Option<String>>,
    pub write_status: AtomicUsize,
    pub token_status: AtomicUsize,
    pub redirect: Mutex<Option<String>>,
    pub token_redirect: Mutex<Option<String>>,
    pub storage: AtomicBool,
    pub hold_body: AtomicBool,
    pub hold_headers: AtomicBool,
    pub headers_release: Semaphore,
    pub body_release: Semaphore,
    pub response_headers: Mutex<String>,
    pub response_body: Mutex<Vec<u8>>,
    pub upload_mode: AtomicBool,
    pub write_release: Semaphore,
    pub delete_release: Semaphore,
}

pub(in crate::http) struct Peer {
    pub address: SocketAddr,
    pub state: Arc<State>,
    certificate: Vec<u8>,
    worker: JoinHandle<()>,
    stop: Option<oneshot::Sender<()>>,
}

impl Peer {
    pub async fn new() -> Self {
        Self::with_names(vec!["127.0.0.1".into()]).await
    }

    pub async fn with_names(names: Vec<String>) -> Self {
        let certificate = rcgen::generate_simple_self_signed(names).unwrap();
        let der = certificate.cert.der().clone();
        let tls = rustls::ServerConfig::builder_with_provider(Arc::new(
            rustls::crypto::ring::default_provider(),
        ))
        .with_safe_default_protocol_versions()
        .unwrap()
        .with_no_client_auth()
        .with_single_cert(
            vec![der.clone()],
            PrivatePkcs8KeyDer::from(certificate.signing_key.serialize_der()).into(),
        )
        .unwrap();
        let acceptor = TlsAcceptor::from(Arc::new(tls));
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let state = Arc::new(State {
            tokens: 0.into(),
            reads: 0.into(),
            writes: 0.into(),
            disconnected: 0.into(),
            hold: false.into(),
            release: Semaphore::new(0),
            token_body: Mutex::new(None),
            challenge: Mutex::new(None),
            write_status: 201.into(),
            token_status: 200.into(),
            redirect: Mutex::new(None),
            token_redirect: Mutex::new(None),
            storage: false.into(),
            hold_body: false.into(),
            hold_headers: false.into(),
            headers_release: Semaphore::new(0),
            body_release: Semaphore::new(0),
            response_headers: Mutex::new(String::new()),
            response_body: Mutex::new(b"abc".to_vec()),
            upload_mode: false.into(),
            write_release: Semaphore::new(0),
            delete_release: Semaphore::new(0),
        });
        let shared = Arc::clone(&state);
        let (stop, mut stopped) = oneshot::channel();
        let worker = tokio::spawn(async move {
            let mut connections = JoinSet::new();
            loop {
                tokio::select! {
                    _ = &mut stopped => break,
                    accepted = listener.accept(), if connections.len() < 32 => {
                        let (socket, _) = accepted.unwrap();
                        let acceptor = acceptor.clone();
                        let shared = Arc::clone(&shared);
                        connections.spawn(async move {
                            let result = timeout(Duration::from_secs(5), async {
                                if let Ok(mut socket) = acceptor.accept(socket).await {
                                    serve(&mut socket, &shared, address).await;
                                }
                            }).await;
                            assert!(result.is_ok(), "bounded test peer timed out");
                        });
                    }
                    joined = connections.join_next(), if !connections.is_empty() => {
                        joined.unwrap().unwrap();
                    }
                }
            }
            connections.shutdown().await;
        });
        Self {
            address,
            state,
            certificate: der.to_vec(),
            worker,
            stop: Some(stop),
        }
    }

    pub fn config(&self, actions: RegistryActions) -> RegistryConfig {
        RegistryConfig {
            origin: format!("https://{}", self.address),
            repository: "tenant/package".into(),
            credentials: RegistryCredentials::BearerChallenge {
                realm: format!("https://{}/token", self.address),
                service: "registry.test".into(),
                identity: identity(1),
                actions,
                username: "public-test-user".into(),
                password: "public-test-password".into(),
                addresses: vec![],
            },
            addresses: vec![],
            additional_root_certificates: vec![self.certificate.clone()],
            allow_insecure_loopback: false,
            limits: RegistryLimits {
                max_in_flight: 8,
                max_retained_bytes: 1024 * 1024,
                connect_timeout: Duration::from_secs(1),
                request_timeout: Duration::from_secs(3),
                operation_timeout: Duration::from_secs(4),
                ..RegistryLimits::default()
            },
        }
    }

    pub async fn wait_tokens(&self, count: usize) {
        wait_until(|| self.state.tokens.load(Ordering::Acquire) >= count).await;
    }

    pub async fn close(mut self) {
        self.stop.take().unwrap().send(()).unwrap();
        timeout(Duration::from_secs(3), &mut self.worker)
            .await
            .unwrap()
            .unwrap();
    }
}

impl Drop for Peer {
    fn drop(&mut self) {
        self.worker.abort();
    }
}

pub(in crate::http) fn identity(epoch: u64) -> BearerIdentity {
    BearerIdentity {
        tenant: TenantId("tenant".into()),
        principal: "operator".into(),
        credential_epoch: epoch,
    }
}

pub(in crate::http) async fn wait_until(mut predicate: impl FnMut() -> bool) {
    timeout(Duration::from_secs(3), async {
        while !predicate() {
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();
}

async fn serve(socket: &mut TlsStream<tokio::net::TcpStream>, state: &State, address: SocketAddr) {
    let mut head = Vec::new();
    while !head.ends_with(b"\r\n\r\n") {
        let mut byte = [0];
        if socket.read_exact(&mut byte).await.is_err() {
            return;
        }
        head.push(byte[0]);
        assert!(head.len() <= 32 * 1024);
    }
    let head = String::from_utf8(head).unwrap();
    let lower = head.to_ascii_lowercase();
    let length = lower
        .lines()
        .find_map(|line| line.strip_prefix("content-length: "))
        .map_or(0, |value| value.parse::<usize>().unwrap());
    assert!(length <= 65536);
    let mut body = vec![0; length];
    if socket.read_exact(&mut body).await.is_err() {
        return;
    }
    if head.starts_with("GET /token?") {
        assert!(lower.contains("authorization: basic "));
        assert!(head.contains("service=registry.test"));
        assert!(head.contains("scope=repository%3Atenant%2Fpackage%3Apull"));
        assert!(!head.contains("offline_token"));
        let number = state.tokens.fetch_add(1, Ordering::AcqRel) + 1;
        if state.hold.load(Ordering::Acquire) {
            let mut byte = [0];
            tokio::select! {
                permit = state.release.acquire() => permit.unwrap().forget(),
                _ = socket.read(&mut byte) => {
                    state.disconnected.fetch_add(1, Ordering::AcqRel);
                    return;
                }
            }
        }
        let body = state.token_body.lock().unwrap().clone().unwrap_or_else(|| {
            format!("{{\"token\":\"fixture-token-{number}\",\"expires_in\":60}}").into_bytes()
        });
        let redirect = state.token_redirect.lock().unwrap().clone();
        let headers = redirect.map_or_else(
            || "Content-Type: application/json\r\n".to_owned(),
            |url| format!("Location: {url}\r\n"),
        );
        reply(
            socket,
            state.token_status.load(Ordering::Acquire),
            &headers,
            &body,
        )
        .await;
        return;
    }
    assert!(!lower.contains("authorization: basic "));
    let read = head.starts_with("GET ") || head.starts_with("HEAD ");
    if !read {
        state.writes.fetch_add(1, Ordering::AcqRel);
        assert!(lower.contains("authorization: bearer fixture-token-"));
        if state.upload_mode.load(Ordering::Acquire) {
            let deleting = head.starts_with("DELETE ");
            let release = if deleting {
                &state.delete_release
            } else {
                &state.write_release
            };
            let mut byte = [0];
            tokio::select! {
                permit = release.acquire() => { permit.unwrap().forget(); }
                _ = socket.read(&mut byte) => {
                    state.disconnected.fetch_add(1, Ordering::AcqRel);
                    return;
                }
            }
            let location = "/v2/tenant/package/blobs/uploads/session?_state=a%2fb%2B%3D&empty=";
            if deleting {
                assert!(head.starts_with(&format!("DELETE {location} HTTP/1.1")));
                reply(socket, 204, "", b"").await;
            } else if head.starts_with("POST ") {
                reply(socket, 202, &format!("Location: {location}\r\n"), b"").await;
            } else {
                reply(socket, 201, "", b"").await;
            }
            return;
        }
        let status = state.write_status.load(Ordering::Acquire);
        if status == 0 {
            return;
        }
        reply(socket, status, "", b"").await;
        return;
    }
    serve_read(socket, state, &head, &lower, address).await;
}

async fn serve_read(
    socket: &mut TlsStream<tokio::net::TcpStream>,
    state: &State,
    head: &str,
    lower: &str,
    address: SocketAddr,
) {
    state.reads.fetch_add(1, Ordering::AcqRel);
    if state.storage.load(Ordering::Acquire) {
        assert!(!lower.contains("authorization:"));
        assert!(!lower.contains("cookie:"));
    } else if !lower.contains("authorization: bearer fixture-token-") {
        let challenge = state.challenge.lock().unwrap().clone().unwrap_or_else(|| {
            format!("Bearer realm=\"https://{address}/token\",service=\"registry.test\",scope=\"repository:tenant/package:pull\"")
        });
        reply(
            socket,
            401,
            &format!("WWW-Authenticate: {challenge}\r\n"),
            b"",
        )
        .await;
        return;
    }
    let redirect = state.redirect.lock().unwrap().clone();
    if let Some(redirect) = redirect {
        reply(socket, 307, &format!("Location: {redirect}\r\n"), b"").await;
        return;
    }
    if state.hold_headers.load(Ordering::Acquire) {
        let mut byte = [0];
        tokio::select! {
            permit = state.headers_release.acquire() => permit.unwrap().forget(),
            _ = socket.read(&mut byte) => {
                state.disconnected.fetch_add(1, Ordering::AcqRel);
                return;
            }
        }
    }
    if state.hold_body.load(Ordering::Acquire) {
        let headers = b"HTTP/1.1 200 OK\r\nContent-Type: application/octet-stream\r\nContent-Length: 3\r\nConnection: close\r\n\r\n";
        if socket.write_all(headers).await.is_err() {
            return;
        }
        socket.flush().await.unwrap();
        let mut byte = [0];
        tokio::select! {
            permit = state.body_release.acquire() => { permit.unwrap().forget(); }
            _ = socket.read(&mut byte) => {
                state.disconnected.fetch_add(1, Ordering::AcqRel);
                return;
            }
        }
        let _ = socket.write_all(b"abc").await;
        let _ = socket.shutdown().await;
        return;
    }
    let extra = state.response_headers.lock().unwrap().clone();
    let body = state.response_body.lock().unwrap().clone();
    reply(
        socket,
        200,
        &format!("Content-Type: application/octet-stream\r\n{extra}"),
        if head.starts_with("HEAD ") {
            b""
        } else {
            &body
        },
    )
    .await;
}

async fn reply(
    socket: &mut TlsStream<tokio::net::TcpStream>,
    status: usize,
    headers: &str,
    body: &[u8],
) {
    let head = format!(
        "HTTP/1.1 {status} Reply\r\nConnection: close\r\nContent-Length: {}\r\n{headers}\r\n",
        body.len()
    );
    if socket.write_all(head.as_bytes()).await.is_ok() {
        let _ = socket.write_all(body).await;
        let _ = socket.flush().await;
        let _ = timeout(Duration::from_secs(1), socket.shutdown()).await;
    }
}
