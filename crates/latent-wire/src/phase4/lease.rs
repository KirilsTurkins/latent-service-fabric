//! The real reservation survives deferred protobuf encoding and byte-frame Drop.
use super::{fence_error, Phase4ResponseOwner};
use http_body::{Body as HttpBody, Frame, SizeHint};
use latent_core::PlatformError;
use std::{
    future::Future,
    pin::Pin,
    sync::Arc,
    task::{Context, Poll},
};
use tonic::{
    body::Body,
    codegen::{http, Bytes, Service},
    server::NamedService,
    Status,
};

#[derive(Clone)]
pub(super) struct ResponseLease(Arc<dyn Phase4ResponseOwner>);
impl ResponseLease {
    pub(super) fn new(owner: Arc<dyn Phase4ResponseOwner>) -> Self {
        Self(owner)
    }
    pub(super) fn check(&self) -> Result<(), PlatformError> {
        let mut calls = 0u8;
        self.0.with_current(&mut || {
            calls = calls.saturating_add(1);
        })?;
        if calls != 1 {
            return Err(fence_error());
        }
        Ok(())
    }
}
#[derive(Clone)]
pub struct Phase4ResponseService<S> {
    inner: S,
}
impl<S> Phase4ResponseService<S> {
    pub(super) fn new(inner: S) -> Self {
        Self { inner }
    }
}
impl<S: NamedService> NamedService for Phase4ResponseService<S> {
    const NAME: &'static str = S::NAME;
}
impl<S, B> Service<http::Request<B>> for Phase4ResponseService<S>
where
    S: Service<http::Request<B>, Response = http::Response<Body>>,
    S::Future: Send + 'static,
{
    type Response = http::Response<Body>;
    type Error = S::Error;
    type Future = Pin<Box<dyn Future<Output = Result<Self::Response, Self::Error>> + Send>>;
    fn poll_ready(&mut self, cx: &mut Context<'_>) -> Poll<Result<(), Self::Error>> {
        self.inner.poll_ready(cx)
    }
    fn call(&mut self, request: http::Request<B>) -> Self::Future {
        let future = self.inner.call(request);
        Box::pin(async move { future.await.map(retain) })
    }
}
fn retain(mut response: http::Response<Body>) -> http::Response<Body> {
    let lease = response.extensions_mut().remove::<ResponseLease>();
    response.map(|body| {
        Body::new(LeasedBody {
            inner: Some(Box::pin(body)),
            lease,
        })
    })
}
struct LeasedBody {
    inner: Option<Pin<Box<Body>>>,
    lease: Option<ResponseLease>,
}
impl LeasedBody {
    fn finish(&mut self) {
        drop(self.inner.take());
        drop(self.lease.take());
    }
}
impl HttpBody for LeasedBody {
    type Data = Bytes;
    type Error = Status;
    fn poll_frame(
        mut self: Pin<&mut Self>,
        cx: &mut Context<'_>,
    ) -> Poll<Option<Result<Frame<Bytes>, Status>>> {
        let Some(inner) = self.inner.as_mut() else {
            return Poll::Ready(None);
        };
        let result = inner.as_mut().poll_frame(cx);
        match result {
            Poll::Ready(Some(Ok(frame))) => {
                let Some(lease) = &self.lease else {
                    return Poll::Ready(Some(Ok(frame)));
                };
                // Encoding has finished outside bookkeeping locks. Transfer only
                // this bounded frame under the real current data-read fence.
                let mut frame = Some(frame);
                let mut published = None;
                let fence = lease.0.with_current(&mut || {
                    published = frame.take();
                });
                if let Err(error) = fence {
                    self.finish();
                    return Poll::Ready(Some(Err(crate::invocation::platform_status(error))));
                }
                let Some(frame) = published else {
                    self.finish();
                    return Poll::Ready(Some(Err(Status::internal(
                        "invalid Phase 4 publication fence",
                    ))));
                };
                Poll::Ready(Some(Ok(match frame.into_data() {
                    Ok(bytes) => Frame::data(Bytes::from_owner(LeasedBytes {
                        bytes,
                        _lease: lease.clone(),
                    })),
                    Err(trailers) => trailers,
                })))
            }
            Poll::Ready(result @ (None | Some(Err(_)))) => {
                self.finish();
                Poll::Ready(result)
            }
            Poll::Pending => Poll::Pending,
        }
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
impl Drop for LeasedBody {
    fn drop(&mut self) {
        self.finish();
    }
}
struct LeasedBytes {
    bytes: Bytes,
    _lease: ResponseLease,
}
impl AsRef<[u8]> for LeasedBytes {
    fn as_ref(&self) -> &[u8] {
        &self.bytes
    }
}

#[cfg(test)]
mod tests;
