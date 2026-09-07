//! Shared clock boundary for admission and activation-scoped capabilities.

use std::time::Instant;

use crate::ClockSample;

/// Supplies a coherent admission sample and monotonic runtime observations.
/// Implementations must use the same monotonic time domain for both methods.
pub trait ActivationClock: Send + Sync {
    fn sample(&self) -> ClockSample;
    fn monotonic_now(&self) -> Instant;
}

#[derive(Debug, Clone, Copy, Default)]
pub struct SystemActivationClock;

impl ActivationClock for SystemActivationClock {
    fn sample(&self) -> ClockSample {
        ClockSample::system_now()
    }

    fn monotonic_now(&self) -> Instant {
        Instant::now()
    }
}
