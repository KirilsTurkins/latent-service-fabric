use latent_core::{PlatformError, PlatformErrorCode};
use std::fmt;

pub type SignatureResult<T> = Result<T, SignatureError>;

/// Bounded failure taxonomy. Diagnostics never retain untrusted input or keys.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SignatureFailure {
    InvalidLimits,
    ResourceLimit,
    MalformedEnvelope,
    UnsupportedProfile,
    InvalidSubject,
    SubjectMismatch,
    IntegrityMismatch,
    InvalidValidity,
    InvalidKey,
    UnapprovedKey,
    InvalidSignature,
    UntrustedPublisher,
    UntrustedBuilder,
    SourceDisallowed,
    PredicateDisallowed,
    MalformedProvenance,
    InvalidPolicy,
    InvalidRevocations,
    TrustExpired,
    KeyExpired,
    SignatureExpired,
    Revoked,
    ClockRegression,
    TrustConflict,
    StaleProof,
    Internal,
}

impl SignatureFailure {
    #[must_use]
    pub const fn code(self) -> &'static str {
        match self {
            Self::InvalidLimits => "signature-invalid-limits",
            Self::ResourceLimit => "signature-resource-limit",
            Self::MalformedEnvelope => "signature-malformed-envelope",
            Self::UnsupportedProfile => "signature-unsupported-profile",
            Self::InvalidSubject => "signature-invalid-subject",
            Self::SubjectMismatch => "signature-subject-mismatch",
            Self::IntegrityMismatch => "signature-integrity-mismatch",
            Self::InvalidValidity => "signature-invalid-validity",
            Self::InvalidKey => "signature-invalid-key",
            Self::UnapprovedKey => "signature-unapproved-key",
            Self::InvalidSignature => "signature-invalid",
            Self::UntrustedPublisher => "signature-untrusted-publisher",
            Self::UntrustedBuilder => "provenance-untrusted-builder",
            Self::SourceDisallowed => "provenance-source-disallowed",
            Self::PredicateDisallowed => "provenance-predicate-disallowed",
            Self::MalformedProvenance => "provenance-malformed",
            Self::InvalidPolicy => "signature-invalid-policy",
            Self::InvalidRevocations => "signature-invalid-revocations",
            Self::TrustExpired => "signature-trust-expired",
            Self::KeyExpired => "signature-key-expired",
            Self::SignatureExpired => "signature-expired",
            Self::Revoked => "signature-revoked",
            Self::ClockRegression => "signature-clock-regression",
            Self::TrustConflict => "signature-trust-conflict",
            Self::StaleProof => "signature-stale-proof",
            Self::Internal => "signature-internal",
        }
    }

    const fn platform_code(self) -> PlatformErrorCode {
        match self {
            Self::ResourceLimit => PlatformErrorCode::ResourceExhausted,
            Self::IntegrityMismatch => PlatformErrorCode::CorruptArtifact,
            Self::UnapprovedKey
            | Self::InvalidSignature
            | Self::UntrustedPublisher
            | Self::UntrustedBuilder
            | Self::SourceDisallowed
            | Self::PredicateDisallowed
            | Self::TrustExpired
            | Self::KeyExpired
            | Self::SignatureExpired
            | Self::Revoked => PlatformErrorCode::PermissionDenied,
            Self::ClockRegression | Self::TrustConflict | Self::StaleProof => {
                PlatformErrorCode::StateConflict
            }
            Self::Internal => PlatformErrorCode::Internal,
            _ => PlatformErrorCode::InvalidArgument,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct SignatureError {
    reason: SignatureFailure,
}

impl SignatureError {
    pub(crate) const fn new(reason: SignatureFailure) -> Self {
        Self { reason }
    }

    #[must_use]
    pub const fn reason(self) -> SignatureFailure {
        self.reason
    }
}

impl From<SignatureFailure> for SignatureError {
    fn from(reason: SignatureFailure) -> Self {
        Self::new(reason)
    }
}

impl fmt::Display for SignatureError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.reason.code())
    }
}
impl std::error::Error for SignatureError {}

impl From<SignatureError> for PlatformError {
    fn from(error: SignatureError) -> Self {
        Self {
            code: error.reason.platform_code(),
            message: error.reason.code().to_owned(),
            retryable: false,
            details: Vec::new(),
        }
    }
}
