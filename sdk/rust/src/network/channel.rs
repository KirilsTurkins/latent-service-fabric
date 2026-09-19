use super::{
    ownership::{Executor, Lease, Resources, WorkLease},
    FailureKind, RpcFailure,
};
use http_body::{Body, Frame, SizeHint};
use std::{
    future::Future,
    io,
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
    net::{TcpSocket, TcpStream},
    time::{timeout_at, Instant},
};
use tonic::{
    body::Body as GrpcBody,
    transport::{Channel, Endpoint},
};
use tower::Service;

pub(super) async fn connect(
    address: SocketAddr,
    resources: Arc<Resources>,
    deadline: Instant,
) -> Result<Channel, RpcFailure> {
    let attempted = Arc::new(AtomicBool::new(false));
    let endpoint = Endpoint::from_shared(format!("http://{address}"))
        .map_err(|_| RpcFailure::local(FailureKind::InvalidConfiguration))?
        .buffer_size(resources.limits.maximum_calls)
        .concurrency_limit(resources.limits.maximum_calls)
        .initial_stream_window_size(32768)
        .initial_connection_window_size(128 * 1024)
        .http2_adaptive_window(false)
        .http2_max_header_list_size(16384)
        .http2_header_table_size(4096)
        .max_frame_size(16384)
        .executor(Executor(Arc::clone(&resources)));
    let connector = tower::service_fn(move |_uri: http::Uri| {
        let resources = Arc::clone(&resources);
        let attempted = Arc::clone(&attempted);
        async move {
            if attempted.swap(true, Ordering::AcqRel) || *resources.closed.borrow() {
                return Err(io::Error::other("explicit-client-reconnect-required"));
            }
            let permit = resources
                .sockets
                .clone()
                .try_acquire_owned()
                .map_err(|_| io::Error::other("client-socket-limit"))?;
            let lease = WorkLease {
                permit: Some(permit),
                resources: Arc::clone(&resources),
            };
            let socket = if address.is_ipv4() {
                TcpSocket::new_v4()?
            } else {
                TcpSocket::new_v6()?
            };
            socket.set_send_buffer_size(32768)?;
            socket.set_recv_buffer_size(128 * 1024)?;
            let stream = timeout_at(deadline, socket.connect(address))
                .await
                .map_err(|_| {
                    io::Error::new(io::ErrorKind::TimedOut, "client-connect-deadline")
                })??;
            if stream.peer_addr()? != address {
                return Err(io::Error::other("client-peer-mismatch"));
            }
            stream.set_nodelay(true)?;
            Ok(hyper_util::rt::TokioIo::new(TrackedSocket {
                stream: Some(stream),
                _lease: lease,
            }))
        }
    });
    timeout_at(deadline, endpoint.connect_with_connector(connector))
        .await
        .map_err(|_| RpcFailure::local(FailureKind::Deadline))?
        .map_err(|_| RpcFailure::local(FailureKind::Connection))
}

struct TrackedSocket {
    stream: Option<TcpStream>,
    _lease: WorkLease,
}

impl Drop for TrackedSocket {
    fn drop(&mut self) {
        self.stream.take();
    }
}

impl AsyncRead for TrackedSocket {
    fn poll_read(
        self: Pin<&mut Self>,
        context: &mut Context<'_>,
        buffer: &mut ReadBuf<'_>,
    ) -> Poll<io::Result<()>> {
        Pin::new(self.get_mut().stream.as_mut().expect("live tracked socket"))
            .poll_read(context, buffer)
    }
}

impl AsyncWrite for TrackedSocket {
    fn poll_write(
        self: Pin<&mut Self>,
        context: &mut Context<'_>,
        bytes: &[u8],
    ) -> Poll<io::Result<usize>> {
        Pin::new(self.get_mut().stream.as_mut().expect("live tracked socket"))
            .poll_write(context, bytes)
    }
    fn poll_flush(self: Pin<&mut Self>, context: &mut Context<'_>) -> Poll<io::Result<()>> {
        Pin::new(self.get_mut().stream.as_mut().expect("live tracked socket")).poll_flush(context)
    }
    fn poll_shutdown(self: Pin<&mut Self>, context: &mut Context<'_>) -> Poll<io::Result<()>> {
        Pin::new(self.get_mut().stream.as_mut().expect("live tracked socket"))
            .poll_shutdown(context)
    }
}

#[derive(Clone)]
pub(super) struct CallChannel {
    pub channel: Channel,
    pub lease: Arc<Lease>,
}

impl Service<http::Request<GrpcBody>> for CallChannel {
    type Response = http::Response<GrpcBody>;
    type Error = tonic::transport::Error;
    type Future = Pin<Box<dyn Future<Output = Result<Self::Response, Self::Error>> + Send>>;

    fn poll_ready(&mut self, context: &mut Context<'_>) -> Poll<Result<(), Self::Error>> {
        self.channel.poll_ready(context)
    }

    fn call(&mut self, request: http::Request<GrpcBody>) -> Self::Future {
        let lease = Arc::clone(&self.lease);
        let request = request.map(|inner| {
            GrpcBody::new(OwnedBody {
                inner,
                _lease: Arc::clone(&lease),
            })
        });
        let future = self.channel.call(request);
        Box::pin(async move {
            let response = future.await?;
            Ok(response.map(|inner| {
                GrpcBody::new(OwnedBody {
                    inner,
                    _lease: lease,
                })
            }))
        })
    }
}

struct OwnedBody {
    inner: GrpcBody,
    _lease: Arc<Lease>,
}

impl Body for OwnedBody {
    type Data = <GrpcBody as Body>::Data;
    type Error = <GrpcBody as Body>::Error;

    fn poll_frame(
        self: Pin<&mut Self>,
        context: &mut Context<'_>,
    ) -> Poll<Option<Result<Frame<Self::Data>, Self::Error>>> {
        Pin::new(&mut self.get_mut().inner).poll_frame(context)
    }
    fn is_end_stream(&self) -> bool {
        self.inner.is_end_stream()
    }
    fn size_hint(&self) -> SizeHint {
        self.inner.size_hint()
    }
}
