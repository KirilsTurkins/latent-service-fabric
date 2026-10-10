use super::{
    bounded::Optional,
    cache::{CacheHit, CacheRequest},
    codec, headers,
    model::{Profile, RequestData},
    pool::Lease,
    Cancellation, CanonicalTarget, Delivery, HttpError, HttpVersion, Method, Outcome, RawHead,
    TrustedContext, MAX_REQUEST_BODY,
};
use latent_core::IncomingDeadline;
use std::sync::Arc;

/// Owns the bounded collection phase. Dropping a collector retires its actual
/// buffers; disconnect handles and other surviving owners keep the reservation.
pub struct Collector {
    target: CanonicalTarget,
    headers: headers::RequestHeaders,
    method: Method,
    version: HttpVersion,
    body: Vec<u8>,
    failed: bool,
    cache_sensitive: bool,
    // Fields drop in declaration order: free all retained data before refunding.
    lease: Arc<Lease>,
}
impl Collector {
    pub(super) fn new(head: RawHead<'_>, lease: Arc<Lease>) -> Result<Self, HttpError> {
        let method = Method::parse(head.method)?;
        let headers = headers::request(&head, method)?;
        let target = CanonicalTarget::parse(head.scheme, head.authority, head.target)?;
        // Record credential presence before application-header filtering. Never
        // retain credentials themselves or permit a stripped token to enable a hit.
        let cache_sensitive = head.headers.iter().any(|header| {
            ["authorization", "proxy-authorization", "cookie"]
                .iter()
                .any(|name| header.name.eq_ignore_ascii_case(name))
        });
        Ok(Self {
            lease,
            target,
            headers,
            method,
            version: head.version,
            body: Vec::new(),
            failed: false,
            cache_sensitive,
        })
    }
    #[must_use]
    pub fn target(&self) -> &CanonicalTarget {
        &self.target
    }
    #[must_use]
    pub fn cancellation(&self) -> Cancellation {
        Cancellation(self.lease.clone())
    }
    pub fn append(&mut self, bytes: &[u8]) -> Result<(), HttpError> {
        if self.failed {
            return Err(HttpError::InvalidFraming);
        }
        let result = self.append_checked(bytes);
        self.failed = result.is_err();
        result
    }
    fn append_checked(&mut self, bytes: &[u8]) -> Result<(), HttpError> {
        self.lease.check()?;
        let length = self
            .body
            .len()
            .checked_add(bytes.len())
            .ok_or(HttpError::BodyTooLarge)?;
        if length > MAX_REQUEST_BODY {
            return Err(HttpError::BodyTooLarge);
        }
        if (matches!(self.method, Method::Get | Method::Head) && length != 0)
            || (self.version == HttpVersion::Http11 && self.headers.length.is_none() && length != 0)
            || self
                .headers
                .length
                .is_some_and(|declared| length > declared)
        {
            return Err(HttpError::InvalidFraming);
        }
        if length > self.body.capacity() {
            let next = self
                .body
                .capacity()
                .saturating_mul(2)
                .max(length)
                .min(MAX_REQUEST_BODY);
            self.body
                .try_reserve_exact(next - self.body.len())
                .map_err(|_| HttpError::AllocationFailed)?;
        }
        self.body.extend_from_slice(bytes);
        Ok(())
    }
    pub fn finish(self, context: TrustedContext) -> Result<Request, HttpError> {
        self.lease.check()?;
        if self.failed {
            return Err(HttpError::InvalidFraming);
        }
        if self
            .headers
            .length
            .is_some_and(|length| length != self.body.len())
        {
            return Err(HttpError::InvalidFraming);
        }
        Ok(Request {
            lease: self.lease,
            context,
            cache_sensitive: self.cache_sensitive,
            data: RequestData {
                profile: Profile::BufferedV1,
                method: self.method,
                scheme: self.target.scheme,
                authority: self.target.authority,
                path: self.target.path,
                query: Optional::from_option(self.target.query),
                headers: self.headers.fields,
                media_type: Optional::from_option(self.headers.media),
                body: super::body::Body(self.body),
            },
        })
    }
}

pub struct Request {
    context: TrustedContext,
    pub(super) data: RequestData,
    pub(super) cache_sensitive: bool,
    lease: Arc<Lease>,
}
impl Request {
    #[must_use]
    pub fn context(&self) -> &TrustedContext {
        &self.context
    }
    #[must_use]
    pub fn body(&self) -> &[u8] {
        &self.data.body.0
    }
    /// Consumes the only request owner. No uncharged raw Vec can be extracted.
    pub fn into_invocation(self) -> Result<Invocation, HttpError> {
        self.lease.check()?;
        let bytes = codec::encode(&self.data)?;
        Ok(Invocation {
            lease: self.lease,
            context: self.context,
            method: self.data.method,
            bytes,
        })
    }
}

/// The adapter retains this owner until the normal activation has retired its
/// input. A bounded copy into `ActivationRequest` has the activation owner's own
/// charge; never detach a queued/running activation when this owner is cancelled.
pub struct Invocation {
    context: TrustedContext,
    pub(super) method: Method,
    bytes: Vec<u8>,
    pub(super) lease: Arc<Lease>,
}
impl Invocation {
    #[must_use]
    pub fn input(&self) -> &[u8] {
        &self.bytes
    }
    #[must_use]
    pub fn context(&self) -> &TrustedContext {
        &self.context
    }
    #[must_use]
    pub fn deadline(&self) -> IncomingDeadline {
        self.lease.deadline
    }
    #[must_use]
    pub fn cancellation(&self) -> Cancellation {
        Cancellation(self.lease.clone())
    }
    /// A validated application outcome becomes an owned delivery, never a claim
    /// that a socket write or browser consumption has already succeeded.
    pub fn complete(self, outcome: Outcome<'_>) -> Result<Delivery, HttpError> {
        self.complete_cached(outcome, None)
    }
    /// The exact validated outcome is staged, but cannot be published until
    /// successful local transport completion. A failed fill never fails delivery.
    pub fn complete_cached(
        self,
        outcome: Outcome<'_>,
        cache: Option<CacheRequest>,
    ) -> Result<Delivery, HttpError> {
        self.lease.check()?;
        let mut delivery = Delivery::new(self.lease.clone(), self.method, outcome)?;
        if let (Some(request), Outcome::Returned { bytes, .. }) = (cache, outcome) {
            delivery.stage(request, bytes);
        }
        Ok(delivery)
    }
    /// A hit still becomes a bounded, cancellable transport delivery. The cached
    /// read remains charged until decoding/copying into this exchange completes.
    pub fn complete_cache_hit(self, hit: CacheHit) -> Result<Delivery, HttpError> {
        let mut delivery = self.complete(Outcome::Returned {
            bytes: hit.wire(),
            media_type: super::VALUE_MEDIA_TYPE,
        })?;
        delivery.cache_age = Some(hit.age().to_string());
        Ok(delivery)
    }
}
