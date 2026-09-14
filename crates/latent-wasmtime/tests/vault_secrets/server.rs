//! Finite synthetic TLS replies for adversarial cases outside real Vault's API.
use super::*;
use rcgen::{BasicConstraints, CertificateParams, IsCa, KeyPair};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::TcpListener,
    sync::{oneshot, Notify},
};
use tokio_rustls::TlsAcceptor;

pub struct Reply {
    pub status: u16,
    pub body: String,
    pub gated: bool,
}
impl Reply {
    pub fn value(version: u64, value: &str) -> Self {
        Self { status: 200, gated: false, body: serde_json::json!({
            "lease_id":"", "lease_duration":0, "renewable":false,
            "data":{"data":{"value":value},"metadata":{"version":version,"destroyed":false,"deletion_time":""}}
        }).to_string() }
    }
}
pub struct Server {
    pub config: latent_secrets::vault::VaultConfig,
    pub event: Arc<Notify>,
    pub release: Arc<Notify>,
    stop: Option<oneshot::Sender<()>>,
    task: tokio::task::JoinHandle<()>,
}
impl Server {
    pub async fn new(replies: Vec<Reply>) -> Self {
        assert!(replies.len() <= 16 && replies.iter().all(|r| r.body.len() <= 100_000));
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let port = listener.local_addr().unwrap().port();
        let ca_key = KeyPair::generate().unwrap();
        let mut params = CertificateParams::new(vec![]).unwrap();
        params.is_ca = IsCa::Ca(BasicConstraints::Unconstrained);
        let ca = params.self_signed(&ca_key).unwrap();
        let server_key = KeyPair::generate().unwrap();
        let mut params = CertificateParams::new(vec![]).unwrap();
        params
            .subject_alt_names
            .push(rcgen::SanType::IpAddress("127.0.0.1".parse().unwrap()));
        let issuer = rcgen::Issuer::new(CertificateParams::new(vec![]).unwrap(), &ca_key);
        let cert = params.signed_by(&server_key, &issuer).unwrap();
        let tls = rustls::ServerConfig::builder_with_provider(Arc::new(
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
        let acceptor = TlsAcceptor::from(Arc::new(tls));
        let event = Arc::new(Notify::new());
        let release = Arc::new(Notify::new());
        let (stop, mut stopped) = oneshot::channel();
        let (observed, resume) = (event.clone(), release.clone());
        let task = tokio::spawn(async move {
            let mut children = tokio::task::JoinSet::new();
            let mut stopping = false;
            for reply in replies {
                let stream = tokio::select! { result = listener.accept() => result.unwrap().0, _ = &mut stopped => { stopping = true; break; } };
                let (acceptor, event, release) =
                    (acceptor.clone(), observed.clone(), resume.clone());
                children.spawn(async move {
                    let exchange = async {
                        let mut stream = acceptor.accept(stream).await.unwrap();
                        let mut input = vec![];
                        while !input.ends_with(b"\r\n\r\n") {
                            assert!(input.len() < 16384);
                            let mut byte = [0];
                            stream.read_exact(&mut byte).await.unwrap();
                            input.push(byte[0]);
                        }
                        assert!(input.starts_with(b"GET /v1/secret/data/fixture"));
                        if reply.gated { event.notify_one(); release.notified().await; }
                        let header = format!("HTTP/1.1 {} Test\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n", reply.status, reply.body.len());
                        let _ = stream.write_all(header.as_bytes()).await;
                        let _ = stream.write_all(reply.body.as_bytes()).await;
                    };
                    tokio::time::timeout(Duration::from_secs(3), exchange).await.unwrap();
                });
            }
            // A stop also terminates a deliberately blocked test response.
            while !stopping {
                tokio::select! {
                    _ = &mut stopped => { stopping = true; },
                    result = children.join_next() => match result { Some(result) => result.unwrap(), None => return },
                }
            }
            children.abort_all();
            while let Some(result) = children.join_next().await {
                assert!(result.is_ok() || result.unwrap_err().is_cancelled());
            }
        });
        Self {
            config: setup::config(port, ca.der().to_vec()),
            event,
            release,
            stop: Some(stop),
            task,
        }
    }
    pub async fn close(mut self) {
        if let Some(stop) = self.stop.take() {
            let _ = stop.send(());
        }
        tokio::time::timeout(Duration::from_secs(1), &mut self.task)
            .await
            .unwrap()
            .unwrap();
    }
}
impl Drop for Server {
    fn drop(&mut self) {
        self.task.abort();
    }
}
