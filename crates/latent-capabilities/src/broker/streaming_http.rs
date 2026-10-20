//! Owned HTTP v0.3 continuations of one policy-accepted operation.
use super::{
    http::{HttpError, HttpHeaderBlock, HttpRequest, HttpResponseHead},
    io::IoOutputChunk,
    CapabilitySession,
};
use latent_core::{BoxFuture, PlatformError};
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
    BoxFuture<'static, Result<Box<dyn HttpUpload>, StreamingHttpError>>;
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
pub type PhaseHttpInvocation = BoxFuture<'static, Result<Box<dyn HttpUpload>, HttpPhaseError>>;
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
        Ok(Box::pin(async move { future.await.map_err(Into::into) }))
    }
}
pub trait HttpUpload: Send {
    fn write(&mut self, bytes: Vec<u8>) -> BoxFuture<'_, Result<(), StreamingHttpError>>;
    fn finish(self: Box<Self>)
        -> BoxFuture<'static, Result<Box<dyn HttpBody>, StreamingHttpError>>;
    fn finish_with_read_timeout(
        self: Box<Self>,
        timeout_millis: Option<u32>,
    ) -> BoxFuture<'static, Result<Box<dyn HttpBody>, HttpPhaseError>> {
        if timeout_millis.is_some_and(|value| value != 0) {
            drop(self);
            return Box::pin(async { Err(HttpPhaseError::Unsupported) });
        }
        let future = self.finish();
        Box::pin(async move { future.await.map_err(Into::into) })
    }
}
pub trait HttpBody: Send {
    fn head(&self) -> &HttpResponseHead;
    /// A chunk owns both its bytes and one guest lowering copy until actual Drop.
    /// Saturation rejects before polling I/O; dropping held chunks permits retry.
    fn read(
        &mut self,
        maximum_bytes: usize,
    ) -> BoxFuture<'_, Result<Option<IoOutputChunk>, StreamingHttpError>>;
    /// Available only after verified EOF. Adapters materialize it at most once.
    fn trailers(&self) -> Result<&HttpHeaderBlock, StreamingHttpError>;
    fn read_with_timeout(
        &mut self,
        maximum_bytes: usize,
        timeout_millis: Option<u32>,
    ) -> BoxFuture<'_, Result<Option<IoOutputChunk>, HttpPhaseError>> {
        if timeout_millis.is_some_and(|value| value != 0) {
            return Box::pin(async { Err(HttpPhaseError::Unsupported) });
        }
        let future = self.read(maximum_bytes);
        Box::pin(async move { future.await.map_err(Into::into) })
    }
}
