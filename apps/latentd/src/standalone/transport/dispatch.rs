use std::convert::Infallible;
use std::sync::Arc;
use std::task::{Context, Poll};

use latent_core::ActivationClock;
use tokio::runtime::Handle;
use tonic::body::Body;
use tonic::codegen::http::{Request, Response};
use tower::{Layer, Service, ServiceExt};

use super::auth;
use super::owned::{ControlTask, OwnedRpc, ResponseFuture};
use super::state::{Kind, Shared};

#[derive(Clone)]
pub(super) struct DispatchLayer {
    pub(super) shared: Arc<Shared>,
    pub(super) clock: Arc<dyn ActivationClock>,
    pub(super) control_runtime: Handle,
}

impl<S> Layer<S> for DispatchLayer {
    type Service = Dispatch<S>;
    fn layer(&self, inner: S) -> Self::Service {
        Dispatch {
            inner,
            layer: self.clone(),
        }
    }
}

#[derive(Clone)]
pub(super) struct Dispatch<S> {
    inner: S,
    layer: DispatchLayer,
}

impl<S> Service<Request<Body>> for Dispatch<S>
where
    S: Service<Request<Body>, Response = Response<Body>, Error = Infallible>
        + Clone
        + Send
        + 'static,
    S::Future: Send + 'static,
{
    type Response = Response<Body>;
    type Error = Infallible;
    type Future = ResponseFuture;
    fn poll_ready(&mut self, _cx: &mut Context<'_>) -> Poll<Result<(), Infallible>> {
        Poll::Ready(Ok(()))
    }
    fn call(&mut self, mut request: Request<Body>) -> ResponseFuture {
        let inspection = matches!(
            request.uri().path(),
            "/latent.invocation.v1.InvocationService/Cancel"
                | "/latent.invocation.v1.InvocationService/GetActivation"
        );
        let guard = match self.layer.shared.acquire(Kind::Rpc { inspection }) {
            Ok(guard) => guard,
            Err(status) => return Box::pin(std::future::ready(Ok(status.into_http()))),
        };
        if let Err(status) = auth::authenticate(
            &mut request,
            &self.layer.shared.config,
            self.layer.clock.as_ref(),
        ) {
            drop(guard);
            return Box::pin(std::future::ready(Ok(status.into_http())));
        }
        let control = request.uri().path().starts_with("/latent.control.v1.");
        let control_guard = if control {
            match self.layer.shared.acquire(Kind::ControlJob) {
                Ok(guard) => Some(guard),
                Err(status) => {
                    drop(guard);
                    return Box::pin(std::future::ready(Ok(status.into_http())));
                }
            }
        } else {
            None
        };
        let future = OwnedRpc::new(
            Box::pin(self.inner.clone().oneshot(request)),
            guard,
            control_guard,
            Arc::clone(&self.layer.shared.cancel),
        );
        if control {
            Box::pin(ControlTask::new(self.layer.control_runtime.spawn(future)))
        } else {
            Box::pin(future)
        }
    }
}
