//! Shared clock boundary for admission and activation-scoped capabilities.

use std::time::Instant;

use crate::ClockSample;

/// Supplies a coherent admission sample and monotonic runtime observations.
/// Implementations must use the same monotonic time domain for both methods.
pub trait ActivationClock: Send + Sync {
    fn sample(&self) -> ClockSample;
    fn monotonic_now(&self) -> Instant;

    /// Whether monotonic observations use the process's ordinary system clock.
    /// Custom clocks opt in only when system-timer waiting is appropriate.
    fn uses_system_monotonic(&self) -> bool {
        false
    }

    /// Optional bounded observation of the manager's deadline-wait boundary.
    fn deadline_wait_observer(&self) -> Option<&crate::DeadlineWaitObserver> {
        None
    }
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

    fn uses_system_monotonic(&self) -> bool {
        true
    }
}
