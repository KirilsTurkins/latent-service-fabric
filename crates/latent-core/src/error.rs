//! Fabric-level failures, separate from component domain errors.

use crate::Metadata;

/// Stable platform-level error classification.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
#[non_exhaustive]
pub enum PlatformErrorCode {
    Unavailable,
    DeadlineExceeded,
    Cancelled,
    ResourceExhausted,
    PermissionDenied,
    Unauthenticated,
    InvalidArgument,
    NotFound,
    AlreadyExists,
    IncompatibleContract,
    StateConflict,
    DependencyFailed,
    GuestTrap,
    CorruptArtifact,
    RouteUnavailable,
    AdmissionRejected,
    Internal,
}

/// One structured detail attached to a platform error.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ErrorDetail {
    pub kind: String,
    pub fields: Metadata,
}

/// Error returned by LSF infrastructure rather than by component business logic.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PlatformError {
    pub code: PlatformErrorCode,
    pub message: String,
    pub retryable: bool,
    pub details: Vec<ErrorDetail>,
}
