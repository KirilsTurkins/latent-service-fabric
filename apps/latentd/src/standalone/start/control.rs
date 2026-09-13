//! The existing load/lease task is owned across startup and transferred once.

use std::sync::Arc;
use std::time::Duration;

use latent_core::{ActivationClock, PlatformError};
use latent_policy::supply_chain::SupplyChainAuthority;

use super::super::load::{HostLoad, LoadSampler};

pub(super) struct StartupControl {
    load: Arc<HostLoad>,
    sampler: Option<LoadSampler>,
    authority: Arc<SupplyChainAuthority>,
    armed: bool,
}

impl StartupControl {
    pub(super) fn start(
        authority: Arc<SupplyChainAuthority>,
        interval: Duration,
        runtime: &tokio::runtime::Handle,
        clock: Arc<dyn ActivationClock>,
    ) -> Self {
        let load = Arc::new(HostLoad::default());
        let sampler = LoadSampler::start(
            Arc::clone(&load),
            interval,
            runtime,
            Some(Arc::clone(&authority)),
            clock,
        );
        Self {
            load,
            sampler: Some(sampler),
            authority,
            armed: true,
        }
    }

    pub(super) fn load(&self) -> Arc<HostLoad> {
        Arc::clone(&self.load)
    }

    pub(super) fn transfer(mut self) -> LoadSampler {
        self.armed = false;
        self.sampler.take().expect("startup owns its one sampler")
    }

    pub(super) async fn shutdown(mut self, timeout: Duration) -> Result<(), PlatformError> {
        self.authority.retire();
        self.sampler
            .take()
            .expect("startup owns its one sampler")
            .shutdown(timeout)
            .await
    }
}

impl Drop for StartupControl {
    fn drop(&mut self) {
        // Cancellation cannot await here. Retire immediately; the same sampler's
        // Drop stops its task. Explicit startup failures take the joined path.
        if self.armed {
            self.authority.retire();
        }
    }
}
