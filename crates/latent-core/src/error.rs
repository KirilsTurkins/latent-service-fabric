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

impl PlatformErrorCode {
    /// Returns the stable lower-kebab-case code used by wire protocols and SDKs.
    #[must_use]
    pub const fn wire_code(self) -> &'static str {
        match self {
            Self::Unavailable => "unavailable",
            Self::DeadlineExceeded => "deadline-exceeded",
            Self::Cancelled => "cancelled",
            Self::ResourceExhausted => "resource-exhausted",
            Self::PermissionDenied => "permission-denied",
            Self::Unauthenticated => "unauthenticated",
            Self::InvalidArgument => "invalid-argument",
            Self::NotFound => "not-found",
            Self::AlreadyExists => "already-exists",
            Self::IncompatibleContract => "incompatible-contract",
            Self::StateConflict => "state-conflict",
            Self::DependencyFailed => "dependency-failed",
            Self::GuestTrap => "guest-trap",
            Self::CorruptArtifact => "corrupt-artifact",
            Self::RouteUnavailable => "route-unavailable",
            Self::AdmissionRejected => "admission-rejected",
            Self::Internal => "internal",
        }
    }

    /// Parses one stable wire code without coercing unknown future values.
    #[must_use]
    pub fn from_wire_code(code: &str) -> Option<Self> {
        match code {
            "unavailable" => Some(Self::Unavailable),
            "deadline-exceeded" => Some(Self::DeadlineExceeded),
            "cancelled" => Some(Self::Cancelled),
            "resource-exhausted" => Some(Self::ResourceExhausted),
            "permission-denied" => Some(Self::PermissionDenied),
            "unauthenticated" => Some(Self::Unauthenticated),
            "invalid-argument" => Some(Self::InvalidArgument),
            "not-found" => Some(Self::NotFound),
            "already-exists" => Some(Self::AlreadyExists),
            "incompatible-contract" => Some(Self::IncompatibleContract),
            "state-conflict" => Some(Self::StateConflict),
            "dependency-failed" => Some(Self::DependencyFailed),
            "guest-trap" => Some(Self::GuestTrap),
            "corrupt-artifact" => Some(Self::CorruptArtifact),
            "route-unavailable" => Some(Self::RouteUnavailable),
            "admission-rejected" => Some(Self::AdmissionRejected),
            "internal" => Some(Self::Internal),
            _ => None,
        }
    }
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
