//! Provider construction retains only a once-bound projection of the boot clock.
use std::sync::{Arc, OnceLock};

use latent_core::PlatformError;
use latent_effects::{authority::EffectTime, runtime::EffectTimeSource};

use super::super::effects::ProtectedEffectClock;

/// Contains no clock/floor/grant owner of its own. Before the exact protected
/// startup returns and binds its clock, every observation fails closed.
#[derive(Default)]
pub(super) struct AdapterClock {
    admitted: OnceLock<Arc<ProtectedEffectClock>>,
}

impl AdapterClock {
    pub fn bind(&self, clock: Arc<ProtectedEffectClock>) -> Result<(), PlatformError> {
        self.admitted.set(clock).map_err(|_| super::unavailable())
    }
}

impl EffectTimeSource for AdapterClock {
    fn observe(&self) -> EffectTime {
        match self.admitted.get() {
            Some(clock) => clock.observe(),
            None => EffectTime {
                unix_millis: 0,
                continuity_proven: false,
            },
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn an_unbound_provider_clock_never_synthesizes_wall_time_or_continuity() {
        let clock = AdapterClock::default();
        for _ in 0..2 {
            let sample = clock.observe();
            assert_eq!(sample.unix_millis, 0);
            assert!(!sample.continuity_proven);
        }
        assert!(clock.admitted.get().is_none());
    }
}
