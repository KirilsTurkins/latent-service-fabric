//! Bounded local durability. Records describe decisions; they confer no authority.
mod codec;
mod limits;
mod model;
mod store;
mod ticket;
mod worker;
use latent_core::{PlatformError, PlatformErrorCode};
pub use limits::*;
pub use model::*;
pub use ticket::{AuditAppendTicket, AuditBeginTicket, AuditQueryTicket};
pub use worker::*;
type Result<T> = std::result::Result<T, PlatformError>;
fn error(code: PlatformErrorCode, reason: &'static str) -> PlatformError {
    PlatformError {
        code,
        message: reason.into(),
        retryable: false,
        details: Vec::new(),
    }
}
fn invalid() -> PlatformError {
    error(PlatformErrorCode::InvalidArgument, "audit-invalid")
}
fn capacity() -> PlatformError {
    error(PlatformErrorCode::ResourceExhausted, "audit-capacity")
}
fn corrupt() -> PlatformError {
    error(PlatformErrorCode::CorruptArtifact, "audit-corrupt")
}
fn unavailable() -> PlatformError {
    error(PlatformErrorCode::Unavailable, "audit-unavailable")
}
fn closed() -> PlatformError {
    error(PlatformErrorCode::Unavailable, "audit-closed")
}

#[cfg(test)]
mod tests;
