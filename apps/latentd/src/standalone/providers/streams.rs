use crate::config::StreamInstallation;
use latent_capabilities::broker::pools::ProviderPools;
use latent_core::PlatformError;
use latent_streams::StreamLifecycle;
use std::sync::Arc;
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Mutex,
};
use std::time::Instant;
use tokio::task::JoinHandle;

pub(super) struct Driver {
    stop: latent_streams::StreamMaintenanceStop,
    task: Mutex<Option<JoinHandle<Result<(), latent_streams::StreamError>>>>,
    joined: AtomicBool,
    clean: AtomicBool,
}

impl Driver {
    pub fn start(
        owner: &Arc<StreamLifecycle>,
        runtime: &tokio::runtime::Handle,
    ) -> Result<Self, PlatformError> {
        let maintenance = owner.maintenance().map_err(|_| super::unavailable())?;
        let stop = maintenance.stop_handle();
        Ok(Self {
            stop,
            task: Mutex::new(Some(runtime.spawn(maintenance.run()))),
            joined: AtomicBool::new(false),
            clean: AtomicBool::new(false),
        })
    }

    pub fn stop(&self) {
        self.stop.stop();
    }

    pub async fn join(&self, deadline: Instant) -> bool {
        self.stop();
        let task = self
            .task
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .take();
        let Some(task) = task else {
            return self.joined.load(Ordering::Acquire) && self.clean.load(Ordering::Acquire);
        };
        let mut waiter = Waiter {
            owner: self,
            task: Some(task),
        };
        let result =
            tokio::time::timeout_at(deadline.into(), waiter.task.as_mut().expect("owned task"))
                .await;
        let Ok(result) = result else {
            return false; // Waiter restores the same unjoined physical owner.
        };
        waiter.task = None;
        let clean = matches!(result, Ok(Ok(())));
        self.clean.store(clean, Ordering::Release);
        self.joined.store(true, Ordering::Release);
        clean
    }
}

struct Waiter<'a> {
    owner: &'a Driver,
    task: Option<JoinHandle<Result<(), latent_streams::StreamError>>>,
}
impl Drop for Waiter<'_> {
    fn drop(&mut self) {
        if let Some(task) = self.task.take() {
            *self
                .owner
                .task
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner) = Some(task);
        }
    }
}
impl Drop for Driver {
    fn drop(&mut self) {
        self.stop();
        if let Some(task) = self
            .task
            .get_mut()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .take()
        {
            // Last node-owner Drop requests abort; the actual runtime task keeps
            // its original metadata until its future is physically destroyed.
            task.abort();
        }
    }
}

#[cfg(feature = "development-outbound-streams")]
pub(super) fn install(
    pools: &Arc<ProviderPools>,
    config: &StreamInstallation,
) -> Result<StreamLifecycle, PlatformError> {
    StreamLifecycle::install_for_qualification(
        pools.clone(),
        &config.identity.id,
        config.identity.epoch,
        config.configuration.clone(),
    )
    .map_err(|_| super::unavailable())
}
#[cfg(not(feature = "development-outbound-streams"))]
pub(super) fn install(
    _pools: &Arc<ProviderPools>,
    _config: &StreamInstallation,
) -> Result<StreamLifecycle, PlatformError> {
    Err(super::unavailable())
}
