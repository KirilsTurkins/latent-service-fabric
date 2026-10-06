use latent_commit::atomic::AtomicError;
use latent_core::{PlatformError, PlatformErrorCode};
use latent_executor::transaction::StateFailure;
use latent_state::protected_store::ProtectedStoreError;

pub(super) fn fixed(code: PlatformErrorCode, message: &'static str) -> PlatformError {
    PlatformError {
        code,
        message: message.into(),
        retryable: false,
        details: vec![],
    }
}
pub(super) fn atomic(error: AtomicError) -> PlatformError {
    match error {
        AtomicError::Invalid => fixed(
            PlatformErrorCode::InvalidArgument,
            "invalid-command-envelope",
        ),
        AtomicError::Limit => fixed(
            PlatformErrorCode::ResourceExhausted,
            "command-capacity-exhausted",
        ),
        AtomicError::Conflict => fixed(PlatformErrorCode::StateConflict, "command-conflict"),
        AtomicError::PermissionDenied => fixed(
            PlatformErrorCode::PermissionDenied,
            "command-permission-denied",
        ),
        AtomicError::Expired => fixed(
            PlatformErrorCode::Unavailable,
            "original-command-result-expired",
        ),
        AtomicError::Corrupt | AtomicError::UnsupportedFormat => fixed(
            PlatformErrorCode::CorruptArtifact,
            "command-history-not-readable",
        ),
        AtomicError::Unavailable | AtomicError::RecoveryRequired => fixed(
            PlatformErrorCode::Unavailable,
            "original-command-recovery-required",
        ),
        AtomicError::InProgress => fixed(
            PlatformErrorCode::Unavailable,
            "original-command-in-progress",
        ),
        AtomicError::NotFound => fixed(PlatformErrorCode::NotFound, "original-command-not-found"),
    }
}
pub(super) fn protected(_: ProtectedStoreError) -> PlatformError {
    fixed(
        PlatformErrorCode::Unavailable,
        "protected-command-owner-unavailable",
    )
}
pub(super) fn store(error: latent_state::embedded::StoreError) -> PlatformError {
    use latent_state::embedded::StoreError;
    atomic(match error {
        StoreError::Invalid => AtomicError::Invalid,
        StoreError::Capacity => AtomicError::Limit,
        StoreError::Conflict => AtomicError::Conflict,
        StoreError::Corrupt => AtomicError::Corrupt,
        StoreError::UnsupportedFormat => AtomicError::UnsupportedFormat,
        StoreError::Unavailable | StoreError::CommitUncertain | StoreError::SnapshotExpired => {
            AtomicError::RecoveryRequired
        }
    })
}
pub(super) fn state(error: StateFailure) -> PlatformError {
    match error {
        StateFailure::PermissionDenied => atomic(AtomicError::PermissionDenied),
        StateFailure::Conflict | StateFailure::StaleInput => atomic(AtomicError::Conflict),
        StateFailure::ReadBudgetExhausted | StateFailure::WriteBudgetExhausted => {
            atomic(AtomicError::Limit)
        }
        StateFailure::InvalidKey
        | StateFailure::InvalidValue
        | StateFailure::InvalidLimit
        | StateFailure::InvalidCursor => atomic(AtomicError::Invalid),
        StateFailure::Cancelled => fixed(PlatformErrorCode::Cancelled, "original-command-stopped"),
        _ => atomic(AtomicError::RecoveryRequired),
    }
}
pub(super) fn storage(
    error: AtomicError,
) -> Result<AtomicError, latent_state::embedded::StoreError> {
    use latent_state::embedded::StoreError;
    match error {
        AtomicError::Corrupt => Err(StoreError::Corrupt),
        AtomicError::UnsupportedFormat => Err(StoreError::UnsupportedFormat),
        AtomicError::Unavailable => Err(StoreError::Unavailable),
        _ => Ok(error),
    }
}
