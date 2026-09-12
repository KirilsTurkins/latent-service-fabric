use latent_core::PlatformError;
use std::time::{SystemTime, UNIX_EPOCH};

/// Trusted host clock. Request timestamps never implement this interface.
pub trait SupplyChainClock: Send + Sync {
    fn now(&self) -> Result<u64, PlatformError>;
}
#[derive(Debug, Default)]
pub struct SystemSupplyChainClock;
impl SupplyChainClock for SystemSupplyChainClock {
    fn now(&self) -> Result<u64, PlatformError> {
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|duration| duration.as_secs())
            .map_err(|_| super::unavailable("admission-clock-unavailable"))
    }
}
