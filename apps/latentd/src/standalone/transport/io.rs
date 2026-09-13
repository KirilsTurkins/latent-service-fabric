use std::future::Future;
use std::io;
use std::net::SocketAddr;
use std::pin::Pin;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::task::{Context, Poll};

use tokio::io::{AsyncRead, AsyncWrite, ReadBuf};
use tokio::net::{TcpListener, TcpStream};
use tonic::codegen::tokio_stream::Stream;
use tonic::transport::server::Connected;

use super::signal::SignalWaiter;
use super::state::{Guard, Kind, Shared};

pub(super) struct Incoming {
    pub(super) listener: TcpListener,
    pub(super) shared: Arc<Shared>,
    pub(super) stopped: SignalWaiter,
}

impl Stream for Incoming {
    type Item = Result<OwnedIo, io::Error>;
    fn poll_next(mut self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Option<Self::Item>> {
        if Pin::new(&mut self.stopped).poll(cx).is_ready() {
            return Poll::Ready(None);
        }
        // Reject floods in bounded batches without monopolizing a runtime poll.
        for _ in 0..16 {
            let (stream, address) = match self.listener.poll_accept(cx) {
                Poll::Pending => return Poll::Pending,
                Poll::Ready(Err(error)) => return Poll::Ready(Some(Err(error))),
                Poll::Ready(Ok(accepted)) => accepted,
            };
            let Ok(guard) = self.shared.acquire(Kind::Connection) else {
                drop(stream);
                continue;
            };
            stream.set_nodelay(true)?;
            let expires_at = tokio::time::Instant::now() + self.shared.config.unauthenticated_timeout;
            let connection = ConnectionInfo {
                address,
                expires_at,
                authenticated: Arc::new(AtomicBool::new(false)),
            };
            return Poll::Ready(Some(Ok(OwnedIo {
                stream: Some(stream),
                connection,
                unauthenticated_deadline: Box::pin(tokio::time::sleep_until(expires_at)),
                read_stop: self.shared.force.listen(),
                write_stop: self.shared.force.listen(),
                shared: Arc::clone(&self.shared),
                guard: Some(guard),
            })));
        }
        cx.waker().wake_by_ref();
        Poll::Pending
    }
}

#[derive(Clone)]
pub(super) struct ConnectionInfo {
    address: SocketAddr,
    expires_at: tokio::time::Instant,
    authenticated: Arc<AtomicBool>,
}

impl ConnectionInfo {
    pub(super) fn address(&self) -> SocketAddr {
        self.address
    }

    pub(super) fn mark_authenticated(&self) -> bool {
        if tokio::time::Instant::now() >= self.expires_at {
            return false;
        }
        self.authenticated.store(true, Ordering::Release);
        true
    }

    fn is_authenticated(&self) -> bool {
        self.authenticated.load(Ordering::Acquire)
    }
}

pub(super) struct OwnedIo {
    stream: Option<TcpStream>,
    connection: ConnectionInfo,
    unauthenticated_deadline: Pin<Box<tokio::time::Sleep>>,
    read_stop: SignalWaiter,
    write_stop: SignalWaiter,
    shared: Arc<Shared>,
    guard: Option<Guard>,
}

impl Connected for OwnedIo {
    type ConnectInfo = ConnectionInfo;
    fn connect_info(&self) -> ConnectionInfo {
        self.connection.clone()
    }
}

impl OwnedIo {
    fn close(&mut self) {
        drop(self.stream.take());
        drop(self.guard.take());
    }

    fn expire_unauthenticated(&mut self) {
        if self.guard.is_some() {
            self.shared.expire_unauthenticated_connection();
        }
        self.close();
    }

    fn poll_unauthenticated_expiry(&mut self, cx: &mut Context<'_>) -> bool {
        if self.connection.is_authenticated() {
            return false;
        }
        if self.unauthenticated_deadline.as_mut().poll(cx).is_ready() {
            self.expire_unauthenticated();
            return true;
        }
        false
    }

    fn closed() -> io::Error {
        io::Error::new(
            io::ErrorKind::ConnectionAborted,
            "standalone transport closed",
        )
    }
}

impl AsyncRead for OwnedIo {
    fn poll_read(
        mut self: Pin<&mut Self>,
        cx: &mut Context<'_>,
        buffer: &mut ReadBuf<'_>,
    ) -> Poll<io::Result<()>> {
        if Pin::new(&mut self.read_stop).poll(cx).is_ready() {
            self.close();
            return Poll::Ready(Err(Self::closed()));
        }
        if self.poll_unauthenticated_expiry(cx) {
            return Poll::Ready(Err(Self::closed()));
        }
        match self.stream.as_mut() {
            Some(stream) => Pin::new(stream).poll_read(cx, buffer),
            None => Poll::Ready(Err(Self::closed())),
        }
    }
}
impl AsyncWrite for OwnedIo {
    fn poll_write(
        mut self: Pin<&mut Self>,
        cx: &mut Context<'_>,
        bytes: &[u8],
    ) -> Poll<io::Result<usize>> {
        if Pin::new(&mut self.write_stop).poll(cx).is_ready() {
            self.close();
            return Poll::Ready(Err(Self::closed()));
        }
        if self.poll_unauthenticated_expiry(cx) {
            return Poll::Ready(Err(Self::closed()));
        }
        match self.stream.as_mut() {
            Some(stream) => Pin::new(stream).poll_write(cx, bytes),
            None => Poll::Ready(Err(Self::closed())),
        }
    }
    fn poll_flush(mut self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<io::Result<()>> {
        if Pin::new(&mut self.write_stop).poll(cx).is_ready() {
            self.close();
            return Poll::Ready(Err(Self::closed()));
        }
        if self.poll_unauthenticated_expiry(cx) {
            return Poll::Ready(Err(Self::closed()));
        }
        match self.stream.as_mut() {
            Some(stream) => Pin::new(stream).poll_flush(cx),
            None => Poll::Ready(Err(Self::closed())),
        }
    }
    fn poll_shutdown(mut self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<io::Result<()>> {
        if Pin::new(&mut self.write_stop).poll(cx).is_ready() {
            self.close();
            return Poll::Ready(Ok(()));
        }
        if self.poll_unauthenticated_expiry(cx) {
            return Poll::Ready(Ok(()));
        }
        match self.stream.as_mut() {
            Some(stream) => Pin::new(stream).poll_shutdown(cx),
            None => Poll::Ready(Ok(())),
        }
    }
}
impl Drop for OwnedIo {
    fn drop(&mut self) {
        self.close();
    }
}
