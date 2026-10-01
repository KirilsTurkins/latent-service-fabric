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

/// Current descriptive clock coverage from the existing durable authority.
/// This observation grants no data access, execution, commit or dispatch right.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct CoveredClock {
    pub now_seconds: u64,
    pub authority_epoch: u64,
    pub covered_until_seconds: u64,
}

impl super::SupplyChainAuthority {
    /// Reads the original covered clock under the same bounded currentness
    /// owner. No filesystem operation, lease renewal or new owner is performed.
    pub fn covered_clock(&self) -> Result<CoveredClock, PlatformError> {
        let mut state = self.inner.lock()?;
        let now_seconds = self.inner.sample(&mut state)?;
        Ok(CoveredClock {
            now_seconds,
            authority_epoch: state.floor.epoch,
            covered_until_seconds: state.floor.restart_not_before,
        })
    }
}
