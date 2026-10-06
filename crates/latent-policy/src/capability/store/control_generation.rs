//! The actual persisted policy image supplies the installation generation.
//! This bounded token contains neither a row revision nor an execution grant.
use super::{mutation::check_deadline, ownership::Owner, PolicyReadLease, PolicyStore};
use crate::capability::{denied, unavailable};
use latent_core::PlatformError;
use std::{sync::Arc, time::Instant};

/// A capture from one original configured policy owner. The real read lease
/// bounds retained captures, and equality of numbers never substitutes for the
/// original owner or the current persisted image at installation.
pub struct PolicyControlGeneration {
    owner: Arc<Owner>,
    generation: u64,
    _lease: PolicyReadLease,
}

impl PolicyControlGeneration {
    /// Descriptive identity only. It cannot authorize a state/effect operation.
    #[must_use]
    pub const fn persisted_generation(&self) -> u64 {
        self.generation
    }
}

impl PolicyStore {
    /// Capture `Image.generation` from the actual persisted owner, after its
    /// bounded read admission. Row revision, document digest and provider
    /// configuration epochs are deliberately not inputs to this producer.
    pub fn capture_control_generation(
        &self,
        deadline: Instant,
    ) -> Result<PolicyControlGeneration, PlatformError> {
        check_deadline(deadline)?;
        let lease = self.owner.lease()?;
        let _fence = self.owner.fence.try_read().map_err(|_| unavailable())?;
        let state = self.lock()?;
        let generation = state.image.generation;
        check_deadline(deadline)?;
        Ok(PolicyControlGeneration {
            owner: Arc::clone(&self.owner),
            generation,
            _lease: lease,
        })
    }

    /// Recheck the same original owner and complete persisted generation under
    /// its existing policy fence before an installation uses the captured
    /// number. The callback must be short: no waiting, I/O, credential copy or
    /// recursive policy entry. Acquire subsequent catalog/namespace fences in
    /// that order. This does not replace their own permission/currentness checks.
    pub fn with_control_generation(
        &self,
        captured: &PolicyControlGeneration,
        deadline: Instant,
        action: &mut dyn FnMut(u64) -> Result<(), PlatformError>,
    ) -> Result<(), PlatformError> {
        check_deadline(deadline)?;
        if !Arc::ptr_eq(&self.owner, &captured.owner) {
            return Err(denied());
        }
        let _fence = self.owner.fence.try_read().map_err(|_| unavailable())?;
        let state = self.lock()?;
        if state.image.generation != captured.generation {
            return Err(denied());
        }
        check_deadline(deadline)?;
        let _unwind = PoisonOnUnwind(&self.owner);
        action(state.image.generation)
    }
}

struct PoisonOnUnwind<'a>(&'a Owner);
impl Drop for PoisonOnUnwind<'_> {
    fn drop(&mut self) {
        if std::thread::panicking() {
            self.0.poison();
        }
    }
}
