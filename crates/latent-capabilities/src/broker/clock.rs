//! The two in-process clocks may wait for pre-effect currentness admission.
//! This is not a retry facility for generic providers, audit I/O, or effects.

use super::{session::PendingBinding, waiting::WaitingCall, work::PendingWork};
use super::{CapabilitySession, PlatformError, ProviderCall};
use latent_executor::PreparationReadWait;

mod window;
use window::Window;

/// Closed host-clock adapter identity; neither variant grants authority.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum HostClock {
    Monotonic,
    Wall,
}

impl HostClock {
    #[must_use]
    pub const fn capability(self) -> &'static str {
        match self {
            Self::Monotonic => "latent:clock/monotonic@0.1.0",
            Self::Wall => "latent:clock/wall@0.1.0",
        }
    }

    #[must_use]
    pub const fn operation(self) -> &'static str {
        match self {
            Self::Monotonic => "now-nanos",
            Self::Wall => "now-unix-millis",
        }
    }
}

impl CapabilitySession {
    /// Admit exactly one 8-byte, 100-fuel host clock call. Only a validated
    /// currentness Busy *before* publication/commit may defer. The original
    /// grant, deadline, bounded pending owners and a single five-second window
    /// span binding and work admission. No clock sample or provider callback is
    /// run here. Dropping the future drops its timer and all pending ownership.
    /// Required-audit policies remain rejected, like synchronous clock calls.
    pub async fn begin_host_clock(
        &self,
        clock: HostClock,
        wait: &dyn PreparationReadWait,
    ) -> Result<ProviderCall, PlatformError> {
        let mut binding = PendingBinding::new(self, clock);
        let window = Window::new(wait, self.core.deadline.monotonic())
            .map_err(|failure| binding.observe_failure(failure))?;
        let waiting = WaitingCall::new(self).map_err(|failure| binding.observe_failure(failure))?;
        let result = async {
            loop {
                waiting.check()?;
                match binding.attempt() {
                    Ok(handle) => break Ok(handle),
                    Err(failure) => {
                        if binding.entered() || !window.pause(&failure, &waiting, None).await? {
                            break Err(failure);
                        }
                    }
                }
            }
        }
        .await;
        binding.observe(&result);
        let handle = result?;
        let mut work = PendingWork::new(self, handle, clock)?;
        loop {
            waiting.check()?;
            match work.attempt() {
                Ok(()) => break,
                Err(failure) => {
                    if work.entered() || !window.pause(&failure, &waiting, work.deadline()).await? {
                        return Err(failure);
                    }
                }
            }
        }
        // The lookup is closed by PendingBinding, but the affine call retains
        // its row until the adapter actually finishes. No guard reaches await.
        let call = work.finish();
        call.require_host_mode()?;
        Ok(call)
    }
}
