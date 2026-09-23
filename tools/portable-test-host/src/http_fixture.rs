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
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::{TcpListener, TcpStream},
    task::JoinHandle,
};

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
    if raw.len() > 32768 {
        return Err("http-fixture-body-bound");
    }
    Ok(raw)
}

pub struct Peer {
    task: Option<JoinHandle<Result<(), &'static str>>>,
    stop: Option<tokio::sync::oneshot::Sender<()>>,
    completed: Arc<AtomicUsize>,
}
impl Peer {
    pub fn start(fixture: &Fixture) -> Result<Self, &'static str> {
        fixture.validate()?;
        let socket = std::net::TcpListener::bind((std::net::Ipv4Addr::LOCALHOST, fixture.port))
            .map_err(|_| "http-fixture-port-unavailable")?;
        socket
            .set_nonblocking(true)
            .map_err(|_| "http-fixture-listener")?;
        let listener = TcpListener::from_std(socket).map_err(|_| "http-fixture-listener")?;
        let selected = fixture.clone();
        let (send, mut stop) = tokio::sync::oneshot::channel();
        let completed = Arc::new(AtomicUsize::new(0));
        let count = completed.clone();
        let task = tokio::spawn(async move {
            loop {
                tokio::select! {
                    _ = &mut stop => return Ok(()),
                    accepted = listener.accept() => {
                        let (stream, address) = accepted.map_err(|_| "http-fixture-accept")?;
                        if !address.ip().is_loopback() || count.load(Ordering::Acquire) >= 128 {
                            return Err("http-fixture-request-bound");
                        }
                        tokio::select! {
                            _ = &mut stop => return Ok(()),
                            result = tokio::time::timeout(Duration::from_secs(2), exchange(stream, &selected)) => {
                                result.map_err(|_| "http-fixture-peer-deadline")??;
                                count.fetch_add(1, Ordering::AcqRel);
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
        })
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

async fn exchange(mut stream: TcpStream, fixture: &Fixture) -> Result<(), &'static str> {
    let mut data = Vec::with_capacity(4096);
    let header_end = loop {
        if let Some(index) = data.windows(4).position(|part| part == b"\r\n\r\n") {
            break index + 4;
        }
        if data.len() >= 8192 {
            return Err("http-fixture-header-bound");
        }
        let mut chunk = [0; 1024];
        let n = stream
            .read(&mut chunk)
            .await
            .map_err(|_| "http-fixture-read")?;
        if n == 0 {
            return Err("http-fixture-truncated");
        }
        data.extend_from_slice(&chunk[..n]);
    };
    let head = std::str::from_utf8(&data[..header_end]).map_err(|_| "http-fixture-header")?;
    let mut lines = head.split("\r\n");
    let line = lines.next().ok_or("http-fixture-request")?;
    let pieces = line.split(' ').collect::<Vec<_>>();
    if pieces.len() != 3 || pieces[2] != "HTTP/1.1" {
        return Err("http-fixture-request");
    }
    let selected = fixture
        .exchanges
        .iter()
        .find(|entry| entry.method == pieces[0] && entry.path == pieces[1])
        .ok_or("http-fixture-unmatched-request")?;
    let mut length = None;
    let mut host = None;
    for line in lines.filter(|line| !line.is_empty()) {
        let (key, value) = line.split_once(':').ok_or("http-fixture-header")?;
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
    stream.shutdown().await.map_err(|_| "http-fixture-close")
}
