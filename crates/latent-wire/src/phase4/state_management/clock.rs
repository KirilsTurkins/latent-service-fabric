//! Host-installed clock observation for the original maintenance owner.
use latent_commit::atomic::MaintenanceClock;
use latent_core::PlatformError;

/// Sample the same protected continuity source used by commands and effects.
/// One process retains one boot identity and monotonic origin. Restart supplies
/// a different boot: persisted maintenance progress then refuses until explicit
/// current-policy re-anchoring. This observation grants no maintenance, result
/// read, destructive mutation or restore authority and cannot install an anchor.
pub trait StateMaintenanceClock: Send + Sync {
    /// Return one coherent protected wall/monotonic observation.
    ///
    /// # Errors
    /// Refuses if the protected source cannot prove continuity or the retained
    /// process clock observation cannot be represented within the finite bounds.
    fn sample(&self) -> Result<MaintenanceClock, PlatformError>;
}
