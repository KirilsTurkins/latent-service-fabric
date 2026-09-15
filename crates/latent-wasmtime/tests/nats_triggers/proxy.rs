//! Owned finite TLS proxy; faults occur around an actual broker acknowledgement.
use latent_nats::triggers::TriggerConfig;
use rcgen::{BasicConstraints, CertificateParams, IsCa, KeyPair};
use std::io;
use std::sync::atomic::AtomicUsize;
use std::{
    sync::{atomic::Ordering, Arc},
    time::Duration,
};
use tokio::{
    io::{AsyncRead, AsyncReadExt, AsyncWrite, AsyncWriteExt, BufReader},
    net::{TcpListener, TcpStream},
    sync::{oneshot, Notify},
};
use tokio_rustls::{TlsAcceptor, TlsConnector};
pub const HEALTHY: usize = 0;
pub const DROP_ACK: usize = 1;
pub const DROP_BEFORE_ACK: usize = 2;
pub const HOLD_DELIVERY: usize = 4;
pub const REFUSE: usize = 3;
pub struct Proxy {
    pub config: TriggerConfig,
    pub mode: Arc<AtomicUsize>,
    pub seen: Arc<Notify>,
    pub active: Arc<AtomicUsize>,
    stop: Option<oneshot::Sender<()>>,
    task: tokio::task::JoinHandle<()>,
}
pub fn identity() -> (TlsAcceptor, Vec<u8>) {
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
    (TlsAcceptor::from(Arc::new(tls)), ca.der().to_vec())
}
struct Active(Arc<AtomicUsize>);
impl Drop for Active {
    fn drop(&mut self) {
        self.0.fetch_sub(1, Ordering::AcqRel);
    }
}
impl Proxy {
    pub async fn new(mut config: TriggerConfig) -> Self {
        let upstream = config.endpoint.peer;
        let mut roots = rustls::RootCertStore::empty();
        for root in &config.extra_roots {
            roots
                .add(rustls::pki_types::CertificateDer::from(root.clone()))
                .unwrap();
        }
        let tls = rustls::ClientConfig::builder_with_provider(Arc::new(
            rustls::crypto::ring::default_provider(),
        ))
        .with_safe_default_protocol_versions()
        .unwrap()
        .with_root_certificates(roots)
        .with_no_client_auth();
        let connector = TlsConnector::from(Arc::new(tls));
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let (acceptor, ca) = identity();
        config.extra_roots = vec![ca];
        config.endpoint.peer = listener.local_addr().unwrap();
        let mode = Arc::new(AtomicUsize::new(HEALTHY));
        let seen = Arc::new(Notify::new());
        let active = Arc::new(AtomicUsize::new(0));
        let (fault, event, running) = (mode.clone(), seen.clone(), active.clone());
        let (stop, mut stopped) = oneshot::channel();
        let task = tokio::spawn(async move {
            let mut children = tokio::task::JoinSet::new();
            let mut accepted = 0;
            loop {
                tokio::select! {
                    _=&mut stopped=>break,
                    result=children.join_next(),if !children.is_empty()=>{let _=result.unwrap().unwrap();},
                    result=listener.accept(),if accepted<16=>{
                        let (socket,_)=result.unwrap();accepted+=1;
                        if fault.load(Ordering::Acquire)==REFUSE {drop(socket);continue;}
                        let (acceptor,connector,fault,event,running)=(acceptor.clone(),connector.clone(),fault.clone(),event.clone(),running.clone());
                        running.fetch_add(1,Ordering::AcqRel);
                        children.spawn(async move {
                            let _active=Active(running);
                            let exchange=async {
                                let downstream=acceptor.accept(socket).await?;
                                let upstream=connector.connect(rustls::pki_types::ServerName::try_from("127.0.0.1").unwrap(),TcpStream::connect(upstream).await?).await?;
                                let (down_read,mut down_write)=tokio::io::split(downstream);
                                let (up_read,mut up_write)=tokio::io::split(upstream);
                                let mut down_read=BufReader::with_capacity(8192,down_read);
                                let mut up_read=BufReader::with_capacity(8192,up_read);
                                tokio::select! {
                                    result=forward(&mut down_read,&mut up_write,Some((&fault,&event)))=>result,
                                    result=forward(&mut up_read,&mut down_write,Some((&fault,&event)))=>result,
                                }
                            };
                            let _=tokio::time::timeout(Duration::from_secs(5),exchange).await;
                        });
                    }
                }
            }
            children.abort_all();
            while let Some(result) = children.join_next().await {
                assert!(result.is_ok() || result.unwrap_err().is_cancelled());
            }
        });
        Self {
            config,
            mode,
            seen,
            active,
            stop: Some(stop),
            task,
        }
    }
    pub async fn close(mut self) {
        let _ = self.stop.take().unwrap().send(());
        tokio::time::timeout(Duration::from_secs(1), &mut self.task)
            .await
            .unwrap()
            .unwrap();
        assert_eq!(self.active.load(Ordering::Acquire), 0);
    }
}
impl Drop for Proxy {
    fn drop(&mut self) {
        if let Some(stop) = self.stop.take() {
            let _ = stop.send(());
        }
        self.task.abort();
    }
}
fn invalid() -> io::Error {
    io::Error::new(io::ErrorKind::InvalidData, "bounded fixture protocol")
}
pub async fn line<R: AsyncRead + Unpin>(reader: &mut R) -> io::Result<Vec<u8>> {
    let mut out = Vec::with_capacity(8192);
    for _ in 0..8192 {
        let b = reader.read_u8().await?;
        out.push(b);
        if b == b'\n' {
            if out.ends_with(b"\r\n") {
                return Ok(out);
            }
            return Err(invalid());
        }
    }
    Err(invalid())
}
async fn forward<R: AsyncRead + Unpin, W: AsyncWrite + Unpin>(
    reader: &mut R,
    writer: &mut W,
    fault: Option<(&AtomicUsize, &Notify)>,
) -> io::Result<()> {
    for _ in 0..128 {
        let header = line(reader).await?;
        let message = header.starts_with(b"MSG ") || header.starts_with(b"HMSG ");
        let payload = message || header.starts_with(b"HPUB ") || header.starts_with(b"PUB ");
        let body = if payload {
            let number = std::str::from_utf8(&header[..header.len() - 2])
                .map_err(|_| invalid())?
                .rsplit(' ')
                .next()
                .ok_or_else(invalid)?;
            let count: usize = number.parse().map_err(|_| invalid())?;
            if count > 65536 {
                return Err(invalid());
            }
            let mut body = vec![0; count + 2];
            reader.read_exact(&mut body).await?;
            body
        } else {
            Vec::new()
        };
        if let Some((mode, seen)) = fault {
            let selected = mode.load(Ordering::Acquire);
            let empty_ack = message && body == b"\r\n";
            let outgoing_ack = header.starts_with(b"PUB $JS.ACK.");
            let delivery =
                header.starts_with(b"MSG lsf.trigger.") || header.starts_with(b"HMSG lsf.trigger.");
            if (selected == DROP_ACK && empty_ack) || (selected == DROP_BEFORE_ACK && outgoing_ack)
            {
                seen.notify_one();
                return Err(io::Error::new(
                    io::ErrorKind::ConnectionAborted,
                    "fixture drops acknowledgement",
                ));
            }
            if selected == HOLD_DELIVERY && delivery {
                seen.notify_one();
                std::future::pending::<()>().await;
            }
        }
        writer.write_all(&header).await?;
        writer.write_all(&body).await?;
        writer.flush().await?;
    }
    Err(invalid())
}
