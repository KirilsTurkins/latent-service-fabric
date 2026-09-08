use std::future::Future;
use std::io;
use std::net::SocketAddr;
use std::pin::Pin;
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
            return Poll::Ready(Some(Ok(OwnedIo {
                stream: Some(stream),
                address,
                read_stop: self.shared.force.listen(),
                write_stop: self.shared.force.listen(),
                guard: Some(guard),
            })));
        }
        cx.waker().wake_by_ref();
        Poll::Pending
    }
}

pub(super) struct OwnedIo {
    stream: Option<TcpStream>,
    address: SocketAddr,
    read_stop: SignalWaiter,
    write_stop: SignalWaiter,
    guard: Option<Guard>,
}

impl Connected for OwnedIo {
    type ConnectInfo = SocketAddr;
    fn connect_info(&self) -> SocketAddr {
        self.address
    }
}

impl OwnedIo {
    fn close(&mut self) {
        drop(self.stream.take());
        drop(self.guard.take());
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
