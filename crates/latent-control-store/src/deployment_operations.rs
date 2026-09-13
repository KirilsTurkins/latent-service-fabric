//! Bounded managed deployment commands and immutable committed operation history.
pub(crate) mod budget;
pub(crate) mod codec;
mod model;
pub(crate) mod validation;
pub use crate::deployments::operations::PreparedDeploymentOperation;
pub use budget::{DeploymentOperationRead, DeploymentReadLease};
use latent_core::{PlatformError, PlatformErrorCode};
pub use model::*;
pub(crate) type Result<T> = std::result::Result<T, PlatformError>;
pub const MAX_REQUEST_BYTES: usize = 64 * 1024;
pub const MAX_RECEIPT_BYTES: usize = 4096;
/// Aggregate allowance for bounded request normalization, hashing and audit encoding.
pub const MAX_OPERATION_SCRATCH_BYTES: usize = 512 * 1024;
pub(crate) fn error(code: PlatformErrorCode, message: &'static str) -> PlatformError {
    PlatformError {
        code,
        message: message.into(),
        retryable: false,
        details: Vec::new(),
    }
}
pub(crate) fn invalid() -> PlatformError {
    error(
        PlatformErrorCode::InvalidArgument,
        "invalid-deployment-operation",
    )
}
pub(crate) fn capacity() -> PlatformError {
    error(
        PlatformErrorCode::ResourceExhausted,
        "deployment-operation-capacity",
    )
}
pub(crate) fn corrupt() -> PlatformError {
    error(
        PlatformErrorCode::CorruptArtifact,
        "invalid-deployment-operation-history",
    )
}
pub(crate) fn conflict() -> PlatformError {
    error(
        PlatformErrorCode::StateConflict,
        "deployment-operation-conflict",
    )
}
pub(crate) fn unsupported() -> PlatformError {
    error(
        PlatformErrorCode::IncompatibleContract,
        "managed-deployment-operations-unsupported",
    )
}
