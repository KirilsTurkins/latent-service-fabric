//! Maintenance observes the same protected command/effect clock.
use super::super::effects::ProtectedEffectClock;
use latent_commit::atomic::{CommandTime, MaintenanceClock};
use latent_core::PlatformError;
use latent_wire::phase4::StateMaintenanceClock;
use std::{
    sync::{Arc, OnceLock},
    time::Instant,
};

#[derive(Clone, Copy)]
struct Origin {
    boot: [u8; 32],
    monotonic: Instant,
}
impl Origin {
    fn process(monotonic: Instant) -> Result<Self, PlatformError> {
        static ORIGIN: OnceLock<Result<Origin, ()>> = OnceLock::new();
        ORIGIN
            .get_or_init(|| {
                let mut boot = [0; 32];
                rustls::crypto::ring::default_provider()
                    .secure_random
                    .fill(&mut boot)
                    .map_err(|_| ())?;
                if boot == [0; 32] {
                    return Err(());
                }
                Ok(Self { boot, monotonic })
            })
            .as_ref()
            .copied()
            .map_err(|()| super::unavailable())
    }
}
pub(super) struct ProtectedMaintenanceClock {
    clock: Arc<ProtectedEffectClock>,
    origin: Origin,
}
impl ProtectedMaintenanceClock {
    pub fn new(clock: Arc<ProtectedEffectClock>) -> Result<Self, PlatformError> {
        // The first origin is from this same admitted clock, never a second
        // wall/monotonic sampling path or an implicit persisted anchor.
        let sample = clock.sample()?;
        let origin = Origin::process(sample.monotonic())?;
        Ok(Self { clock, origin })
    }
}

#[cfg(all(test, target_os = "linux", target_arch = "x86_64"))]
mod tests;
impl StateMaintenanceClock for ProtectedMaintenanceClock {
    fn sample(&self) -> Result<MaintenanceClock, PlatformError> {
        let sample = self.clock.sample()?;
        let monotonic_millis = sample
            .monotonic()
            .checked_duration_since(self.origin.monotonic)
            .and_then(|elapsed| u64::try_from(elapsed.as_millis()).ok())
            .ok_or_else(super::unavailable)?;
        Ok(MaintenanceClock {
            time: CommandTime {
                unix_millis: sample.unix_millis(),
                continuity_proven: true,
            },
            boot: self.origin.boot,
            monotonic_millis,
        })
    }
}
