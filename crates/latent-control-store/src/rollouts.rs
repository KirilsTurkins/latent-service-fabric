//! Bounded manual rollout commands and immutable historical results.
mod canary;
pub(crate) mod codec;
mod model;
pub(crate) mod validation;
pub use crate::deployments::rollouts::canary::RolloutCanaryCohort;
pub use crate::deployments::rollouts::PreparedRolloutMutation;
pub use canary::{RolloutCanaryCounters, RolloutCanaryDecision, RolloutCanaryPolicy};
use latent_core::{PlatformError, PlatformErrorCode};
pub use model::*;
pub(crate) type Result<T> = std::result::Result<T, PlatformError>;
pub const MAX_REQUEST_BYTES: usize = 64 * 1024;
pub const MAX_ROW_BYTES: usize = 128 * 1024;
pub const MAX_RECEIPT_BYTES: usize = 4096;
pub const MAX_PAGE_BYTES: usize = 64 * 1024;
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
        "invalid-rollout-request",
    )
}
pub(crate) fn capacity() -> PlatformError {
    error(PlatformErrorCode::ResourceExhausted, "rollout-capacity")
}
pub(crate) fn corrupt() -> PlatformError {
    error(
        PlatformErrorCode::CorruptArtifact,
        "invalid-persisted-rollout",
    )
}
pub(crate) fn conflict() -> PlatformError {
    error(
        PlatformErrorCode::StateConflict,
        "rollout-generation-conflict",
    )
}
