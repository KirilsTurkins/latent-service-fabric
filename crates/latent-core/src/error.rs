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

/// A declared component/domain outcome.
///
/// This is intentionally not a [`PlatformError`].  The platform completed the
/// invocation successfully enough to observe a component-declared failure and
/// must retain its final resource consumption separately.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DeclaredError {
    pub code: String,
    pub message: String,
    pub payload: Vec<u8>,
    pub media_type: String,
    pub metadata: Metadata,
}

/// Error returned by LSF infrastructure rather than by component business logic.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PlatformError {
    pub code: PlatformErrorCode,
    pub message: String,
    pub retryable: bool,
    pub details: Vec<ErrorDetail>,
}
