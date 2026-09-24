//! A separate, finite blocking-worker window; never the caller timer's domain.
use std::time::{Duration, Instant};

use crate::compiler::JobControl;
use latent_artifacts::ArtifactPreparationReadWait;
use latent_core::PlatformError;

pub(in crate::backend) struct WorkerWindow {
    control: JobControl,
    until: Option<Instant>,
}

impl WorkerWindow {
    pub(super) fn new(control: JobControl) -> Self {
        // Minted once at the owned job's creation, so queue and compilation
        // consume this same window. Coalesced callers cannot refresh it.
        let until = control.created().checked_add(Duration::from_secs(5));
        Self { control, until }
    }

    pub(in crate::backend) fn check<T>(
        window: Option<&Self>,
        mut read: impl FnMut() -> Result<T, PlatformError>,
    ) -> Result<T, PlatformError> {
        loop {
            match read() {
                Err(error)
                    if super::wait::busy(&error)
                        && window.is_some_and(ArtifactPreparationReadWait::wait_after_busy) => {}
                result => return result,
            }
        }
    }
}

impl ArtifactPreparationReadWait for WorkerWindow {
    fn wait_after_busy(&self) -> bool {
        #[cfg(test)]
        self.control.record_wait();
        let Some(until) = self.until else {
            return false;
        };
        if self.control.is_stopped() {
            return false;
        }
        let now = Instant::now();
        if now >= until {
            return false;
        }
        // No repository, lifecycle, policy or compiler guard is held here.
        // This is the existing fixed compiler worker, not a detached task.
        std::thread::sleep(until.duration_since(now).min(Duration::from_millis(10)));
        !self.control.is_stopped() && Instant::now() < until
    }
}

#[cfg(test)]
mod tests;
