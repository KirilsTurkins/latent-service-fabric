//! A pool entry owns the real socket and HTTP driver. No task is detached.
use crate::streaming::wire::RequestBody;
use crate::{destination::canonical, dns::Answers, HttpDestination, HttpError};
use latent_capabilities::broker::{
    io::IoMemory,
    pools::{PoolCall, PooledConnection, ProviderClient, ProviderMetadata, ProviderPools},
};
use std::{
    future::Future,
    net::SocketAddr,
    pin::Pin,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
    task::{Context, Poll},
};
use tokio::{
    io::{AsyncRead, AsyncWrite, ReadBuf},
    net::{TcpSocket, TcpStream, UdpSocket},
};
use tokio_rustls::{client::TlsStream, TlsConnector};

type Driver =
    hyper::client::conn::http1::Connection<hyper_util::rt::TokioIo<TrackedStream>, RequestBody>;
pub(crate) enum Network {
    Dns(DnsConnection),
    Http(Box<HttpConnection>),
}
pub(crate) struct DnsConnection {
    pub socket: DnsSocket,
    pub _memory: ProviderMetadata,
}
pub(crate) enum DnsSocket {
    Udp(UdpSocket),
    Tcp(TcpStream),
}
pub(crate) struct HttpConnection {
    pub sender: hyper::client::conn::http1::SendRequest<RequestBody>,
    pub driver: Option<Driver>,
    pub peer: SocketAddr,
    pub wrote: Arc<AtomicBool>,
    pub input: Option<Arc<IoMemory>>,
    _memory: ProviderMetadata,
}
pub(crate) struct OwnedRequestBody {
    pub bytes: Vec<u8>,
    pub _memory: Arc<IoMemory>,
}
impl AsRef<[u8]> for OwnedRequestBody {
    fn as_ref(&self) -> &[u8] {
        &self.bytes
    }
}

pub(crate) async fn connect(
    pools: &ProviderPools,
    client: &Arc<ProviderClient<Network>>,
    call: &PoolCall,
    destination: &HttpDestination,
    answers: &Answers,
    tls: &Arc<rustls::ClientConfig>,
    maximum_headers: usize,
) -> Result<PooledConnection<Network>, HttpError> {
    connect_for(
        pools,
        client,
        crate::protocol::ProtocolScope::Invocation(call),
        destination,
        answers,
        tls,
        maximum_headers,
    )
    .await
}
pub(crate) async fn connect_for(
    pools: &ProviderPools,
    client: &Arc<ProviderClient<Network>>,
    scope: crate::protocol::ProtocolScope<'_>,
    destination: &HttpDestination,
    answers: &Answers,
    tls: &Arc<rustls::ClientConfig>,
    maximum_headers: usize,
) -> Result<PooledConnection<Network>, HttpError> {
    let reused = match scope {
        crate::protocol::ProtocolScope::Invocation(call) => client.checkout_wait(call).await?,
        crate::protocol::ProtocolScope::Maintenance(_) => None,
    };
    if let Some(mut connection) = reused {
        let valid = matches!(connection.resource(), Network::Http(http) if http.driver.is_some() && answers.contains(canonical(http.peer.ip())) && destination.addresses.permits(http.peer.ip()));
        if valid {
            return Ok(connection);
        }
        drop(connection);
    }
    let reservation = match scope {
        crate::protocol::ProtocolScope::Invocation(call) => {
            client.reserve_connection_wait(call).await?
        }
        crate::protocol::ProtocolScope::Maintenance(request) => {
            client.reserve_maintenance_connection(request)?
        }
    };
    // Rustls caps handshake messages at 64 KiB. This separate shared charge
    // covers its finite record/handshake state and Hyper's fixed header buffers;
    // request/body storage has its own actual owner. It is not a total RSS claim.
    let memory = pools.reserve_protocol_metadata(256 * 1024)?;
    let mut connected = None;
    for ip in answers.iter() {
        scope.checkpoint()?;
        if !destination.addresses.permits(ip) {
            return Err(HttpError::PermissionDenied);
        }
        // No HTTP bytes exist yet; only these finite approved peers are tried.
        if let Ok(stream) = scope
            .wait(bounded_tcp_connect(SocketAddr::new(
                ip,
                destination.origin.port,
            )))
            .await?
        {
            connected = Some(stream);
            break;
        }
    }
    let stream = connected.ok_or(HttpError::ConnectionFailed)?;
    let peer = stream
        .peer_addr()
        .map_err(|_| HttpError::ConnectionFailed)?;
    if !answers.contains(canonical(peer.ip()))
        || !destination.addresses.permits(peer.ip())
        || peer.port() != destination.origin.port
    {
        return Err(HttpError::PermissionDenied);
    }
    stream
        .set_nodelay(true)
        .map_err(|_| HttpError::ConnectionFailed)?;
    let stream = if destination.origin.scheme == "https" {
        let name = rustls::pki_types::ServerName::try_from(destination.origin.host.clone())
            .map_err(|_| HttpError::InvalidUrl)?;
        let connector = TlsConnector::from(Arc::clone(tls));
        let stream = scope
            .wait(connector.connect_with(name, stream, |connection| {
                connection.set_buffer_limit(Some(16384));
            }))
            .await?
            .map_err(|_| HttpError::TlsFailed)?;
        if stream
            .get_ref()
            .1
            .alpn_protocol()
            .is_some_and(|p| p != b"http/1.1")
        {
            return Err(HttpError::TlsFailed);
        }
        Stream::Tls(Box::new(stream))
    } else {
        Stream::Tcp(stream)
    };
    let wrote = Arc::new(AtomicBool::new(false));
    let tracked = TrackedStream {
        stream,
        wrote: Arc::clone(&wrote),
    };
    let mut builder = hyper::client::conn::http1::Builder::new();
    builder
        .max_headers(maximum_headers)
        .max_buf_size(32768)
        .http09_responses(false)
        .allow_spaces_after_header_name_in_responses(false)
        .allow_obsolete_multiline_headers_in_responses(false)
        .ignore_invalid_headers_in_responses(false);
    let (sender, driver) = scope
        .wait(builder.handshake(hyper_util::rt::TokioIo::new(tracked)))
        .await?
        .map_err(|_| HttpError::ConnectionFailed)?;
    reservation
        .connected(Network::Http(Box::new(HttpConnection {
            sender,
            driver: Some(driver),
            peer,
            wrote,
            input: None,
            _memory: memory,
        })))
        .map_err(Into::into)
}
/// Drive the connection and its consumer in the caller's original future. The
/// completed driver is dropped once; a cancellation drops its actual socket.
pub(crate) async fn drive<F: Future>(
    driver: &mut Option<Driver>,
    future: F,
) -> Result<F::Output, HttpError> {
    let mut future = std::pin::pin!(future);
    std::future::poll_fn(|cx| {
        if let Poll::Ready(value) = future.as_mut().poll(cx) {
            return Poll::Ready(Ok(value));
        }
        let Some(connection) = driver.as_mut() else {
            return Poll::Ready(Err(HttpError::ConnectionFailed));
        };
        if Pin::new(connection).poll(cx).is_ready() {
            *driver = None;
            return match future.as_mut().poll(cx) {
                Poll::Ready(value) => Poll::Ready(Ok(value)),
                Poll::Pending => Poll::Ready(Err(HttpError::ConnectionFailed)),
            };
        }
        future.as_mut().poll(cx).map(Ok)
    })
    .await
}
pub(crate) enum Stream {
    Tcp(TcpStream),
    Tls(Box<TlsStream<TcpStream>>),
}
pub(crate) struct TrackedStream {
    stream: Stream,
    wrote: Arc<AtomicBool>,
}
impl AsyncRead for TrackedStream {
    fn poll_read(
        self: Pin<&mut Self>,
        cx: &mut Context<'_>,
        buffer: &mut ReadBuf<'_>,
    ) -> Poll<std::io::Result<()>> {
        match &mut self.get_mut().stream {
            Stream::Tcp(stream) => Pin::new(stream).poll_read(cx, buffer),
            Stream::Tls(stream) => Pin::new(stream).poll_read(cx, buffer),
        }
    }
}
impl AsyncWrite for TrackedStream {
    fn poll_write(
        self: Pin<&mut Self>,
        cx: &mut Context<'_>,
        bytes: &[u8],
    ) -> Poll<std::io::Result<usize>> {
        let this = self.get_mut();
        let result = match &mut this.stream {
            Stream::Tcp(stream) => Pin::new(stream).poll_write(cx, bytes),
            Stream::Tls(stream) => Pin::new(stream).poll_write(cx, bytes),
        };
        if matches!(result, Poll::Ready(Ok(n)) if n > 0) {
            this.wrote.store(true, Ordering::Release);
        }
        result
    }
    fn poll_flush(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<std::io::Result<()>> {
        match &mut self.get_mut().stream {
            Stream::Tcp(stream) => Pin::new(stream).poll_flush(cx),
            Stream::Tls(stream) => Pin::new(stream).poll_flush(cx),
        }
    }
    fn poll_shutdown(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<std::io::Result<()>> {
        match &mut self.get_mut().stream {
            Stream::Tcp(stream) => Pin::new(stream).poll_shutdown(cx),
            Stream::Tls(stream) => Pin::new(stream).poll_shutdown(cx),
        }
    }
}

async fn bounded_tcp_connect(peer: SocketAddr) -> std::io::Result<TcpStream> {
    let socket = if peer.is_ipv4() {
        TcpSocket::new_v4()?
    } else {
        TcpSocket::new_v6()?
    };
    socket.set_send_buffer_size(16 * 1024)?;
    socket.set_recv_buffer_size(32 * 1024)?;
    socket.connect(peer).await
}
