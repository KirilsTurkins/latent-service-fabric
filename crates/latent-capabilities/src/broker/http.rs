//! Buffered HTTP v0.2: bounded data and an explicitly installed trusted port.
//! These DTOs do not grant network authority. Only the original session can do so.
use super::{io::IoBuffer, pools::PoolCall, CapabilitySession};
use latent_core::{BoxFuture, PlatformError, PlatformErrorCode};

pub const HTTP_CAPABILITY: &str = "latent:http/client@0.2.0";
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum HttpMethod {
    Get,
    Head,
    Post,
    Put,
    Patch,
    Delete,
    Options,
}
impl HttpMethod {
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Get => "GET",
            Self::Head => "HEAD",
            Self::Post => "POST",
            Self::Put => "PUT",
            Self::Patch => "PATCH",
            Self::Delete => "DELETE",
            Self::Options => "OPTIONS",
        }
    }
    #[must_use]
    pub const fn follows_redirects(self) -> bool {
        matches!(self, Self::Get | Self::Head)
    }
}
// Deliberately no Debug implementation that might print a payload or credential.
pub struct HttpHeader {
    pub name: String,
    pub value: String,
}
pub struct HttpRequest {
    pub method: HttpMethod,
    pub url: String,
    pub headers: Vec<HttpHeader>,
    pub body: Option<Vec<u8>>,
    pub body_media_type: Option<String>,
    pub idempotency_key: Option<String>,
    pub timeout_millis: Option<u64>,
}
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum HttpError {
    InvalidUrl,
    InvalidRequest,
    PermissionDenied,
    RequestTooLarge,
    ResponseTooLarge,
    DeadlineExceeded,
    Cancelled,
    BudgetExhausted,
    DnsFailed,
    TlsFailed,
    ConnectionFailed,
    Unavailable,
    Uncertain,
}
impl From<PlatformError> for HttpError {
    fn from(error: PlatformError) -> Self {
        match error.code {
            PlatformErrorCode::PermissionDenied | PlatformErrorCode::Unauthenticated => {
                Self::PermissionDenied
            }
            PlatformErrorCode::ResourceExhausted | PlatformErrorCode::AdmissionRejected => {
                Self::BudgetExhausted
            }
            PlatformErrorCode::DeadlineExceeded => Self::DeadlineExceeded,
            PlatformErrorCode::Cancelled => Self::Cancelled,
            PlatformErrorCode::InvalidArgument => Self::InvalidRequest,
            _ => Self::Unavailable,
        }
    }
}
/// Header names and values are encoded as alternating NUL-terminated UTF-8
/// fields in charged fixed-capacity storage. No uncharged owned header map is
/// returned to the guest adapter; canonical lowering has its own call reserve.
pub struct HttpResponse {
    status: u16,
    headers: IoBuffer,
    body: IoBuffer,
}
impl HttpResponse {
    pub fn new(status: u16, headers: IoBuffer, body: IoBuffer) -> Result<Self, HttpError> {
        if !(200..=599).contains(&status) {
            return Err(HttpError::ConnectionFailed);
        }
        let bytes = headers.bytes();
        if !bytes.is_empty() && !bytes.ends_with(&[0]) {
            return Err(HttpError::ConnectionFailed);
        }
        let mut fields = bytes.split_inclusive(|b| *b == 0);
        let mut count = 0;
        while let Some(name) = fields.next() {
            let value = fields.next().ok_or(HttpError::ConnectionFailed)?;
            count += 1;
            if count > 64
                || name.len() < 2
                || !name[..name.len() - 1].iter().all(|b| {
                    b.is_ascii_lowercase() || b.is_ascii_digit() || b"!#$%&'*+-.^_`|~".contains(b)
                })
                || std::str::from_utf8(&value[..value.len() - 1]).is_err()
                || value[..value.len() - 1]
                    .iter()
                    .any(|b| *b < 32 && *b != 9 || *b == 127)
            {
                return Err(HttpError::ConnectionFailed);
            }
        }
        Ok(Self {
            status,
            headers: headers.retain()?,
            body: body.retain()?,
        })
    }
    #[must_use]
    pub fn status(&self) -> u16 {
        self.status
    }
    #[must_use]
    pub fn body(&self) -> &[u8] {
        self.body.bytes()
    }
    pub fn headers(&self) -> impl Iterator<Item = (&str, &str)> {
        let mut fields = self.headers.bytes().split_inclusive(|b| *b == 0);
        std::iter::from_fn(move || {
            let name = fields.next()?;
            let value = fields.next().expect("validated header pair");
            Some((
                std::str::from_utf8(&name[..name.len() - 1]).expect("validated name"),
                std::str::from_utf8(&value[..value.len() - 1]).expect("validated value"),
            ))
        })
    }
    #[must_use]
    pub fn body_media_type(&self) -> Option<&str> {
        self.headers()
            .find(|(name, _)| *name == "content-type")
            .map(|(_, value)| value)
    }
}
/// Result data drops before the original operation. Hosts retain `owner` through
/// canonical lowering; a returned DTO or completed audit is not cleanup proof.
pub struct HttpCompletion {
    pub response: Result<HttpResponse, HttpError>,
    pub owner: PoolCall,
}
pub type HttpInvocation = BoxFuture<'static, Result<HttpCompletion, HttpError>>;
pub trait OutboundHttpInvoker: Send + Sync {
    /// Reserve bounded queue/input ownership synchronously; no network work is
    /// accepted until the returned future passes its final policy/audit barrier.
    fn start(
        &self,
        session: &CapabilitySession,
        request: HttpRequest,
    ) -> Result<HttpInvocation, HttpError>;
}
