use std::future::Future;
use std::pin::Pin;
use std::sync::atomic::{AtomicU8, AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};
use std::task::{Context, Poll};
use std::time::Instant;

use http_body::{Body as HttpBody, Frame, SizeHint};
use latent_activation::ActivationStatus;
use latent_core::{ActivationClock, BoxFuture, CancelDisposition, ClockSample, PlatformError};
use latent_wire::invocation::{
    CancellationCommand, InvocationCancellation, InvocationCommand, InvocationInterruption,
    InvocationResponse, InvocationRuntime, StatusQuery,
};
use tonic::body::Body;
use tonic::codegen::{
    http::{Request, Response},
    Bytes,
};
use tonic::transport::Channel;
use tower::Service;

use super::super::super::signal::{Signal, SignalWaiter};

pub(super) struct Clock(pub(super) Mutex<ClockSample>);
impl ActivationClock for Clock {
    fn sample(&self) -> ClockSample {
        *self.0.lock().unwrap()
    }
    fn monotonic_now(&self) -> Instant {
        self.sample().monotonic()
    }
}

#[derive(Default)]
pub(super) struct Runtime {
    pub(super) started: AtomicUsize,
    pub(super) dropped: Arc<AtomicU8>,
}
impl InvocationRuntime for Runtime {
    fn invoke(
        &self,
        _command: InvocationCommand,
        cancellation: InvocationCancellation,
    ) -> BoxFuture<'_, Result<InvocationResponse, PlatformError>> {
        self.started.fetch_add(1, Ordering::Release);
        Box::pin(PendingInvocation {
            cancellation,
            dropped: Arc::clone(&self.dropped),
        })
    }
    fn cancel(
        &self,
        _command: CancellationCommand,
    ) -> BoxFuture<'_, Result<CancelDisposition, PlatformError>> {
        Box::pin(std::future::ready(Ok(CancelDisposition::NotFound)))
    }
    fn get_activation(
        &self,
        _query: StatusQuery,
    ) -> BoxFuture<'_, Result<Option<ActivationStatus>, PlatformError>> {
        Box::pin(std::future::ready(Ok(None)))
    }
}
struct PendingInvocation {
    cancellation: InvocationCancellation,
    dropped: Arc<AtomicU8>,
}
impl Future for PendingInvocation {
    type Output = Result<InvocationResponse, PlatformError>;
    fn poll(self: Pin<&mut Self>, _: &mut Context<'_>) -> Poll<Self::Output> {
        Poll::Pending
    }
}
impl Drop for PendingInvocation {
    fn drop(&mut self) {
        self.dropped.store(
            match self.cancellation.cause() {
                Some(InvocationInterruption::DeadlineExceeded) => 2,
                Some(InvocationInterruption::Cancelled) => 1,
                None => 3,
            },
            Ordering::Release,
        );
    }
}

#[derive(Clone)]
pub(super) struct DelayedChannel {
    pub(super) channel: Channel,
    pub(super) gate: Arc<Signal>,
}
impl Service<Request<Body>> for DelayedChannel {
    type Response = Response<Body>;
    type Error = tonic::transport::Error;
    type Future = <Channel as Service<Request<Body>>>::Future;
    fn poll_ready(&mut self, cx: &mut Context<'_>) -> Poll<Result<(), Self::Error>> {
        self.channel.poll_ready(cx)
    }
    fn call(&mut self, request: Request<Body>) -> Self::Future {
        let ready = self.gate.listen();
        self.channel.call(request.map(|body| {
            Body::new(DelayedBody {
                inner: Box::pin(body),
                ready,
            })
        }))
    }
}
struct DelayedBody {
    inner: Pin<Box<Body>>,
    ready: SignalWaiter,
}
impl HttpBody for DelayedBody {
    type Data = Bytes;
    type Error = tonic::Status;
    fn poll_frame(
        mut self: Pin<&mut Self>,
        cx: &mut Context<'_>,
    ) -> Poll<Option<Result<Frame<Bytes>, tonic::Status>>> {
        if Pin::new(&mut self.ready).poll(cx).is_pending() {
            return Poll::Pending;
        }
        self.inner.as_mut().poll_frame(cx)
    }
    fn size_hint(&self) -> SizeHint {
        self.inner.size_hint()
    }
}
