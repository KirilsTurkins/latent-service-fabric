use super::{error, response, Counters, RegistryAddressPolicy, RegistryResolution};
use crate::http::{exhausted, invalid, RegistryConfig, RegistryLimits, Result};
use bytes::Bytes;
use http_body_util::Full;
use latent_core::PlatformErrorCode;
use latent_network::{canonical, dns::Resolver};
use reqwest::{
    header::{HeaderMap, HeaderValue, CONTENT_LENGTH, HOST},
    Method, Response, Url,
};
use std::{
    future::Future,
    net::SocketAddr,
    pin::Pin,
    sync::{atomic::Ordering, Arc},
    task::Poll,
};
use tokio::{
    net::TcpSocket,
    time::{timeout_at, Instant},
};
use tokio_rustls::{client::TlsStream, TlsConnector};

pub(super) type Driver = hyper::client::conn::http1::Connection<
    hyper_util::rt::TokioIo<TlsStream<tokio::net::TcpStream>>,
    Full<Bytes>,
>;

pub(in crate::http) struct OwnedClient {
    pub(super) origin: Url,
    pub(super) policy: RegistryAddressPolicy,
    pub(super) resolution: RegistryResolution,
    pub(super) resolver: Option<Resolver>,
    pub(super) content_prefixes: Vec<String>,
    pub(super) counters: Arc<Counters>,
    pub(super) tls: Arc<rustls::ClientConfig>,
    pub(super) limits: RegistryLimits,
}

impl OwnedClient {
    pub(in crate::http) async fn send(
        &self,
        method: Method,
        url: Url,
        headers: HeaderMap,
        body: Option<Bytes>,
        deadline: Instant,
    ) -> Result<Response> {
        if url.origin() != self.origin.origin()
            || url.scheme() != "https"
            || !url.username().is_empty()
            || url.password().is_some()
            || url.fragment().is_some()
            || url.as_str().len() > 4096
        {
            return Err(invalid("oci-network-request-outside-origin"));
        }
        let deadline = deadline.min(Instant::now() + self.limits.request_timeout);
        if headers.len() > 32
            || headers
                .iter()
                .map(|(name, value)| name.as_str().len() + value.len())
                .sum::<usize>()
                > 16384
        {
            return Err(exhausted("oci-request-header-limit"));
        }
        timeout_at(
            deadline,
            self.exchange(method, url, headers, body, deadline),
        )
        .await
        .map_err(|_| deadline_error())?
    }

    async fn exchange(
        &self,
        method: Method,
        url: Url,
        mut headers: HeaderMap,
        body: Option<Bytes>,
        deadline: Instant,
    ) -> Result<Response> {
        if Instant::now() >= deadline {
            return Err(deadline_error());
        }
        let lease = self.counters.reserve(body.as_ref().map_or(0, Bytes::len))?;
        let stream = self.connect(&url, deadline).await?;
        let port = url
            .port_or_known_default()
            .ok_or_else(|| invalid("invalid-oci-port"))?;
        let host = url
            .host_str()
            .ok_or_else(|| invalid("invalid-oci-origin"))?
            .trim_matches(['[', ']']);
        let mut builder = hyper::client::conn::http1::Builder::new();
        builder
            .max_headers(100)
            .max_buf_size(32768)
            .http09_responses(false)
            .allow_spaces_after_header_name_in_responses(false)
            .allow_obsolete_multiline_headers_in_responses(false)
            .ignore_invalid_headers_in_responses(false);
        let (mut sender, mut driver) = builder
            .handshake(hyper_util::rt::TokioIo::new(stream))
            .await
            .map_err(|_| connection_error())?;
        let host = if host.contains(':') {
            format!("[{host}]:{port}")
        } else {
            format!("{host}:{port}")
        };
        headers.insert(
            HOST,
            HeaderValue::from_str(&host).map_err(|_| invalid("invalid-oci-host"))?,
        );
        let bytes = body.unwrap_or_default();
        headers.insert(CONTENT_LENGTH, HeaderValue::from(bytes.len()));
        let mut request = http::Request::new(Full::new(bytes));
        *request.method_mut() = method;
        let target = url.query().map_or_else(
            || url.path().to_owned(),
            |query| format!("{}?{query}", url.path()),
        );
        *request.uri_mut() = target
            .parse()
            .map_err(|_| invalid("invalid-oci-request-path"))?;
        *request.headers_mut() = headers;
        let response = drive(&mut driver, sender.send_request(request)).await?;
        let (parts, body) = response.into_parts();
        let body = response::OwnedBody::new(body, driver, lease, deadline);
        let response = http::Response::from_parts(parts, reqwest::Body::wrap(body));
        let response = Response::from(response);
        crate::http::body::headers(&response)?;
        Ok(response)
    }
    async fn connect(
        &self,
        url: &Url,
        deadline: Instant,
    ) -> Result<TlsStream<tokio::net::TcpStream>> {
        let addresses = match &self.resolution {
            RegistryResolution::Static { addresses } => addresses.clone(),
            RegistryResolution::Dns { .. } => self
                .resolver
                .as_ref()
                .ok_or_else(|| invalid("oci-resolver-missing"))?
                .resolve(deadline)
                .await
                .map_err(error)?
                .iter()
                .collect(),
        };
        let port = url
            .port_or_known_default()
            .ok_or_else(|| invalid("invalid-oci-port"))?;
        let connect_deadline = deadline.min(Instant::now() + self.limits.connect_timeout);
        let mut connected = None;
        for address in &addresses {
            if !self.policy.permits(*address) {
                return Err(crate::error(
                    PlatformErrorCode::PermissionDenied,
                    "oci-connected-peer-denied",
                ));
            }
            let socket = if address.is_ipv4() {
                TcpSocket::new_v4()
            } else {
                TcpSocket::new_v6()
            }
            .map_err(|_| connection_error())?;
            socket
                .set_send_buffer_size(16384)
                .map_err(|_| connection_error())?;
            socket
                .set_recv_buffer_size(32768)
                .map_err(|_| connection_error())?;
            if let Ok(stream) = timeout_at(
                connect_deadline,
                socket.connect(SocketAddr::new(*address, port)),
            )
            .await
            .map_err(|_| deadline_error())?
            {
                connected = Some(stream);
                break;
            }
        }
        let stream = connected.ok_or_else(connection_error)?;
        let peer = stream.peer_addr().map_err(|_| connection_error())?;
        if peer.port() != port
            || !self.policy.permits(peer.ip())
            || !addresses
                .iter()
                .any(|address| canonical(*address) == canonical(peer.ip()))
        {
            return Err(crate::error(
                PlatformErrorCode::PermissionDenied,
                "oci-connected-peer-denied",
            ));
        }
        let host = url
            .host_str()
            .ok_or_else(|| invalid("invalid-oci-origin"))?
            .trim_matches(['[', ']']);
        let name = rustls::pki_types::ServerName::try_from(host.to_owned())
            .map_err(|_| invalid("invalid-oci-tls-name"))?;
        let connector = TlsConnector::from(Arc::clone(&self.tls));
        let stream = timeout_at(
            connect_deadline,
            connector.connect_with(name, stream, |connection| {
                connection.set_buffer_limit(Some(16384));
            }),
        )
        .await
        .map_err(|_| deadline_error())?
        .map_err(|_| connection_error())?;
        if stream
            .get_ref()
            .1
            .alpn_protocol()
            .is_some_and(|protocol| protocol != b"http/1.1")
        {
            return Err(connection_error());
        }
        Ok(stream)
    }
}

pub(super) async fn drive<F: Future<Output = std::result::Result<Value, hyper::Error>>, Value>(
    driver: &mut Driver,
    future: F,
) -> Result<Value> {
    let mut future = std::pin::pin!(future);
    std::future::poll_fn(|context| {
        if let Poll::Ready(result) = future.as_mut().poll(context) {
            return Poll::Ready(result.map_err(|_| connection_error()));
        }
        if Pin::new(&mut *driver).poll(context).is_ready() {
            return match future.as_mut().poll(context) {
                Poll::Ready(result) => Poll::Ready(result.map_err(|_| connection_error())),
                Poll::Pending => Poll::Ready(Err(connection_error())),
            };
        }
        future
            .as_mut()
            .poll(context)
            .map(|result| result.map_err(|_| connection_error()))
    })
    .await
}

pub(super) struct Lease {
    counters: Arc<Counters>,
    bytes: usize,
}

impl Counters {
    fn reserve(self: &Arc<Self>, bytes: usize) -> Result<Lease> {
        if self.closed.load(Ordering::Acquire) {
            return Err(crate::error(
                PlatformErrorCode::Unavailable,
                "oci-network-closed",
            ));
        }
        let bytes = bytes
            .checked_add(256 * 1024)
            .ok_or_else(|| exhausted("oci-connection-byte-limit"))?;
        self.connections
            .fetch_update(Ordering::AcqRel, Ordering::Acquire, |current| {
                (current < self.maximum_connections).then_some(current + 1)
            })
            .map_err(|_| exhausted("oci-connection-limit"))?;
        if self
            .bytes
            .fetch_update(Ordering::AcqRel, Ordering::Acquire, |current| {
                current
                    .checked_add(bytes)
                    .filter(|total| *total <= self.maximum_bytes)
            })
            .is_err()
        {
            self.connections.fetch_sub(1, Ordering::AcqRel);
            return Err(exhausted("oci-connection-byte-limit"));
        }
        Ok(Lease {
            counters: Arc::clone(self),
            bytes,
        })
    }
}

impl Drop for Lease {
    fn drop(&mut self) {
        self.counters.bytes.fetch_sub(self.bytes, Ordering::AcqRel);
        self.counters.connections.fetch_sub(1, Ordering::AcqRel);
        self.counters.retired.notify_waiters();
    }
}

pub(super) fn tls(config: &RegistryConfig) -> Result<Arc<rustls::ClientConfig>> {
    if config.additional_root_certificates.len() > 8
        || config
            .additional_root_certificates
            .iter()
            .any(|root| root.len() > 65536)
    {
        return Err(invalid("oci-tls-root-limit"));
    }
    let mut roots = rustls::RootCertStore::empty();
    roots.extend(webpki_roots::TLS_SERVER_ROOTS.iter().cloned());
    for root in &config.additional_root_certificates {
        roots
            .add(rustls::pki_types::CertificateDer::from(root.clone()))
            .map_err(|_| invalid("invalid-oci-tls-root"))?;
    }
    let mut tls = rustls::ClientConfig::builder_with_provider(Arc::new(
        rustls::crypto::ring::default_provider(),
    ))
    .with_safe_default_protocol_versions()
    .map_err(|_| invalid("invalid-oci-tls-configuration"))?
    .with_root_certificates(roots)
    .with_no_client_auth();
    tls.alpn_protocols = vec![b"http/1.1".to_vec()];
    Ok(Arc::new(tls))
}

fn deadline_error() -> latent_core::PlatformError {
    crate::error(
        PlatformErrorCode::DeadlineExceeded,
        "oci-operation-deadline",
    )
}

fn connection_error() -> latent_core::PlatformError {
    crate::error(PlatformErrorCode::Unavailable, "oci-transport-failed")
}
