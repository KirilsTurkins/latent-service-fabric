//! Shared bounded control ownership for durable manual rollouts.
//!
//! The deployment catalog alone commits routes and progress. This owner adds
//! admission, response preflight and audit outside its publication fences.
//! Neither this worker nor its state is consulted by invocation.
#![forbid(unsafe_code)]

mod audit;
mod coordinator;
mod lease;
mod limits;
mod model;
#[cfg(all(test, unix))]
mod tests;
mod ticket;
mod worker;

pub use audit::reconcile_rollout_audit;
pub use coordinator::{RolloutCoordinator, RolloutHandle, RolloutWorker};
pub use lease::{OwnedResponse, ResponseLease};
pub use limits::CoordinatorLimits;
pub use model::{CoordinatorSnapshot, MutationPreview, MutationResult, RolloutFailure};
pub use ticket::{RolloutControl, RolloutTicket};

use latent_core::{PlatformError, PlatformErrorCode};
type Result<T> = std::result::Result<T, PlatformError>;

fn error(code: PlatformErrorCode, message: &'static str) -> PlatformError {
    PlatformError {
        code,
        message: message.into(),
        retryable: false,
        details: Vec::new(),
    }
}
fn invalid(message: &'static str) -> PlatformError {
    error(PlatformErrorCode::InvalidArgument, message)
}
fn capacity(message: &'static str) -> PlatformError {
    error(PlatformErrorCode::ResourceExhausted, message)
}
fn busy() -> PlatformError {
    capacity("rollout-coordinator-busy")
}
fn closed() -> PlatformError {
    error(PlatformErrorCode::Unavailable, "rollout-coordinator-closed")
}
fn deadline() -> PlatformError {
    error(
        PlatformErrorCode::DeadlineExceeded,
        "rollout-operation-deadline",
    )
}
fn cancelled() -> PlatformError {
    error(PlatformErrorCode::Cancelled, "rollout-operation-cancelled")
}

fn bounded(failure: PlatformError) -> PlatformError {
    let code = failure.code;
    let message = match code {
        PlatformErrorCode::StateConflict => "rollout-state-conflict",
        PlatformErrorCode::PermissionDenied => "rollout-operation-denied",
        PlatformErrorCode::ResourceExhausted => "rollout-resource-limit",
        PlatformErrorCode::NotFound => "rollout-not-found",
        PlatformErrorCode::AlreadyExists => "rollout-already-exists",
        PlatformErrorCode::IncompatibleContract => "rollout-incompatible",
        PlatformErrorCode::CorruptArtifact => "rollout-corrupt-content",
        PlatformErrorCode::DeadlineExceeded => "rollout-operation-deadline",
        PlatformErrorCode::Cancelled => "rollout-operation-cancelled",
        PlatformErrorCode::InvalidArgument => "rollout-invalid-request",
        _ => "rollout-operation-unavailable",
    };
    drop(failure);
    error(code, message)
}
