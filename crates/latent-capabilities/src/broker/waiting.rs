use super::{busy, capacity, session::SessionCore, CapabilitySession, Charge, Kind, PlatformError};
use std::{
    sync::{atomic::Ordering, Arc},
    time::Instant,
};

// An activation owner while waiting for shared I/O capacity. It confers no
// provider authority: dispatch still performs the final policy/publication fence.
pub(super) struct WaitingCall {
    pub core: Arc<SessionCore>,
    _metadata: Charge,
    _lifetime: WaitingLifetime,
}
struct WaitingLifetime(Arc<super::session::Stats>);
impl Drop for WaitingLifetime {
    fn drop(&mut self) {
        self.0.waiting.fetch_sub(1, Ordering::AcqRel);
    }
}
impl WaitingCall {
    pub fn new(session: &CapabilitySession) -> Result<Self, PlatformError> {
        let core = &session.core;
        let live = core.owner.live.try_read().map_err(|_| busy())?;
        if !*live {
            return Err(super::stopped());
        }
        let _state = core.state.try_lock().map_err(|_| busy())?;
        core.check()?;
        if core.stats.waiting.load(Ordering::Acquire) >= core.owner.limits.maximum_calls_per_session
        {
            return Err(capacity());
        }
        let metadata = core.owner.counters.acquire(Kind::Metadata, 512)?;
        core.stats.waiting.fetch_add(1, Ordering::AcqRel);
        Ok(Self {
            core: Arc::clone(core),
            _metadata: metadata,
            _lifetime: WaitingLifetime(Arc::clone(&core.stats)),
        })
    }
    pub fn deadline(&self) -> Result<Instant, PlatformError> {
        self.core.deadline.monotonic().ok_or_else(super::denied)
    }
    pub fn check(&self) -> Result<(), PlatformError> {
        self.core.check()?;
        let live = self.core.owner.live.try_read().map_err(|_| busy())?;
        if !*live {
            return Err(super::stopped());
        }
        Ok(())
    }
}
