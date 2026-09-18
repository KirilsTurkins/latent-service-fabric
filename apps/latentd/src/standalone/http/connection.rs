use super::{
    dispatch, head, millis,
    state::{ConnectionPermit, Signal},
    tls::Socket,
    write, Shared,
};
use latent_core::IncomingDeadline;
use latent_node::ActivationTransportInterruption;
use std::{
    future::Future,
    io,
    net::SocketAddr,
    pin::Pin,
    sync::Arc,
    task::{Context, Poll},
};
use tokio::{
    io::{AsyncRead, AsyncReadExt, AsyncWrite, AsyncWriteExt},
    net::TcpStream,
    time::{timeout_at, Instant},
};
use zeroize::{Zeroize, Zeroizing};

// Construct the socket/permit aggregate before spawning: an unpolled task must
// close its actual socket before reporting the connection reservation returned.
pub(super) fn run(
    socket: TcpStream,
    peer: SocketAddr,
    permit: ConnectionPermit,
    shared: Arc<Shared>,
) -> impl std::future::Future<Output = ()> + Send {
    let socket = Socket {
        socket,
        handshake_remaining: Some(64 * 1024),
    };
    let age = Instant::now() + millis(shared.settings.limits.maximum_connection_age_millis);
    let work = async move {
        let work = connection(socket, peer, shared.clone(), age);
        tokio::select! {
            () = shared.handle.stopped(Signal::Forced) => {}
            () = work => {}
        }
    };
    OwnedConnection {
        work: Box::pin(work),
        _permit: permit,
    }
}
struct OwnedConnection<F> {
    work: Pin<Box<F>>,
    _permit: ConnectionPermit,
}
impl<F: Future<Output = ()>> Future for OwnedConnection<F> {
    type Output = ();
    fn poll(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<()> {
        self.get_mut().work.as_mut().poll(cx)
    }
}
async fn connection(mut socket: Socket, peer: SocketAddr, shared: Arc<Shared>, age: Instant) {
    if (!shared.settings.peers.is_empty() && !shared.settings.peers.contains(&peer.ip()))
        || (shared.settings.scheme == latent_ingress::http::Scheme::Http
            && !peer.ip().is_loopback())
    {
        return;
    }
    // Finite send/receive buffers are inherited from the listening socket.
    if socket.socket.set_nodelay(true).is_err() {
        return;
    }
    if let Some(configuration) = &shared.settings.tls {
        let acceptor = tokio_rustls::TlsAcceptor::from(configuration.clone());
        let expiry =
            age.min(Instant::now() + millis(shared.settings.limits.handshake_timeout_millis));
        let Ok(Ok(mut stream)) = timeout_at(
            expiry,
            acceptor.accept_with(socket, |tls| tls.set_buffer_limit(Some(64 * 1024))),
        )
        .await
        else {
            return;
        };
        stream.get_mut().0.handshake_remaining = None;
        serve(&mut stream, &shared, age).await;
    } else {
        socket.handshake_remaining = None;
        serve(&mut socket, &shared, age).await;
    }
}
async fn serve<S: AsyncRead + AsyncWrite + Unpin>(socket: &mut S, shared: &Shared, age: Instant) {
    let mut buffer = Zeroizing::new(Vec::new());
    if buffer.try_reserve_exact(head::MAX_HEAD).is_err() {
        return;
    }
    buffer.resize(head::MAX_HEAD, 0);
    for index in 0..shared.settings.limits.maximum_requests_per_connection {
        if !shared.handle.accepting() {
            break;
        }
        let result = exchange(socket, shared, &mut buffer, index, age).await;
        match result {
            Ok(false) => {}
            Ok(true) | Err(0) => break,
            Err(status) => {
                let until =
                    age.min(Instant::now() + millis(shared.settings.limits.write_timeout_millis));
                let _ = timeout_at(until, write::error(socket, status)).await;
                break;
            }
        }
    }
    // Includes TLS close_notify flushing. The connection reservation stays in
    // the stream until this bounded shutdown or actual socket destruction.
    let until = age.min(Instant::now() + millis(shared.settings.limits.write_timeout_millis));
    let _ = timeout_at(until, socket.shutdown()).await;
}
async fn exchange<S: AsyncRead + AsyncWrite + Unpin>(
    socket: &mut S,
    shared: &Shared,
    buffer: &mut [u8],
    index: u32,
    age: Instant,
) -> Result<bool, u16> {
    let (used, end, deadline) = read_head(socket, shared, buffer, index == 0, age).await?;
    let mut head = head::parse(&buffer[..end], shared, deadline)?;
    let close = head.close || index + 1 == shared.settings.limits.maximum_requests_per_connection;
    if used - end > head.content_length {
        return Err(400);
    }
    let path = head.collector.target().path();
    if path == "/_lsf/assets" || path.starts_with(latent_artifacts::web::IMMUTABLE_ASSET_PREFIX) {
        if used != end {
            return Err(400);
        }
        return super::assets::exchange(socket, shared, head, &mut buffer[..end], deadline, close)
            .await;
    }
    // The immutable namespace never reaches trigger lookup or cell reservation,
    // including misses, malformed locators, HEAD, 304 and rejected methods.
    let selected = dispatch::select(&head, shared)?;
    head.collector
        .append(&buffer[end..used])
        .map_err(|e| e.status().unwrap_or(0))?;
    let mut remaining = head.content_length - (used - end);
    buffer.zeroize();
    let body_until = Instant::from_std(deadline.monotonic())
        .min(Instant::now() + millis(shared.settings.limits.body_timeout_millis));
    while remaining != 0 {
        let maximum = remaining.min(buffer.len());
        let n = read_until(socket, &mut buffer[..maximum], body_until).await?;
        head.collector
            .append(&buffer[..n])
            .map_err(|e| e.status().unwrap_or(0))?;
        remaining -= n;
    }
    buffer.zeroize();
    let mut activation = dispatch::begin(head, selected, shared)?;
    let mut unexpected = [0u8; 1];
    let result = tokio::select! {
        biased;
        () = tokio::time::sleep_until(deadline.monotonic().into()) => {
            activation.interrupt(ActivationTransportInterruption::DeadlineExceeded);
            return Err(0);
        }
        // EOF (including a client write-half-close), error, or premature pipelined
        // input cancels this profile. There is no second unbounded request queue.
        _ = socket.read(&mut unexpected) => {
            activation.interrupt(ActivationTransportInterruption::Disconnected);
            return Err(0);
        }
        result = &mut activation => result,
    };
    let delivery = dispatch::complete(result.0, result.1)?;
    let close = close || !shared.handle.accepting();
    let until = Instant::from_std(deadline.monotonic())
        .min(Instant::now() + millis(shared.settings.limits.write_timeout_millis));
    timeout_at(until, write::delivery(socket, delivery, close))
        .await
        .map_err(|_| 0u16)?
        .map_err(|_| 0u16)?;
    Ok(close)
}
async fn read_head<S: AsyncRead + Unpin>(
    socket: &mut S,
    shared: &Shared,
    buffer: &mut [u8],
    first: bool,
    age: Instant,
) -> Result<(usize, usize, IncomingDeadline), u16> {
    let limits = shared.settings.limits;
    let idle = if first {
        limits.header_timeout_millis
    } else {
        limits.idle_timeout_millis
    };
    let mut used = tokio::select! {
        () = shared.handle.stopped(Signal::Draining) => return Err(0),
        r = read_until(socket, buffer, age.min(Instant::now() + millis(idle))) => r?,
    };
    let sample = shared.services.clock.sample();
    let expires = age
        .into_std()
        .min(sample.monotonic() + millis(shared.settings.request_timeout_millis));
    let projected = sample.unix_millis().saturating_add(
        u64::try_from(
            expires
                .saturating_duration_since(sample.monotonic())
                .as_millis(),
        )
        .map_err(|_| 0u16)?,
    );
    let deadline = IncomingDeadline::new(expires, projected);
    let header_until =
        Instant::from_std(expires).min(Instant::now() + millis(limits.header_timeout_millis));
    let mut scan = 0;
    loop {
        if let Some(offset) = buffer[scan..used].windows(4).position(|s| s == b"\r\n\r\n") {
            return Ok((used, scan + offset + 4, deadline));
        }
        if used == buffer.len() {
            return Err(431);
        }
        scan = used.saturating_sub(3);
        used += tokio::select! {
            () = shared.handle.stopped(Signal::Draining) => return Err(0),
            r = read_until(socket, &mut buffer[used..], header_until) => r?,
        };
    }
}
async fn read_until<S: AsyncRead + Unpin>(
    socket: &mut S,
    buffer: &mut [u8],
    until: Instant,
) -> Result<usize, u16> {
    let n = timeout_at(until, socket.read(buffer))
        .await
        .map_err(|_| 0u16)?
        .map_err(|_: io::Error| 0u16)?;
    if n == 0 {
        Err(0)
    } else {
        Ok(n)
    }
}
