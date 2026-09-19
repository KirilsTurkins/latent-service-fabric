//! The buffered-v1 inbound HTTP contract. No listener or background worker is created.
//!
//! The shared pool owns every exchange through collection, invocation and delivery.
//! Application authority comes from the existing host context, not the HTTP payload.

mod body;
mod bounded;
pub mod cache;
mod codec;
mod context;
mod delivery;
mod headers;
mod lifecycle;
mod model;
mod pool;
mod target;

pub use context::TrustedContext;
pub use delivery::{Delivered, Delivery, DeliveryCause, Outcome};
pub use lifecycle::{Collector, Invocation, Request};
pub use model::{HeaderView, HttpVersion, Method, RawHead, Scheme};
pub use pool::{Cancellation, HttpPool, PoolSnapshot};
pub use target::CanonicalTarget;

pub const CONTRACT: &str = "latent:web/application@0.1.0";
pub const FUNCTION: &str = "handle";
pub const PROFILE: &str = "buffered-v1";
pub const VALUE_MEDIA_TYPE: &str = "application/vnd.latent.wit-values.v1+json";
pub const MAX_REQUEST_BODY: usize = 64 * 1024;
pub const MAX_RESPONSE_BODY: usize = 256 * 1024;
pub const MAX_HEADERS: usize = 64;
pub const MAX_HEADER_BYTES: usize = 16 * 1024;
pub const MAX_TARGET_BYTES: usize = 8192;
pub const MAX_CONTEXT_BYTES: usize = 8192;
pub const MAX_WIRE_BYTES: usize = 2 * 1024 * 1024;
pub const MAX_JSON_NODES: usize = 32_768;
/// Conservative retained and temporary codec capacity, reserved before allocation.
/// Guest/runtime, socket and TLS allocations have their own owners and limits.
pub const EXCHANGE_RESERVATION_BYTES: usize = 4 * 1024 * 1024;

/// Static, non-reflective mapping failures. Never includes credentials or payloads.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum HttpError {
    InvalidLimits,
    Overloaded,
    AllocationFailed,
    InvalidTarget,
    UnsupportedMethod,
    InvalidHeaders,
    HeadersTooLarge,
    InvalidFraming,
    BodyTooLarge,
    InvalidContext,
    InvalidResponse,
    Disconnected,
    DeadlineExceeded,
    IncompleteDelivery,
}

impl HttpError {
    /// A transport can send this fixed status only while it still owns writable
    /// response capacity. A disconnected/expired exchange must be closed.
    #[must_use]
    pub const fn status(self) -> Option<u16> {
        match self {
            Self::Overloaded | Self::AllocationFailed => Some(503),
            Self::UnsupportedMethod => Some(405),
            Self::HeadersTooLarge => Some(431),
            Self::BodyTooLarge => Some(413),
            Self::InvalidResponse => Some(502),
            Self::InvalidLimits | Self::InvalidContext => Some(500),
            Self::Disconnected | Self::DeadlineExceeded | Self::IncompleteDelivery => None,
            Self::InvalidTarget | Self::InvalidHeaders | Self::InvalidFraming => Some(400),
        }
    }
}

impl std::fmt::Display for HttpError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "HTTP mapping failed: {self:?}")
    }
}
impl std::error::Error for HttpError {}
