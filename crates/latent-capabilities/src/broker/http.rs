//! Buffered HTTP v0.2: bounded data and an explicitly installed trusted port.
//! These DTOs do not grant network authority. Only the original session can do so.
use super::io::IoFuture;
use super::{io::IoBuffer, pools::PoolCall, CapabilitySession};
use latent_core::{PlatformError, PlatformErrorCode};
pub(super) mod refusal;

pub const HTTP_CAPABILITY: &str = "latent:http/client@0.2.0";
pub const MAXIMUM_HTTP_REASON_BYTES: usize = 512;
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
        refusal::observe(refusal::Stage::TypedHttpConversion, &error);
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
pub struct HttpHeaderBlock {
    data: IoBuffer,
}
impl HttpHeaderBlock {
    pub fn new(headers: IoBuffer) -> Result<Self, HttpError> {
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
            data: headers.retain()?,
        })
    }
    pub fn iter(&self) -> impl Iterator<Item = (&str, &str)> {
        let mut fields = self.data.bytes().split_inclusive(|b| *b == 0);
        std::iter::from_fn(move || {
            let name = fields.next()?;
            let value = fields.next().expect("validated header pair");
            Some((
                std::str::from_utf8(&name[..name.len() - 1]).expect("validated name"),
                std::str::from_utf8(&value[..value.len() - 1]).expect("validated value"),
            ))
        })
    }
}
pub struct HttpResponseHead {
    status: u16,
    headers: HttpHeaderBlock,
    reason_phrase: Option<IoBuffer>,
}
impl HttpResponseHead {
    pub fn new(status: u16, headers: IoBuffer) -> Result<Self, HttpError> {
        Self::with_reason_phrase(status, headers, None)
    }
    pub fn with_reason_phrase(
        status: u16,
        headers: IoBuffer,
        reason_phrase: Option<IoBuffer>,
    ) -> Result<Self, HttpError> {
        if !(200..=599).contains(&status) {
            return Err(HttpError::ConnectionFailed);
        }
        if let Some(reason) = &reason_phrase {
            if reason.capacity() > MAXIMUM_HTTP_REASON_BYTES {
                return Err(HttpError::ResponseTooLarge);
            }
            if reason
                .bytes()
                .iter()
                .any(|byte| *byte < 32 && *byte != 9 || *byte == 127)
            {
                return Err(HttpError::ConnectionFailed);
            }
        }
        Ok(Self {
            status,
            headers: HttpHeaderBlock::new(headers)?,
            reason_phrase: reason_phrase.map(IoBuffer::retain).transpose()?,
        })
    }
    #[must_use]
    pub fn status(&self) -> u16 {
        self.status
    }
    /// None is unavailable metadata, while Some(empty) is an actual empty phrase.
    /// The complete original capacity stays charged for this head's lifetime.
    #[must_use]
    pub fn reason_phrase(&self) -> Option<&[u8]> {
        self.reason_phrase.as_ref().map(IoBuffer::bytes)
    }
    pub fn headers(&self) -> impl Iterator<Item = (&str, &str)> {
        self.headers.iter()
    }
    #[must_use]
    pub fn body_media_type(&self) -> Option<&str> {
        self.headers()
            .find(|(name, _)| *name == "content-type")
            .map(|(_, value)| value)
    }
}
pub struct HttpResponse {
    head: HttpResponseHead,
    body: IoBuffer,
}
impl HttpResponse {
    pub fn new(status: u16, headers: IoBuffer, body: IoBuffer) -> Result<Self, HttpError> {
        Ok(Self {
            head: HttpResponseHead::new(status, headers)?,
            body: body.retain()?,
        })
    }
    #[must_use]
    pub fn status(&self) -> u16 {
        self.head.status()
    }
    #[must_use]
    pub fn body(&self) -> &[u8] {
        self.body.bytes()
    }
    pub fn headers(&self) -> impl Iterator<Item = (&str, &str)> {
        self.head.headers()
    }
    #[must_use]
    pub fn body_media_type(&self) -> Option<&str> {
        self.head.body_media_type()
    }
}
/// Result data drops before the original operation. Hosts retain `owner` through
/// canonical lowering; a returned DTO or completed audit is not cleanup proof.
pub struct HttpCompletion {
    pub response: Result<HttpResponse, HttpError>,
    pub owner: PoolCall,
}
pub type HttpInvocation = IoFuture<'static, Result<HttpCompletion, HttpError>>;
pub trait OutboundHttpInvoker: Send + Sync {
    /// Reserve bounded queue/input ownership synchronously; no network work is
    /// accepted until the returned future passes its final policy/audit barrier.
    fn start_from(
        &self,
        session: &CapabilitySession,
        source: &mut dyn HttpRequestSource,
    ) -> Result<HttpInvocation, HttpError>;

    fn start(
        &self,
        session: &CapabilitySession,
        request: HttpRequest,
    ) -> Result<HttpInvocation, HttpError>;
}

// Opt-in borrowed ingress. The legacy DTO and start API remain preallocated.
pub use ingress::{
    HttpBodyOwner, HttpInputLimits, HttpInputMemory, HttpOwnedRequest, HttpRequestSource,
    HttpTextField, PreparedHttpInput,
};
mod ingress {
    use super::*;
    use crate::broker::session::{PreparedShared, SessionCoreOwner, Shared};
    use latent_core::HostMemoryReservation;
    use std::{alloc::Layout, ops::Deref, sync::Arc};

    #[derive(Clone, Copy)]
    pub enum HttpTextField {
        Url,
        HeaderName(usize),
        HeaderValue(usize),
        BodyMediaType,
        IdempotencyKey,
    }
    /// The source is synchronously borrowed; no method returns owned payloads.
    pub trait HttpRequestSource {
        fn method(&self) -> HttpMethod;
        fn timeout_millis(&self) -> Option<u64>;
        fn header_count(&self) -> usize;
        fn text_len(&mut self, field: HttpTextField) -> Result<Option<usize>, HttpError>;
        fn write_text(&mut self, field: HttpTextField, output: &mut [u8]) -> Result<(), HttpError>;
        fn body_len(&self) -> Option<usize>;
        fn write_body(&mut self, output: &mut [u8]) -> Result<(), HttpError>;
    }
    pub struct HttpInputLimits {
        pub maximum_headers: usize,
        pub maximum_header_bytes: usize,
        pub maximum_body_bytes: usize,
    }
    pub struct PreparedHttpInput {
        url: String,
        url_credit: Option<HostMemoryReservation>,
        shared: PreparedShared<Credit>,
        logical_shared: PreparedShared<IoMemory>,
        original: SessionCoreOwner,
    }
    struct Credit {
        _origin: super::super::io::HttpInputOrigin,
        _url: Option<HostMemoryReservation>,
        _rest: Option<HostMemoryReservation>,
        original: SessionCoreOwner,
    }
    #[derive(Clone)]
    enum Memory {
        Legacy(Arc<IoMemory>),
        Funded {
            logical: Shared<IoMemory>,
            original: Shared<Credit>,
        },
    }
    #[derive(Clone)]
    pub struct HttpInputMemory(Memory);
    impl HttpInputMemory {
        fn original(&self) -> Option<&Shared<Credit>> {
            match &self.0 {
                Memory::Legacy(_) => None,
                Memory::Funded { original, .. } => Some(original),
            }
        }
        pub fn legacy(&self) -> Option<&Arc<IoMemory>> {
            match &self.0 {
                Memory::Legacy(x) => Some(x),
                _ => None,
            }
        }
        /// Same current-hop sharing observation as the former Arc<IoMemory>.
        pub fn strong_count(&self) -> usize {
            match &self.0 {
                Memory::Legacy(x) => Arc::strong_count(x),
                Memory::Funded { logical, .. } => Shared::downgrade(logical).strong_count(),
            }
        }
        /// Retain original ingress credit independently of each hop's logical charge.
        pub fn followup(
            &self,
            admission: &super::super::pools::PoolAdmission,
            bytes: usize,
            metadata: usize,
        ) -> Result<Self, HttpError> {
            let logical = admission.reserve_input(bytes, metadata)?;
            Ok(Self(match self.original() {
                None => Memory::Legacy(Arc::new(logical)),
                Some(original) => {
                    if !logical.http_original_session(&original.original) {
                        return Err(HttpError::PermissionDenied);
                    }
                    let prepared = Shared::<IoMemory>::reserve(&original.original.budget)?;
                    Memory::Funded {
                        logical: prepared.allocate(logical),
                        original: original.clone(),
                    }
                }
            }))
        }
        fn same_origin(&self, other: &Self) -> bool {
            match (self.original(), other.original()) {
                (None, None) => true,
                (Some(a), Some(b)) => Shared::ptr_eq(a, b),
                _ => false,
            }
        }
    }
    impl Deref for HttpInputMemory {
        type Target = IoMemory;
        fn deref(&self) -> &Self::Target {
            match &self.0 {
                Memory::Legacy(x) => x,
                Memory::Funded { logical, .. } => logical,
            }
        }
    }
    /// Payload always retires before its original credit. No mutable DTO escape.
    pub struct HttpOwnedRequest {
        request: HttpRequest,
        memory: HttpInputMemory,
    }
    impl Deref for HttpOwnedRequest {
        type Target = HttpRequest;
        fn deref(&self) -> &HttpRequest {
            &self.request
        }
    }
    impl HttpOwnedRequest {
        pub fn preallocated(request: HttpRequest, memory: Arc<IoMemory>) -> Self {
            Self {
                request,
                memory: HttpInputMemory(Memory::Legacy(memory)),
            }
        }
        pub fn memory(&self) -> &HttpInputMemory {
            &self.memory
        }
        pub fn take_body(&mut self) -> HttpBodyOwner {
            HttpBodyOwner {
                bytes: self.request.body.take().unwrap_or_default(),
                _memory: self.memory.clone(),
            }
        }
        pub fn clear_sensitive_headers(&mut self) {
            self.request.headers.clear();
            self.request.body_media_type = None;
            self.request.idempotency_key = None;
        }
        /// Redirect-generated URL storage remains a distinct preallocated boundary.
        pub fn replace_redirect_url(&mut self, url: String) {
            self.request.url = url;
        }
        pub fn install_followup(&mut self, memory: HttpInputMemory) -> Result<(), HttpError> {
            if !self.memory.same_origin(&memory) {
                return Err(HttpError::PermissionDenied);
            }
            self.memory = memory;
            Ok(())
        }
    }
    pub struct HttpBodyOwner {
        bytes: Vec<u8>,
        _memory: HttpInputMemory,
    }
    impl AsRef<[u8]> for HttpBodyOwner {
        fn as_ref(&self) -> &[u8] {
            &self.bytes
        }
    }

    fn backing<T>(count: usize) -> Result<usize, HttpError> {
        if count == 0 || std::mem::size_of::<T>() == 0 {
            return Ok(0);
        }
        Layout::array::<T>(count)
            .map_err(|_| HttpError::RequestTooLarge)?
            .size()
            .checked_add(64)
            .ok_or(HttpError::RequestTooLarge)
    }
    fn reserve(
        original: &SessionCoreOwner,
        bytes: usize,
    ) -> Result<Option<HostMemoryReservation>, HttpError> {
        if bytes == 0 || !original.budget.profile().supports_descendants() {
            return Ok(None);
        }
        Ok(Some(
            original
                .budget
                .reserve_host_memory(u64::try_from(bytes).map_err(|_| HttpError::RequestTooLarge)?)
                .map_err(|e| HttpError::from(e.to_platform_error()))?,
        ))
    }
    fn exact<T>(
        count: usize,
        credit: &mut Option<HostMemoryReservation>,
        confirmed: &mut usize,
    ) -> Result<Vec<T>, HttpError> {
        let mut x = Vec::new();
        x.try_reserve_exact(count)
            .map_err(|_| HttpError::BudgetExhausted)?;
        if x.capacity() != count && std::mem::size_of::<T>() != 0 {
            return Err(HttpError::BudgetExhausted);
        }
        *confirmed = confirmed
            .checked_add(backing::<T>(count)?)
            .ok_or(HttpError::RequestTooLarge)?;
        if let Some(credit) = credit {
            credit
                .confirm_bytes(u64::try_from(*confirmed).map_err(|_| HttpError::RequestTooLarge)?);
        }
        Ok(x)
    }
    fn text(
        source: &mut dyn HttpRequestSource,
        field: HttpTextField,
        len: usize,
        credit: &mut Option<HostMemoryReservation>,
        confirmed: &mut usize,
    ) -> Result<String, HttpError> {
        let mut bytes = exact::<u8>(len, credit, confirmed)?;
        bytes.resize(len, 0);
        source.write_text(field, &mut bytes)?;
        String::from_utf8(bytes).map_err(|_| HttpError::InvalidRequest)
    }
    impl PreparedHttpInput {
        pub fn new(
            session: &CapabilitySession,
            source: &mut dyn HttpRequestSource,
        ) -> Result<Self, HttpError> {
            session.check_liveness()?;
            if source.header_count() > 64 {
                return Err(HttpError::RequestTooLarge);
            }
            let shared = Shared::<Credit>::reserve(&session.core.budget)?;
            let logical_shared = Shared::<IoMemory>::reserve(&session.core.budget)?;
            let length = source
                .text_len(HttpTextField::Url)?
                .ok_or(HttpError::InvalidRequest)?;
            if length > 2048 {
                return Err(HttpError::RequestTooLarge);
            }
            let mut url_credit = reserve(&session.core, backing::<u8>(length)?)?;
            let url = text(source, HttpTextField::Url, length, &mut url_credit, &mut 0)?;
            Ok(Self {
                url,
                url_credit,
                shared,
                logical_shared,
                original: session.core.clone(),
            })
        }
        pub fn url(&self) -> &str {
            &self.url
        }
        pub fn finish(
            self,
            admission: &super::super::pools::PoolAdmission,
            source: &mut dyn HttpRequestSource,
            limits: HttpInputLimits,
        ) -> Result<HttpOwnedRequest, HttpError> {
            if !(1..=64).contains(&limits.maximum_headers)
                || !(1024..=32768).contains(&limits.maximum_header_bytes)
                || limits.maximum_body_bytes > 512 * 1024
            {
                return Err(HttpError::InvalidRequest);
            }
            let count = source.header_count();
            if count > 64 || count > limits.maximum_headers {
                return Err(HttpError::RequestTooLarge);
            }
            let mut fields = [(0usize, 0usize); 64];
            let mut total = backing::<HttpHeader>(count)?;
            let mut header_bytes = 0usize;
            let mut retained = self
                .url
                .len()
                .checked_add(
                    count
                        .checked_mul(std::mem::size_of::<HttpHeader>())
                        .ok_or(HttpError::RequestTooLarge)?,
                )
                .and_then(|n| n.checked_add(1024))
                .ok_or(HttpError::RequestTooLarge)?;
            for (index, field) in fields[..count].iter_mut().enumerate() {
                let name = source
                    .text_len(HttpTextField::HeaderName(index))?
                    .ok_or(HttpError::InvalidRequest)?;
                let value = source
                    .text_len(HttpTextField::HeaderValue(index))?
                    .ok_or(HttpError::InvalidRequest)?;
                if name > 64 || value > limits.maximum_header_bytes {
                    return Err(HttpError::RequestTooLarge);
                }
                *field = (name, value);
                header_bytes = header_bytes
                    .checked_add(name)
                    .and_then(|n| n.checked_add(value))
                    .and_then(|n| n.checked_add(4))
                    .ok_or(HttpError::RequestTooLarge)?;
                retained = retained
                    .checked_add(name)
                    .and_then(|n| n.checked_add(value))
                    .ok_or(HttpError::RequestTooLarge)?;
                total = total
                    .checked_add(backing::<u8>(name)?)
                    .and_then(|n| n.checked_add(backing::<u8>(value).ok()?))
                    .ok_or(HttpError::RequestTooLarge)?;
            }
            if header_bytes > limits.maximum_header_bytes
                || retained > 2 * limits.maximum_header_bytes + 4096
            {
                return Err(HttpError::RequestTooLarge);
            }
            let media = source.text_len(HttpTextField::BodyMediaType)?;
            let key = source.text_len(HttpTextField::IdempotencyKey)?;
            for len in [media, key].into_iter().flatten() {
                if len == 0 || len > 256 {
                    return Err(HttpError::InvalidRequest);
                }
                header_bytes = header_bytes
                    .checked_add(len + 32)
                    .ok_or(HttpError::RequestTooLarge)?;
                retained = retained
                    .checked_add(len)
                    .ok_or(HttpError::RequestTooLarge)?;
                total = total
                    .checked_add(backing::<u8>(len)?)
                    .ok_or(HttpError::RequestTooLarge)?;
            }
            if header_bytes > limits.maximum_header_bytes {
                return Err(HttpError::RequestTooLarge);
            }
            let body = source.body_len();
            if body.is_some_and(|n| n > limits.maximum_body_bytes) {
                return Err(HttpError::RequestTooLarge);
            }
            if let Some(n) = body {
                total = total
                    .checked_add(backing::<u8>(n)?)
                    .ok_or(HttpError::RequestTooLarge)?;
                retained = retained.checked_add(n).ok_or(HttpError::RequestTooLarge)?;
            }
            let logical = admission.reserve_input(retained, 4096)?;
            if !logical.http_original_session(&self.original) {
                return Err(HttpError::PermissionDenied);
            }
            let mut rest_credit = reserve(&self.original, total)?;
            // Initialized owners are declared AFTER pending credit and retire first on any error.
            let mut confirmed = 0;
            let mut headers = exact::<HttpHeader>(count, &mut rest_credit, &mut confirmed)?;
            for (index, (name, value)) in fields[..count].iter().enumerate() {
                headers.push(HttpHeader {
                    name: text(
                        source,
                        HttpTextField::HeaderName(index),
                        *name,
                        &mut rest_credit,
                        &mut confirmed,
                    )?,
                    value: text(
                        source,
                        HttpTextField::HeaderValue(index),
                        *value,
                        &mut rest_credit,
                        &mut confirmed,
                    )?,
                });
            }
            let media = media
                .map(|n| {
                    text(
                        source,
                        HttpTextField::BodyMediaType,
                        n,
                        &mut rest_credit,
                        &mut confirmed,
                    )
                })
                .transpose()?;
            let key = key
                .map(|n| {
                    text(
                        source,
                        HttpTextField::IdempotencyKey,
                        n,
                        &mut rest_credit,
                        &mut confirmed,
                    )
                })
                .transpose()?;
            let body = body
                .map(|n| {
                    let mut bytes = exact::<u8>(n, &mut rest_credit, &mut confirmed)?;
                    bytes.resize(n, 0);
                    source.write_body(&mut bytes)?;
                    Ok::<_, HttpError>(bytes)
                })
                .transpose()?;
            logical.http_checkpoint()?;
            let request = HttpRequest {
                method: source.method(),
                url: self.url,
                headers,
                body,
                body_media_type: media,
                idempotency_key: key,
                timeout_millis: source.timeout_millis(),
            };
            let memory = if self.original.budget.profile().supports_descendants() {
                let origin = logical.http_origin();
                let original = self.shared.allocate(Credit {
                    _origin: origin,
                    _url: self.url_credit,
                    _rest: rest_credit,
                    original: self.original,
                });
                HttpInputMemory(Memory::Funded {
                    logical: self.logical_shared.allocate(logical),
                    original,
                })
            } else {
                HttpInputMemory(Memory::Legacy(Arc::new(logical)))
            };
            Ok(HttpOwnedRequest { request, memory })
        }
    }
}
