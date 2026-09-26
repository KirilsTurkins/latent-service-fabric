//! Immediate broker publication. No transaction or automatic uncertain replay.
use super::{pools::PoolCall, CapabilitySession};
use latent_core::{BoxFuture, PlatformError, PlatformErrorCode};

pub const EVENTS_CAPABILITY: &str = "latent:events/publisher@0.2.0";
pub struct Event {
    pub topic: String,
    pub key: Option<String>,
    pub payload: Vec<u8>,
    pub media_type: String,
    pub attributes: Vec<(String, String)>,
    pub idempotency_key: String,
}
#[derive(Debug, PartialEq, Eq)]
pub struct PublishReceipt {
    pub event_id: String,
    /// Local observation of a validated broker acknowledgement, not a broker timestamp.
    pub accepted_at_unix_millis: u64,
    pub stream_name: String,
    pub sequence: u64,
    pub duplicate: bool,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum EventError {
    InvalidTopic,
    InvalidEvent,
    PermissionDenied,
    BudgetExhausted,
    DeadlineExceeded,
    Cancelled,
    Unavailable,
    Uncertain,
}
impl From<PlatformError> for EventError {
    fn from(error: PlatformError) -> Self {
        match error.code {
            PlatformErrorCode::PermissionDenied | PlatformErrorCode::Unauthenticated => {
                Self::PermissionDenied
            }
            PlatformErrorCode::ResourceExhausted => Self::BudgetExhausted,
            PlatformErrorCode::DeadlineExceeded => Self::DeadlineExceeded,
            PlatformErrorCode::Cancelled => Self::Cancelled,
            _ => Self::Unavailable,
        }
    }
}
pub struct EventCompletion {
    pub receipt: PublishReceipt,
    /// Retain through canonical lowering and Store destruction.
    pub owner: PoolCall,
}
pub type EventFuture = BoxFuture<'static, Result<EventCompletion, EventError>>;
pub trait EventPublisher: Send + Sync {
    fn publish(&self, session: &CapabilitySession, event: Event)
        -> Result<EventFuture, EventError>;
}
