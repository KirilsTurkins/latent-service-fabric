//! Owned HTTP v0.3 continuations of one policy-accepted operation.
use super::{
    http::{HttpError, HttpHeaderBlock, HttpRequest, HttpResponseHead},
    io::IoOutputChunk,
    CapabilitySession,
};
use latent_core::{BoxFuture, PlatformError};
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
pub trait StreamingHttpInvoker: Send + Sync {
    /// Reserve queue and metadata before constructing the future. Network work
    /// begins only after its final current policy and required audit decision.
    fn start(
        &self,
        session: &CapabilitySession,
        request: StreamingHttpRequest,
    ) -> Result<StreamingHttpInvocation, StreamingHttpError>;
}
pub trait HttpUpload: Send {
    fn write(&mut self, bytes: Vec<u8>) -> BoxFuture<'_, Result<(), StreamingHttpError>>;
    fn finish(self: Box<Self>)
        -> BoxFuture<'static, Result<Box<dyn HttpBody>, StreamingHttpError>>;
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
}
