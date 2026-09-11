use latent_artifacts::package::{
    decode_manifest, decode_referrer, PackageLimits, OCI_MANIFEST_MEDIA_TYPE,
};
use latent_oci::{
    HttpOciRegistry, OciReference, RegistryConfig, RegistryCredentials, RegistryLimits,
};
use std::{
    collections::BTreeMap,
    fmt::Write,
    net::SocketAddr,
    path::PathBuf,
    sync::{Arc, Mutex},
    time::Duration,
};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::TcpListener,
    task::JoinHandle,
};

pub struct Reply {
    pub status: u16,
    pub content_type: &'static str,
    pub body: Vec<u8>,
    pub headers: Vec<(String, String)>,
    pub delay: Duration,
}

impl Reply {
    pub fn ok(content_type: &'static str, body: Vec<u8>) -> Self {
        Self {
            status: 200,
            content_type,
            body,
            headers: Vec::new(),
            delay: Duration::ZERO,
        }
    }
    pub fn header(mut self, key: &str, value: &str) -> Self {
        self.headers.push((key.to_owned(), value.to_owned()));
        self
    }
}

pub struct Server {
    address: SocketAddr,
    requests: Arc<Mutex<Vec<String>>>,
    task: JoinHandle<()>,
}

impl Server {
    pub async fn start(mut route: impl FnMut(&str) -> Reply + Send + 'static) -> Self {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let requests = Arc::new(Mutex::new(Vec::new()));
        let log = requests.clone();
        let task = tokio::spawn(async move {
            for _ in 0..64 {
                let (mut socket, _) = listener.accept().await.unwrap();
                let mut request = Vec::new();
                while !request.ends_with(b"\r\n\r\n") {
                    let byte = socket.read_u8().await.unwrap();
                    request.push(byte);
                    assert!(request.len() <= 8192, "bounded test request");
                }
                let request = std::str::from_utf8(&request).unwrap();
                let path = request
                    .lines()
                    .next()
                    .unwrap()
                    .split_whitespace()
                    .nth(1)
                    .unwrap();
                log.lock().unwrap().push(path.to_owned());
                let reply = route(path);
                tokio::time::sleep(reply.delay).await;
                let mut headers = format!("HTTP/1.1 {} Response\r\nConnection: close\r\nContent-Length: {}\r\nContent-Type: {}\r\n", reply.status, reply.body.len(), reply.content_type);
                for (name, value) in reply.headers {
                    write!(headers, "{name}: {value}\r\n").unwrap();
                }
                headers.push_str("\r\n");
                if socket.write_all(headers.as_bytes()).await.is_ok() {
                    let _ = socket.write_all(&reply.body).await;
                }
            }
        });
        Self {
            address,
            requests,
            task,
        }
    }

    pub fn registry(&self, limits: RegistryLimits) -> HttpOciRegistry {
        HttpOciRegistry::new(RegistryConfig {
            origin: format!("http://{}", self.address),
            repository: "tenant/site".into(),
            credentials: RegistryCredentials::Anonymous,
            addresses: Vec::new(),
            additional_root_certificates: Vec::new(),
            allow_insecure_loopback: true,
            limits,
        })
        .unwrap()
    }

    pub fn reference(&self, reference: &str) -> OciReference {
        OciReference {
            registry: self.address.to_string(),
            repository: "tenant/site".into(),
            reference: reference.to_owned(),
        }
    }

    pub fn requests(&self) -> Vec<String> {
        self.requests.lock().unwrap().clone()
    }

    pub async fn wait_requests(&self, count: usize) {
        tokio::time::timeout(Duration::from_secs(2), async {
            while self.requests.lock().unwrap().len() < count {
                tokio::time::sleep(Duration::from_millis(1)).await;
            }
        })
        .await
        .unwrap();
    }
}

impl Drop for Server {
    fn drop(&mut self) {
        self.task.abort();
    }
}

pub struct Fixture {
    pub manifest: Vec<u8>,
    pub blobs: BTreeMap<String, Vec<u8>>,
}

impl Fixture {
    pub fn load(evidence: bool) -> Self {
        let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../examples/package-format");
        let index: serde_json::Value =
            serde_json::from_slice(&std::fs::read(root.join("golden.json")).unwrap()).unwrap();
        let record = if evidence {
            &index["evidence"][0]
        } else {
            &index["packages"][1]
        };
        let manifest =
            std::fs::read(root.join(record["manifest"]["file"].as_str().unwrap())).unwrap();
        let mut blobs = BTreeMap::new();
        let config = if evidence {
            &index["emptyConfig"]
        } else {
            &record["config"]
        };
        blobs.insert(
            format!(
                "/v2/tenant/site/blobs/{}",
                config["digest"].as_str().unwrap()
            ),
            std::fs::read(root.join(config["file"].as_str().unwrap())).unwrap(),
        );
        let records: Vec<_> = if evidence {
            vec![&record["payload"]]
        } else {
            record["blobs"].as_array().unwrap().iter().collect()
        };
        for blob in records {
            blobs.insert(
                format!("/v2/tenant/site/blobs/{}", blob["digest"].as_str().unwrap()),
                std::fs::read(root.join(blob["file"].as_str().unwrap())).unwrap(),
            );
        }
        Self { manifest, blobs }
    }

    pub fn total(&self) -> usize {
        self.manifest.len() + self.blobs.values().map(Vec::len).sum::<usize>()
    }

    pub fn config_path(&self) -> String {
        let digest = match decode_manifest(&self.manifest, PackageLimits::default()) {
            Ok(value) => value.config.digest,
            Err(_) => {
                decode_referrer(&self.manifest, PackageLimits::default())
                    .unwrap()
                    .config
                    .digest
            }
        };
        format!("/v2/tenant/site/blobs/{digest}")
    }

    pub fn reply(&self, path: &str) -> Reply {
        if path.starts_with("/v2/tenant/site/manifests/") {
            return Reply::ok(OCI_MANIFEST_MEDIA_TYPE, self.manifest.clone());
        }
        if let Some(bytes) = self.blobs.get(path) {
            return Reply::ok("application/octet-stream", bytes.clone());
        }
        let mut reply = Reply::ok("application/json", b"{}".to_vec());
        reply.status = 404;
        reply
    }
}
