//! Closed HTTP trigger configuration, exact target pins and bounded control receipts.
pub(crate) mod codec;
pub(crate) mod definition;
mod model;
pub use crate::deployment_operations::{
    DeploymentOperationRead as TriggerRead, DeploymentReadLease as TriggerReadLease,
};
pub use crate::deployments::http::{AcceptedHttpRoute, PreparedTriggerOperation};
use latent_core::{PlatformError, PlatformErrorCode};
pub use model::*;
pub const MAX_IDENTIFIER_BYTES: usize = 128;
pub const MAX_DEFINITION_BYTES: usize = 16 * 1024;
pub const MAX_RECEIPT_BYTES: usize = 4096;
pub const MAX_RECORDS: usize = 256;
pub const MAX_TABLE_BYTES: usize = 2 * 1024 * 1024;
pub const MAX_PAGE_SIZE: u32 = 32;
pub const MAX_PAGE_BYTES: usize = 128 * 1024;
fn error(code: PlatformErrorCode, message: &'static str) -> PlatformError {
    PlatformError {
        code,
        message: message.into(),
        retryable: false,
        details: Vec::new(),
    }
}
pub(crate) fn invalid() -> PlatformError {
    error(PlatformErrorCode::InvalidArgument, "invalid-http-trigger")
}
pub(crate) fn capacity() -> PlatformError {
    error(
        PlatformErrorCode::ResourceExhausted,
        "http-trigger-capacity",
    )
}
pub(crate) fn conflict() -> PlatformError {
    error(PlatformErrorCode::StateConflict, "http-trigger-conflict")
}
pub(crate) fn corrupt() -> PlatformError {
    error(
        PlatformErrorCode::CorruptArtifact,
        "invalid-http-trigger-state",
    )
}

#[cfg(test)]
mod tests;
