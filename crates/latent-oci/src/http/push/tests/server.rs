use crate::http::{RegistryConfig, RegistryCredentials, RegistryLimits};
use std::{collections::BTreeMap, net::SocketAddr, time::Duration};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::{TcpListener, TcpStream},
    sync::{mpsc, oneshot},
    task::JoinHandle,
    time::timeout,
};

pub(super) struct Server {
    address: SocketAddr,
    requests: mpsc::Receiver<Request>,
    task: JoinHandle<()>,
}

pub(super) struct Request {
    pub(super) method: String,
    pub(super) target: String,
    pub(super) headers: BTreeMap<String, String>,
    pub(super) body: Vec<u8>,
    response: oneshot::Sender<Vec<u8>>,
}

impl Server {
    pub(super) async fn new() -> Self {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let (sender, requests) = mpsc::channel(8);
        let task = tokio::spawn(async move {
            // Every test has a finite script. No per-connection tasks or reports.
            for _ in 0..32 {
                let Ok(Ok((mut socket, _))) =
                    timeout(Duration::from_secs(5), listener.accept()).await
                else {
                    break;
                };
                let (response, receiver) = oneshot::channel();
                let request = read(&mut socket, response).await;
                if sender.send(request).await.is_err() {
                    break;
                }
                if let Ok(Ok(bytes)) = timeout(Duration::from_secs(5), receiver).await {
                    // Cancellation is expected to close some peer sockets.
                    let _ = socket.write_all(&bytes).await;
                }
            }
        });
        Self {
            address,
            requests,
            task,
        }
    }

    pub(super) fn config(&self, max_in_flight: usize) -> RegistryConfig {
        RegistryConfig {
            origin: format!("http://{}", self.address),
            repository: "tenant/site".into(),
            credentials: RegistryCredentials::Anonymous,
            addresses: Vec::new(),
            additional_root_certificates: Vec::new(),
            allow_insecure_loopback: true,
            limits: RegistryLimits {
                max_in_flight,
                request_timeout: Duration::from_secs(3),
                operation_timeout: Duration::from_secs(5),
                cleanup_timeout: Duration::from_secs(2),
                ..RegistryLimits::default()
            },
        }
    }

    pub(super) fn reference(&self) -> crate::OciReference {
        crate::OciReference {
            registry: self.address.to_string(),
            repository: "tenant/site".into(),
            reference: "candidate".into(),
        }
    }

    pub(super) async fn next(&mut self) -> Request {
        timeout(Duration::from_secs(3), self.requests.recv())
            .await
            .expect("bounded scripted registry request")
            .expect("scripted registry still running")
    }
}

impl Drop for Server {
    fn drop(&mut self) {
        self.task.abort();
    }
}

impl Request {
    pub(super) fn respond(self, status: u16, headers: &[(&str, &str)]) {
        let mut response = format!("HTTP/1.1 {status} scripted\r\nConnection: close\r\n");
        for (name, value) in headers {
            response.push_str(name);
            response.push_str(": ");
            response.push_str(value);
            response.push_str("\r\n");
        }
        if !headers
            .iter()
            .any(|(name, _)| name.eq_ignore_ascii_case("content-length"))
        {
            response.push_str("Content-Length: 0\r\n");
        }
        response.push_str("\r\n");
        let _ = self.response.send(response.into_bytes());
    }
}

async fn read(socket: &mut TcpStream, response: oneshot::Sender<Vec<u8>>) -> Request {
    let mut bytes = Vec::new();
    while !bytes.ends_with(b"\r\n\r\n") {
        assert!(bytes.len() < 8192, "test request header bound");
        bytes.push(
            timeout(Duration::from_secs(3), socket.read_u8())
                .await
                .unwrap()
                .unwrap(),
        );
    }
    let text = std::str::from_utf8(&bytes).unwrap();
    let mut lines = text.split("\r\n");
    let mut start = lines.next().unwrap().split(' ');
    let method = start.next().unwrap().to_owned();
    let target = start.next().unwrap().to_owned();
    let mut headers = BTreeMap::new();
    for line in lines.filter(|line| !line.is_empty()) {
        let (key, value) = line.split_once(':').unwrap();
        headers.insert(key.to_ascii_lowercase(), value.trim().to_owned());
    }
    let length = headers
        .get("content-length")
        .map_or(0, |length| length.parse::<usize>().unwrap());
    assert!(length <= 64 * 1024, "tiny test body bound");
    let mut body = vec![0; length];
    timeout(Duration::from_secs(3), socket.read_exact(&mut body))
        .await
        .unwrap()
        .unwrap();
    Request {
        method,
        target,
        headers,
        body,
        response,
    }
}
