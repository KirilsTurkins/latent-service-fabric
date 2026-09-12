//! Keep the page allowance through delayed protobuf encoding and body/frame Drop.
use http_body::{Body as HttpBody, Frame, SizeHint};
use latent_audit::AuditResponseLease;
use std::{
    future::Future,
    pin::Pin,
    task::{Context, Poll},
};
use tonic::{
    body::Body,
    codegen::{http, Bytes, Service},
    server::NamedService,
    Status,
};

#[cfg(all(test, unix))]
mod tests;

#[derive(Clone)]
pub struct AuditResponseService<S> {
    inner: S,
}
impl<S> AuditResponseService<S> {
    pub(crate) fn new(inner: S) -> Self {
        Self { inner }
    }
}
impl<S: NamedService> NamedService for AuditResponseService<S> {
    const NAME: &'static str = S::NAME;
}
impl<S, B> Service<http::Request<B>> for AuditResponseService<S>
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
    let lease = response.extensions_mut().remove::<AuditResponseLease>();
    response.map(|body| {
        Body::new(LeasedBody {
            inner: Some(Box::pin(body)),
            lease,
        })
    })
}
struct LeasedBody {
    inner: Option<Pin<Box<Body>>>,
    lease: Option<AuditResponseLease>,
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
        match inner.as_mut().poll_frame(cx) {
            Poll::Ready(Some(Ok(frame))) => Poll::Ready(Some(Ok(match frame.into_data() {
                Ok(bytes) => Frame::data(match &self.lease {
                    Some(lease) => Bytes::from_owner(LeasedBytes {
                        bytes,
                        _lease: lease.clone(),
                    }),
                    None => bytes,
                }),
                Err(trailers) => trailers,
            }))),
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
    _lease: AuditResponseLease,
}
impl AsRef<[u8]> for LeasedBytes {
    fn as_ref(&self) -> &[u8] {
        &self.bytes
    }
}
