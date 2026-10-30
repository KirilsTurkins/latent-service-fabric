//! Owned HTTP v0.3 continuations of one policy-accepted operation.
use super::{
    http::{HttpError, HttpHeaderBlock, HttpRequest, HttpResponseHead},
    io::{IoFuture, IoOutputChunk},
    CapabilitySession,
};
use latent_core::PlatformError;
use std::{
    future::Future,
    pin::Pin,
    task::{Context, Poll},
};
pub const PHASE_TIMING_CAPABILITY: &str = "latent:http/phase-timing@0.4.0";
pub const STREAMING_HTTP_CAPABILITY: &str = "latent:http/streaming@0.3.0";
/// Metadata has no buffered body. `None` selects bounded chunked framing;
/// `Some(n)` commits an exact length, verified before successful finish.
pub struct StreamingHttpRequest {
    pub metadata: HttpRequest,
    pub body_length: Option<u64>,
}
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum StreamingHttpError {
    Http(HttpError),
    InvalidState,
    UnexpectedEof,
    UnsupportedEncoding,
}
impl From<HttpError> for StreamingHttpError {
    fn from(value: HttpError) -> Self {
        Self::Http(value)
    }
}
impl From<PlatformError> for StreamingHttpError {
    fn from(value: PlatformError) -> Self {
        Self::Http(value.into())
    }
}
pub type StreamingHttpInvocation =
    IoFuture<'static, Result<Box<dyn HttpUpload>, StreamingHttpError>>;
/// Explicit phase outcomes never replace the original activation deadline or cancellation.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum HttpPhaseError {
    Http(StreamingHttpError),
    ConnectTimeout,
    ReadTimeout { external_completion_uncertain: bool },
    Unsupported,
}
impl From<HttpError> for HttpPhaseError {
    fn from(error: HttpError) -> Self {
        Self::Http(error.into())
    }
}
impl From<StreamingHttpError> for HttpPhaseError {
    fn from(error: StreamingHttpError) -> Self {
        Self::Http(error)
    }
}
impl From<PlatformError> for HttpPhaseError {
    fn from(error: PlatformError) -> Self {
        Self::Http(error.into())
    }
}
/// The phase facade adds neither an async mapper Box nor a late admission.
/// A custom timed provider supplies Direct; legacy defaults map inline; early
/// Unsupported results use Ready without constructing an allocation at all.
pub enum HttpPhaseFuture<'a, T> {
    Direct(IoFuture<'a, Result<T, HttpPhaseError>>),
    Legacy(IoFuture<'a, Result<T, StreamingHttpError>>),
    Ready(Option<Result<T, HttpPhaseError>>),
}
// Ready's result is never pin-projected; Direct/Legacy only move pinned pointers.
impl<T> Unpin for HttpPhaseFuture<'_, T> {}
impl<'a, T> HttpPhaseFuture<'a, T> {
    pub fn legacy(source: IoFuture<'a, Result<T, StreamingHttpError>>) -> Self {
        Self::Legacy(source)
    }
    pub fn ready(result: Result<T, HttpPhaseError>) -> Self {
        Self::Ready(Some(result))
    }
}
impl<'a, T> From<IoFuture<'a, Result<T, HttpPhaseError>>> for HttpPhaseFuture<'a, T> {
    fn from(source: IoFuture<'a, Result<T, HttpPhaseError>>) -> Self {
        Self::Direct(source)
    }
}
impl<T> Future for HttpPhaseFuture<'_, T> {
    type Output = Result<T, HttpPhaseError>;
    fn poll(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Self::Output> {
        match self.get_mut() {
            Self::Direct(source) => Pin::new(source).poll(cx),
            Self::Legacy(source) => Pin::new(source)
                .poll(cx)
                .map(|result| result.map_err(Into::into)),
            Self::Ready(result) => {
                Poll::Ready(result.take().expect("phase future polled after completion"))
            }
        }
    }
}
pub type PhaseHttpInvocation = HttpPhaseFuture<'static, Box<dyn HttpUpload>>;
pub trait StreamingHttpInvoker: Send + Sync {
    /// Reserve queue and metadata before constructing the future. Network work
    /// begins only after its final current policy and required audit decision.
    fn start(
        &self,
        session: &CapabilitySession,
        request: StreamingHttpRequest,
    ) -> Result<StreamingHttpInvocation, StreamingHttpError>;
    /// A provider must explicitly implement nonzero phase timers. Existing
    /// implementations cannot silently accept a new timeout contract.
    fn start_with_connect_timeout(
        &self,
        session: &CapabilitySession,
        request: StreamingHttpRequest,
        timeout_millis: Option<u32>,
    ) -> Result<PhaseHttpInvocation, HttpPhaseError> {
        if timeout_millis.is_some_and(|value| value != 0) {
            return Err(HttpPhaseError::Unsupported);
        }
        let future = self.start(session, request)?;
        Ok(HttpPhaseFuture::legacy(future))
    }
}
pub trait HttpUpload: Send {
    fn write(&mut self, bytes: Vec<u8>) -> IoFuture<'_, Result<(), StreamingHttpError>>;
    fn finish(self: Box<Self>) -> IoFuture<'static, Result<Box<dyn HttpBody>, StreamingHttpError>>;
    fn finish_with_read_timeout(
        self: Box<Self>,
        timeout_millis: Option<u32>,
    ) -> HttpPhaseFuture<'static, Box<dyn HttpBody>> {
        if timeout_millis.is_some_and(|value| value != 0) {
            drop(self);
            return HttpPhaseFuture::ready(Err(HttpPhaseError::Unsupported));
        }
        let future = self.finish();
        HttpPhaseFuture::legacy(future)
    }
}
pub trait HttpBody: Send {
    fn head(&self) -> &HttpResponseHead;
    /// A chunk owns both its bytes and one guest lowering copy until actual Drop.
    /// Saturation rejects before polling I/O; dropping held chunks permits retry.
    fn read(
        &mut self,
        maximum_bytes: usize,
    ) -> IoFuture<'_, Result<Option<IoOutputChunk>, StreamingHttpError>>;
    /// Available only after verified EOF. Adapters materialize it at most once.
    fn trailers(&self) -> Result<&HttpHeaderBlock, StreamingHttpError>;
    fn read_with_timeout(
        &mut self,
        maximum_bytes: usize,
        timeout_millis: Option<u32>,
    ) -> HttpPhaseFuture<'_, Option<IoOutputChunk>> {
        if timeout_millis.is_some_and(|value| value != 0) {
            return HttpPhaseFuture::ready(Err(HttpPhaseError::Unsupported));
        }
        let future = self.read(maximum_bytes);
        HttpPhaseFuture::legacy(future)
    }
}
