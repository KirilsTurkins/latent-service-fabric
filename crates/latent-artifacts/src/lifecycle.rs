//! Bounded durable release lifecycle, separate from optional signing authority.
mod capability;
mod codec;
mod model;
mod store;
pub use capability::{
    LifecycleAuthorityHandle, LifecycleEligibility, ReleaseUseEligibility, ReleaseUseRecheck,
};
pub use model::*;
pub(crate) use store::{
    LifecycleEvidence, LifecycleFence, LifecycleIdentity, LifecyclePrepared, LifecycleStore,
};

use latent_core::{PlatformError, PlatformErrorCode};
fn error(code: PlatformErrorCode, reason: &'static str) -> PlatformError {
    PlatformError {
        code,
        message: reason.to_owned(),
        retryable: false,
        details: Vec::new(),
    }
}
fn invalid() -> PlatformError {
    error(
        PlatformErrorCode::InvalidArgument,
        "invalid-release-lifecycle-input",
    )
}
fn corrupt() -> PlatformError {
    error(
        PlatformErrorCode::CorruptArtifact,
        "invalid-release-lifecycle-storage",
    )
}
fn unavailable() -> PlatformError {
    error(
        PlatformErrorCode::Unavailable,
        "release-lifecycle-unavailable",
    )
}
fn lock_error<T>(failure: std::sync::TryLockError<T>) -> PlatformError {
    match failure {
        std::sync::TryLockError::WouldBlock => PlatformError {
            code: PlatformErrorCode::Unavailable,
            message: "release-lifecycle-busy".to_owned(),
            retryable: true,
            details: Vec::new(),
        },
        std::sync::TryLockError::Poisoned(_) => unavailable(),
    }
}
fn exhausted() -> PlatformError {
    error(
        PlatformErrorCode::ResourceExhausted,
        "release-lifecycle-limit",
    )
}
fn conflict() -> PlatformError {
    error(
        PlatformErrorCode::StateConflict,
        "release-lifecycle-generation-conflict",
    )
}
