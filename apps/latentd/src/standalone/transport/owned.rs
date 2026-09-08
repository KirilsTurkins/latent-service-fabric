use std::convert::Infallible;
use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;
use std::task::{Context, Poll};

use http_body::{Body as HttpBody, Frame, SizeHint};
use tonic::body::Body;
use tonic::codegen::{http::Response, Bytes};
use tonic::Status;

use super::signal::{Signal, SignalWaiter};
use super::state::Guard;

pub(super) type ResponseFuture =
    Pin<Box<dyn Future<Output = Result<Response<Body>, Infallible>> + Send>>;

pub(super) struct OwnedRpc {
    inner: Option<ResponseFuture>,
    rpc_guard: Option<Guard>,
    control_guard: Option<Guard>,
    cancel: Arc<Signal>,
    stopped: SignalWaiter,
}

impl OwnedRpc {
    pub(super) fn new(
        inner: ResponseFuture,
        rpc_guard: Guard,
        control_guard: Option<Guard>,
        cancel: Arc<Signal>,
    ) -> Self {
        Self {
            inner: Some(inner),
            rpc_guard: Some(rpc_guard),
            control_guard,
            stopped: cancel.listen(),
            cancel,
        }
    }
    fn finish_inner(&mut self) {
        drop(self.inner.take());
        drop(self.control_guard.take());
    }
}

impl Future for OwnedRpc {
    type Output = Result<Response<Body>, Infallible>;
    fn poll(mut self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Self::Output> {
        if Pin::new(&mut self.stopped).poll(cx).is_ready() {
            self.finish_inner();
            drop(self.rpc_guard.take());
            return Poll::Ready(Ok(
                Status::unavailable("standalone node is stopping").into_http()
            ));
        }
        match self
            .inner
            .as_mut()
            .expect("owned RPC future")
            .as_mut()
            .poll(cx)
        {
            Poll::Pending => Poll::Pending,
            Poll::Ready(Ok(response)) => {
                self.finish_inner();
                let guard = self.rpc_guard.take().expect("owned RPC guard");
                let stopped = self.cancel.listen();
                Poll::Ready(Ok(response.map(|body| {
                    Body::new(OwnedBody {
                        inner: Some(Box::pin(body)),
                        guard: Some(guard),
                        stopped,
                    })
                })))
            }
            Poll::Ready(Err(impossible)) => match impossible {},
        }
    }
}

impl Drop for OwnedRpc {
    fn drop(&mut self) {
        self.finish_inner();
        drop(self.rpc_guard.take());
    }
}

struct OwnedBody {
    inner: Option<Pin<Box<Body>>>,
    guard: Option<Guard>,
    stopped: SignalWaiter,
}
impl OwnedBody {
    fn finish(&mut self) {
        drop(self.inner.take());
        drop(self.guard.take());
    }
}
impl HttpBody for OwnedBody {
    type Data = Bytes;
    type Error = Status;
    fn poll_frame(
        mut self: Pin<&mut Self>,
        cx: &mut Context<'_>,
    ) -> Poll<Option<Result<Frame<Bytes>, Status>>> {
        if self.inner.is_none() {
            return Poll::Ready(None);
        }
        if Pin::new(&mut self.stopped).poll(cx).is_ready() {
            self.finish();
            // A body error becomes an HTTP/2 reset and can misreport this
            // intentional cancellation as INTERNAL_ERROR at the client.
            let mut trailers = tonic::codegen::http::HeaderMap::new();
            let status = Status::unavailable("standalone node is stopping");
            return Poll::Ready(Some(
                status
                    .add_header(&mut trailers)
                    .map(|()| Frame::trailers(trailers)),
            ));
        }
        let Some(inner) = self.inner.as_mut() else {
            return Poll::Ready(None);
        };
        let result = inner.as_mut().poll_frame(cx);
        if matches!(result, Poll::Ready(None | Some(Err(_)))) {
            self.finish();
        }
        result
    }
    fn is_end_stream(&self) -> bool {
        self.inner.as_ref().is_none_or(HttpBody::is_end_stream)
    }
    fn size_hint(&self) -> SizeHint {
        self.inner
            .as_ref()
            .map_or_else(|| SizeHint::with_exact(0), HttpBody::size_hint)
    }
}
impl Drop for OwnedBody {
    fn drop(&mut self) {
        self.finish();
    }
}

/// Dropping a waiter requests task abort; guards remain in the worker until
/// its entire future is actually destroyed, including a currently running poll.
pub(super) struct ControlTask {
    task: tokio::task::JoinHandle<Result<Response<Body>, Infallible>>,
}
impl ControlTask {
    pub(super) fn new(task: tokio::task::JoinHandle<Result<Response<Body>, Infallible>>) -> Self {
        Self { task }
    }
}
impl Future for ControlTask {
    type Output = Result<Response<Body>, Infallible>;
    fn poll(mut self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Self::Output> {
        match Pin::new(&mut self.task).poll(cx) {
            Poll::Pending => Poll::Pending,
            Poll::Ready(Ok(response)) => Poll::Ready(response),
            Poll::Ready(Err(_)) => Poll::Ready(Ok(Status::unavailable(
                "standalone control operation was interrupted",
            )
            .into_http())),
        }
    }
}
impl Drop for ControlTask {
    fn drop(&mut self) {
        self.task.abort();
    }
}
