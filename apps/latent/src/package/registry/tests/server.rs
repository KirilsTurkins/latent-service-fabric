use super::*;
use latent_oci::{RegistryConfig, RegistryCredentials, RegistryLimits};
use std::{
    fmt::Write,
    sync::{Arc, Mutex},
};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::TcpListener,
    task::JoinHandle,
};

pub(super) struct Reply {
    status: u16,
    body: Vec<u8>,
    headers: Vec<(String, String)>,
    length: Option<usize>,
    delay: Duration,
}
impl Reply {
    pub fn status(status: u16) -> Self {
        Self {
            status,
            body: Vec::new(),
            headers: Vec::new(),
            length: Some(0),
            delay: Duration::ZERO,
        }
    }
    pub fn head() -> Self {
        Self {
            length: None,
            ..Self::status(200)
        }
    }
    pub fn held() -> Self {
        Self {
            delay: Duration::from_secs(5),
            ..Self::head()
        }
    }
    pub fn created(digest: &str) -> Self {
        Self {
            headers: vec![("Docker-Content-Digest".into(), digest.into())],
            ..Self::status(201)
        }
    }
    fn bytes(media: &str, body: Vec<u8>) -> Self {
        Self {
            status: 200,
            headers: vec![("Content-Type".into(), media.into())],
            length: Some(body.len()),
            body,
            delay: Duration::ZERO,
        }
    }
}
pub(super) struct Server {
    address: std::net::SocketAddr,
    task: Option<JoinHandle<()>>,
    requests: Arc<Mutex<Vec<(String, String)>>>,
}
impl Server {
    pub async fn start(
        mut handler: impl FnMut(&str, &str, &[u8]) -> Reply + Send + 'static,
    ) -> Self {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let requests = Arc::new(Mutex::new(Vec::new()));
        let log = Arc::clone(&requests);
        let task = tokio::spawn(async move {
            for _ in 0..32 {
                let (mut socket, _) = listener.accept().await.unwrap();
                let request = tokio::time::timeout(Duration::from_secs(2), async {
                    let mut bytes = Vec::new();
                    while !bytes.ends_with(b"\r\n\r\n") {
                        bytes.push(socket.read_u8().await.unwrap());
                        assert!(bytes.len() < 8192);
                    }
                    let headers = String::from_utf8(bytes).unwrap();
                    assert!(headers
                        .to_ascii_lowercase()
                        .contains("authorization: bearer fixture-public-token\r\n"));
                    let length = headers
                        .lines()
                        .find_map(|line| {
                            line.to_ascii_lowercase()
                                .strip_prefix("content-length:")
                                .map(|n| n.trim().parse::<usize>().unwrap())
                        })
                        .unwrap_or(0);
                    assert!(length <= 16384);
                    let mut body = vec![0; length];
                    socket.read_exact(&mut body).await.unwrap();
                    (headers, body)
                })
                .await
                .unwrap();
                let mut parts = request.0.lines().next().unwrap().split_whitespace();
                let method = parts.next().unwrap();
                let path = parts.next().unwrap();
                log.lock().unwrap().push((method.into(), path.into()));
                let reply = handler(method, path, &request.1);
                tokio::time::sleep(reply.delay).await;
                let mut headers =
                    format!("HTTP/1.1 {} Fixture\r\nConnection: close\r\n", reply.status);
                if let Some(length) = reply.length {
                    write!(headers, "Content-Length: {length}\r\n").unwrap();
                }
                for (key, value) in reply.headers {
                    write!(headers, "{key}: {value}\r\n").unwrap();
                }
                headers.push_str("\r\n");
                socket.write_all(headers.as_bytes()).await.unwrap();
                if method != "HEAD" {
                    socket.write_all(&reply.body).await.unwrap();
                }
            }
        });
        Self {
            address,
            requests,
            task: Some(task),
        }
    }
    pub fn client(&self) -> (HttpOciRegistry, OciReference) {
        let registry = HttpOciRegistry::new(RegistryConfig {
            origin: format!("http://{}", self.address),
            repository: "repo".into(),
            credentials: RegistryCredentials::Bearer("fixture-public-token".into()),
            addresses: vec![self.address],
            additional_root_certificates: Vec::new(),
            allow_insecure_loopback: true,
            limits: RegistryLimits {
                package: super::super::super::limits().package,
                max_in_flight: 1,
                max_retained_packages: 2,
                operation_timeout: Duration::from_secs(5),
                ..RegistryLimits::default()
            },
        })
        .unwrap();
        (
            registry,
            OciReference {
                registry: self.address.to_string(),
                repository: "repo".into(),
                reference: String::new(),
            },
        )
    }
    pub async fn stop(mut self) -> Vec<(String, String)> {
        let task = self.task.take().unwrap();
        task.abort();
        assert!(task.await.unwrap_err().is_cancelled());
        let requests = self.requests.lock().unwrap().clone();
        requests
    }
}
impl Drop for Server {
    fn drop(&mut self) {
        if let Some(task) = &self.task {
            task.abort();
        }
    }
}

pub(super) fn pull_routes(
    package: &PackageBundle,
    evidence: &AdmissionEvidence,
) -> BTreeMap<String, Reply> {
    let mut routes = BTreeMap::new();
    routes.insert(
        "/v2/repo/manifests/release".into(),
        Reply::bytes(
            format::OCI_MANIFEST_MEDIA_TYPE,
            package.manifest_bytes().to_vec(),
        ),
    );
    routes.insert(
        format!(
            "/v2/repo/blobs/{}",
            format::artifact_blob_digest(package.config_bytes())
        ),
        Reply::bytes("application/octet-stream", package.config_bytes().to_vec()),
    );
    for layer in package.layers() {
        routes.insert(
            format!(
                "/v2/repo/blobs/{}",
                format::artifact_blob_digest(layer.bytes())
            ),
            Reply::bytes("application/octet-stream", layer.bytes().to_vec()),
        );
    }
    let digest = format::package_digest(&evidence.manifest);
    let index = serde_json::json!({"schemaVersion":2,"mediaType":"application/vnd.oci.image.index.v1+json","manifests":[{"mediaType":format::OCI_MANIFEST_MEDIA_TYPE,"artifactType":EvidenceKind::Sbom.artifact_type(),"digest":digest.to_string(),"size":evidence.manifest.len()}]});
    routes.insert(
        format!("/v2/repo/referrers/{}", package.layout().digest()),
        Reply::bytes(
            "application/vnd.oci.image.index.v1+json",
            serde_json::to_vec(&index).unwrap(),
        ),
    );
    routes.insert(
        format!("/v2/repo/manifests/{digest}"),
        Reply::bytes(format::OCI_MANIFEST_MEDIA_TYPE, evidence.manifest.clone()),
    );
    for bytes in [&evidence.configuration, &evidence.payload] {
        routes.insert(
            format!("/v2/repo/blobs/{}", format::artifact_blob_digest(bytes)),
            Reply::bytes("application/octet-stream", bytes.clone()),
        );
    }
    routes
}
