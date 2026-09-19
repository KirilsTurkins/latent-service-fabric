use super::{
    bounded::{BoundedList, BoundedText, Optional},
    cache::{CacheRequest, Pending},
    codec,
    model::{Profile, ResponseData},
    pool::Lease,
    Cancellation, HeaderView, HttpError, Method, VALUE_MEDIA_TYPE,
};
use latent_core::PlatformErrorCode;
use std::sync::Arc;

#[derive(Clone, Copy)]
pub enum Outcome<'a> {
    Returned {
        bytes: &'a [u8],
        media_type: &'a str,
    },
    /// The HTTP application contract returns a response, not result<T, E>.
    DeclaredError,
    Platform(PlatformErrorCode),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DeliveryCause {
    Application,
    InvalidGuestResponse,
    Platform(PlatformErrorCode),
}

/// The payload and headers stay owned until actual delivery or drop. There is no
/// conversion into an unguarded response body or freely cloned response object.
pub struct Delivery {
    pub(super) response: ResponseData,
    cause: DeliveryCause,
    method: Method,
    headers_written: bool,
    written: usize,
    pending: Option<Pending>,
    pub(super) cache_age: Option<String>,
    // Payload/header allocations must be freed before their capacity is refunded.
    lease: Arc<Lease>,
}
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Delivered {
    pub status: u16,
    pub body_bytes: usize,
    pub cause: DeliveryCause,
}

impl Delivery {
    pub(super) fn new(
        lease: Arc<Lease>,
        method: Method,
        outcome: Outcome<'_>,
    ) -> Result<Self, HttpError> {
        let (response, cause) = match outcome {
            Outcome::Returned { bytes, media_type } if media_type == VALUE_MEDIA_TYPE => {
                match codec::response(bytes, method) {
                    Ok(response) => (response, DeliveryCause::Application),
                    Err(_) => (failure(502, method), DeliveryCause::InvalidGuestResponse),
                }
            }
            Outcome::Platform(PlatformErrorCode::Cancelled) => return Err(HttpError::Disconnected),
            Outcome::Platform(code) => (
                failure(platform_status(code), method),
                DeliveryCause::Platform(code),
            ),
            Outcome::Returned { .. } | Outcome::DeclaredError => {
                (failure(502, method), DeliveryCause::InvalidGuestResponse)
            }
        };
        lease.check()?;
        Ok(Self {
            lease,
            response,
            cause,
            method,
            headers_written: false,
            written: 0,
            pending: None,
            cache_age: None,
        })
    }
    pub(super) fn stage(&mut self, request: CacheRequest, wire: &[u8]) {
        self.pending = request.stage(self, wire);
    }
    #[must_use]
    pub fn status(&self) -> u16 {
        self.response.status
    }
    #[must_use]
    pub fn cause(&self) -> DeliveryCause {
        self.cause
    }
    pub fn enforce_browser_profile(&mut self, scheme: super::Scheme) -> Result<(), HttpError> {
        self.lease.check()?;
        if self.headers_written || self.written != 0 {
            return Err(HttpError::IncompleteDelivery);
        }
        if !super::browser::validate_response(&self.response, scheme) {
            self.pending = None;
            self.cache_age = None;
            self.response = failure(502, self.method);
            self.cause = DeliveryCause::InvalidGuestResponse;
        }
        Ok(())
    }
    /// Downstream caches have no access to the operator's complete key or
    /// eligibility fence. Keep browser/proxy storage disabled even on local hits.
    pub fn headers(&self) -> impl Iterator<Item = HeaderView<'_>> {
        self.response
            .headers
            .0
            .iter()
            .filter(|header| !matches!(header.name.0.as_str(), "cache-control" | "age"))
            .map(super::model::Header::view)
            .chain(std::iter::once(HeaderView {
                name: "cache-control",
                value: b"no-store",
            }))
            .chain(self.cache_age.as_ref().map(|age| HeaderView {
                name: "age",
                value: age.as_bytes(),
            }))
    }
    #[must_use]
    pub fn media_type(&self) -> Option<&str> {
        self.response.media_type.as_ref().map(|v| v.0.as_str())
    }
    /// The adapter supplies this framing itself; guest headers cannot override it.
    #[must_use]
    pub fn content_length(&self) -> Option<u64> {
        if self.response.status == 204 {
            return None;
        }
        if self.response.status == 205 {
            return Some(0);
        }
        if self.method == Method::Head || self.response.status == 304 {
            return self.response.representation_length.as_ref().map(|v| v.0);
        }
        Some(self.response.body.0.len() as u64)
    }
    #[must_use]
    pub fn cancellation(&self) -> Cancellation {
        Cancellation(self.lease.clone())
    }
    /// Called only after the bounded transport has completed its header write.
    pub fn mark_headers_written(&mut self) -> Result<(), HttpError> {
        self.lease.check()?;
        if self.headers_written {
            return Err(HttpError::IncompleteDelivery);
        }
        self.headers_written = true;
        Ok(())
    }
    pub fn remaining_body(&self) -> Result<&[u8], HttpError> {
        self.lease.check()?;
        Ok(&self.response.body.0[self.written..])
    }
    /// Advance only by the successful byte count returned by a transport write.
    pub fn advance(&mut self, written: usize) -> Result<(), HttpError> {
        self.lease.check()?;
        if !self.headers_written || written > self.response.body.0.len() - self.written {
            return Err(HttpError::IncompleteDelivery);
        }
        self.written += written;
        Ok(())
    }
    /// Records completed local writes, not peer receipt or browser processing.
    pub fn finish(mut self) -> Result<Delivered, HttpError> {
        self.lease.check()?;
        if !self.headers_written || self.written != self.response.body.0.len() {
            return Err(HttpError::IncompleteDelivery);
        }
        if let Some(pending) = self.pending.take() {
            pending.publish();
        }
        Ok(Delivered {
            status: self.response.status,
            body_bytes: self.written,
            cause: self.cause,
        })
    }
}

fn platform_status(code: PlatformErrorCode) -> u16 {
    match code {
        PlatformErrorCode::Unauthenticated => 401,
        PlatformErrorCode::PermissionDenied => 403,
        PlatformErrorCode::InvalidArgument => 400,
        PlatformErrorCode::NotFound => 404,
        PlatformErrorCode::AlreadyExists | PlatformErrorCode::StateConflict => 409,
        PlatformErrorCode::DeadlineExceeded => 504,
        PlatformErrorCode::Unavailable
        | PlatformErrorCode::ResourceExhausted
        | PlatformErrorCode::RouteUnavailable
        | PlatformErrorCode::AdmissionRejected => 503,
        PlatformErrorCode::GuestTrap
        | PlatformErrorCode::CorruptArtifact
        | PlatformErrorCode::IncompatibleContract
        | PlatformErrorCode::DependencyFailed => 502,
        _ => 500,
    }
}
fn failure(status: u16, method: Method) -> ResponseData {
    let text: &[u8] = match status {
        400 => b"Bad request\n",
        401 => b"Authentication required\n",
        403 => b"Forbidden\n",
        404 => b"Not found\n",
        409 => b"Conflict\n",
        502 => b"Bad gateway\n",
        503 => b"Unavailable\n",
        504 => b"Gateway timeout\n",
        _ => b"Internal failure\n",
    };
    ResponseData {
        profile: Profile::BufferedV1,
        status,
        headers: BoundedList(Vec::new()),
        media_type: Optional::Some(BoundedText("text/plain; charset=utf-8".into())),
        representation_length: Optional::None(()),
        body: super::body::Body(if method == Method::Head {
            Vec::new()
        } else {
            text.to_vec()
        }),
    }
}
