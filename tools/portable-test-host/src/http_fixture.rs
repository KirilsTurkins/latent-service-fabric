//! A bounded, owned loopback peer for the unmodified production HTTP provider.
//! Fixture URLs and bytes are explicit; no ambient endpoints or URL rewriting.
use base64::Engine;
use serde::{Deserialize, Serialize};
use std::{
    collections::BTreeSet,
    sync::{
        atomic::{AtomicUsize, Ordering},
        Arc,
    },
    time::Duration,
};
use subtle::ConstantTimeEq;
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::{TcpListener, TcpStream},
    task::JoinHandle,
};
use zeroize::Zeroizing;

#[derive(Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct Fixture {
    pub port: u16,
    pub exchanges: Vec<Exchange>,
}
#[derive(Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct Exchange {
    pub method: String,
    pub path: String,
    pub request_body: String,
    pub status: u16,
    pub response_body: String,
}
impl Fixture {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.port < 1024 || self.exchanges.is_empty() || self.exchanges.len() > 16 {
            return Err("http-fixture-bound");
        }
        if serde_json::to_vec(self)
            .map_err(|_| "http-fixture-encoding")?
            .len()
            >= 192 * 1024
        {
            return Err("http-fixture-byte-bound");
        }
        let mut keys = BTreeSet::new();
        for entry in &self.exchanges {
            if !matches!(
                entry.method.as_str(),
                "GET" | "HEAD" | "POST" | "PUT" | "DELETE"
            ) || !entry.path.starts_with('/')
                || entry.path.len() > 256
                || entry
                    .path
                    .bytes()
                    .any(|b| !b.is_ascii_alphanumeric() && !b"/-_.".contains(&b))
                || !(200..=599).contains(&entry.status)
                || (300..400).contains(&entry.status)
                || !keys.insert((&entry.method, &entry.path))
            {
                return Err("http-fixture-exchange");
            }
            decode(&entry.request_body)?;
            decode(&entry.response_body)?;
        }
        Ok(())
    }
}
fn decode(text: &str) -> Result<Vec<u8>, &'static str> {
    if text.len() > 43692 {
        return Err("http-fixture-body-bound");
    }
    let raw = base64::engine::general_purpose::STANDARD
        .decode(text)
        .map_err(|_| "http-fixture-base64")?;
    if raw.len() > 32768 || base64::engine::general_purpose::STANDARD.encode(&raw) != text {
        return Err("http-fixture-body-bound");
    }
    Ok(raw)
}

pub struct Peer {
    task: Option<JoinHandle<Result<(), &'static str>>>,
    stop: Option<tokio::sync::oneshot::Sender<()>>,
    completed: Arc<AtomicUsize>,
    authorization: Arc<Zeroizing<String>>,
}
impl Peer {
    pub fn start(fixture: &Fixture) -> Result<Self, &'static str> {
        fixture.validate()?;
        let mut entropy = Zeroizing::new([0u8; 32]);
        getrandom::fill(entropy.as_mut()).map_err(|_| "http-fixture-private-entropy")?;
        let mut secret = Zeroizing::new(String::from("Bearer "));
        for byte in entropy.iter() {
            use std::fmt::Write;
            write!(&mut *secret, "{byte:02x}").map_err(|_| "http-fixture-private-credential")?;
        }
        let authorization = Arc::new(secret);
        let expected_authorization = authorization.clone();
        let socket = socket2::Socket::new(
            socket2::Domain::IPV4,
            socket2::Type::STREAM,
            Some(socket2::Protocol::TCP),
        )
        .map_err(|_| "http-fixture-listener")?;
        #[cfg(unix)]
        socket
            .set_reuse_address(true)
            .map_err(|_| "http-fixture-listener")?;
        // Windows keeps its default non-reuse binding. Authentication and the
        // receipt from the owned peer are independently required by comparison.
        let address = std::net::SocketAddr::from((std::net::Ipv4Addr::LOCALHOST, fixture.port));
        socket
            .bind(&address.into())
            .map_err(|_| "http-fixture-port-unavailable")?;
        socket.listen(4).map_err(|_| "http-fixture-listener")?;
        socket
            .set_nonblocking(true)
            .map_err(|_| "http-fixture-listener")?;
        let listener = TcpListener::from_std(socket.into()).map_err(|_| "http-fixture-listener")?;
        let selected = fixture.clone();
        let (send, mut stop) = tokio::sync::oneshot::channel();
        let completed = Arc::new(AtomicUsize::new(0));
        let count = completed.clone();
        let task = tokio::spawn(async move {
            let mut accepted_count = 0;
            let lifetime = tokio::time::sleep(Duration::from_mins(15));
            tokio::pin!(lifetime);
            loop {
                tokio::select! {
                    _ = &mut stop => return Ok(()),
                    () = &mut lifetime => return Err("http-fixture-lifetime-exhausted"),
                    accepted = listener.accept() => {
                        let (stream, address) = accepted.map_err(|_| "http-fixture-accept")?;
                        accepted_count += 1;
                        if !address.ip().is_loopback() || accepted_count > 128 {
                            return Err("http-fixture-request-bound");
                        }
                        tokio::select! {
                            _ = &mut stop => return Ok(()),
                            result = tokio::time::timeout(Duration::from_secs(2), exchange(stream, &selected, &expected_authorization)) => {
                                if result.map_err(|_| "http-fixture-peer-deadline")?? {
                                    count.fetch_add(1, Ordering::AcqRel);
                                }
                            }
                        }
                    }
                }
            }
        });
        Ok(Self {
            task: Some(task),
            stop: Some(send),
            completed,
            authorization,
        })
    }
    pub fn authorization(&self) -> &str {
        &self.authorization
    }
    pub async fn shutdown(&mut self) -> Result<usize, &'static str> {
        if let Some(stop) = self.stop.take() {
            let _ = stop.send(());
        }
        if let Some(mut task) = self.task.take() {
            if let Ok(result) = tokio::time::timeout(Duration::from_secs(3), &mut task).await {
                result.map_err(|_| "http-fixture-worker")??;
            } else {
                task.abort();
                let _ = task.await;
                return Err("http-fixture-cleanup");
            }
        }
        Ok(self.completed.load(Ordering::Acquire))
    }
}
impl Drop for Peer {
    fn drop(&mut self) {
        if let Some(stop) = self.stop.take() {
            let _ = stop.send(());
        }
        if let Some(task) = self.task.take() {
            task.abort();
        }
    }
}

async fn read_head(stream: &mut TcpStream) -> Result<(Zeroizing<Vec<u8>>, usize), &'static str> {
    let mut data = Zeroizing::new(Vec::with_capacity(4096));
    loop {
        if let Some(index) = data.windows(4).position(|part| part == b"\r\n\r\n") {
            if index + 4 > 8192 {
                return Err("http-fixture-header-bound");
            }
            return Ok((data, index + 4));
        }
        if data.len() >= 8192 {
            return Err("http-fixture-header-bound");
        }
        let mut chunk = Zeroizing::new([0; 1024]);
        let n = stream
            .read(chunk.as_mut())
            .await
            .map_err(|_| "http-fixture-read")?;
        if n == 0 {
            return Err("http-fixture-truncated");
        }
        data.extend_from_slice(&chunk[..n]);
    }
}

async fn exchange(
    mut stream: TcpStream,
    fixture: &Fixture,
    authorization: &str,
) -> Result<bool, &'static str> {
    let (mut data, header_end) = read_head(&mut stream).await?;
    let head = std::str::from_utf8(&data[..header_end]).map_err(|_| "http-fixture-header")?;
    let mut lines = head.split("\r\n");
    let line = lines.next().ok_or("http-fixture-request")?;
    let pieces = line.split(' ').collect::<Vec<_>>();
    if pieces.len() != 3 || pieces[2] != "HTTP/1.1" {
        return Err("http-fixture-request");
    }
    let mut received_authorization = None;
    let mut header_names = BTreeSet::new();
    let mut length = None;
    let mut host = None;
    for line in lines.filter(|line| !line.is_empty()) {
        let (key, value) = line.split_once(':').ok_or("http-fixture-header")?;
        if header_names.len() >= 32 || !header_names.insert(key.to_ascii_lowercase()) {
            return Err("http-fixture-header-count-or-duplicate");
        }
        if key.eq_ignore_ascii_case("authorization") {
            received_authorization = Some(value.trim());
        }
        if key.eq_ignore_ascii_case("transfer-encoding") {
            return Err("http-fixture-transfer-encoding");
        }
        if key.eq_ignore_ascii_case("content-length") {
            let value = value.trim();
            if length.is_some() || value.len() > 5 || !value.bytes().all(|b| b.is_ascii_digit()) {
                return Err("http-fixture-content-length");
            }
            length = Some(
                value
                    .parse::<usize>()
                    .map_err(|_| "http-fixture-content-length")?,
            );
        }
        if key.eq_ignore_ascii_case("host") && host.replace(value.trim()).is_some() {
            return Err("http-fixture-host");
        }
    }
    if !bool::from(
        received_authorization
            .unwrap_or("")
            .as_bytes()
            .ct_eq(authorization.as_bytes()),
    ) {
        stream
            .write_all(b"HTTP/1.1 401 Fixture\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            .await
            .map_err(|_| "http-fixture-write")?;
        stream.shutdown().await.map_err(|_| "http-fixture-close")?;
        return Ok(false);
    }
    let selected = fixture
        .exchanges
        .iter()
        .find(|entry| entry.method == pieces[0] && entry.path == pieces[1])
        .ok_or("http-fixture-unmatched-request")?;
    if host != Some(format!("127.0.0.1:{}", fixture.port).as_str()) {
        return Err("http-fixture-host");
    }
    let expected = decode(&selected.request_body)?;
    let length = length.unwrap_or(0);
    if length != expected.len() {
        return Err("http-fixture-body-mismatch");
    }
    while data.len() < header_end + length {
        let mut chunk = [0; 1024];
        let n = stream
            .read(&mut chunk)
            .await
            .map_err(|_| "http-fixture-read")?;
        if n == 0 {
            return Err("http-fixture-truncated");
        }
        data.extend_from_slice(&chunk[..n]);
    }
    if data[header_end..] != expected {
        return Err("http-fixture-body-mismatch");
    }
    let body = decode(&selected.response_body)?;
    let head = format!("HTTP/1.1 {} Fixture\r\nContent-Length: {}\r\nContent-Type: application/octet-stream\r\nConnection: close\r\n\r\n", selected.status, body.len());
    stream
        .write_all(head.as_bytes())
        .await
        .map_err(|_| "http-fixture-write")?;
    if selected.method != "HEAD" {
        stream
            .write_all(&body)
            .await
            .map_err(|_| "http-fixture-write")?;
    }
    stream.shutdown().await.map_err(|_| "http-fixture-close")?;
    Ok(true)
}
