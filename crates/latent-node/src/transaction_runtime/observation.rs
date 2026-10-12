//! Optional test observation of actual phases; no caller data or authority.
use latent_core::PlatformError;

#[derive(Debug, Clone, Copy)]
pub(super) enum Phase {
    Source,
    InitialPolicy,
    Retention,
    NamespaceRead,
    InitialSeal,
    PendingPublication,
    FinalSeal,
    HostOpen,
    PendingAuthorization,
    PendingPreparation,
    ExistingReplay,
    ReplayBinding,
    CompletionBinding,
}

#[cfg(feature = "transaction-test-observation")]
pub(super) fn platform<T>(
    phase: Phase,
    result: Result<T, PlatformError>,
) -> Result<T, PlatformError> {
    if let Err(error) = &result {
        eprintln!(
            "actual-command phase={phase:?} platform-code={:?}",
            error.code
        );
    }
    result
}

#[cfg(not(feature = "transaction-test-observation"))]
pub(super) fn platform<T>(
    _phase: Phase,
    result: Result<T, PlatformError>,
) -> Result<T, PlatformError> {
    result
}

#[cfg(feature = "transaction-test-observation")]
pub(super) fn atomic<T>(
    phase: Phase,
    result: Result<T, latent_commit::atomic::AtomicError>,
) -> Result<T, latent_commit::atomic::AtomicError> {
    if let Err(error) = &result {
        eprintln!("actual-command phase={phase:?} atomic-code={error:?}");
    }
    result
}

#[cfg(not(feature = "transaction-test-observation"))]
pub(super) fn atomic<T>(
    _phase: Phase,
    result: Result<T, latent_commit::atomic::AtomicError>,
) -> Result<T, latent_commit::atomic::AtomicError> {
    result
}
