//! One shared coordinator on the supplied control runtime, joined before audit.
use latent_audit::AuditHandle;
use latent_control_store::DirectoryDeploymentRepository;
use latent_core::{PlatformError, PlatformErrorCode};
use latent_rollout::{CoordinatorLimits, RolloutCoordinator, RolloutHandle, RolloutWorker};
use serde::Serialize;
use std::{
    sync::Arc,
    time::{Duration, Instant},
};
use tokio::{runtime::Handle, sync::Mutex};

pub(super) struct RolloutRuntime {
    handle: RolloutHandle,
    worker: Mutex<Option<RolloutWorker>>,
}

#[derive(Debug, Clone, Copy, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RolloutShutdownReport {
    pub worker_joined: bool,
    pub worker_live: bool,
    pub queued_commands: usize,
    pub active_commands: usize,
    pub retained_request_bytes: usize,
    pub response_owners: usize,
    pub response_bytes: usize,
    pub failed: bool,
}
impl RolloutShutdownReport {
    pub(super) fn clean(self) -> bool {
        self.worker_joined
            && !self.worker_live
            && !self.failed
            && self.queued_commands == 0
            && self.active_commands == 0
            && self.retained_request_bytes == 0
            && self.response_owners == 0
            && self.response_bytes == 0
    }
}

impl RolloutRuntime {
    pub(super) fn start(
        store: Arc<DirectoryDeploymentRepository>,
        audit: AuditHandle,
        limits: CoordinatorLimits,
        runtime: &Handle,
    ) -> Result<Self, PlatformError> {
        let (handle, worker) = RolloutCoordinator::start(store, audit, limits, runtime)?;
        Ok(Self {
            handle,
            worker: Mutex::new(Some(worker)),
        })
    }

    pub(super) async fn wait_started(&self, deadline: Instant) -> Result<(), PlatformError> {
        self.worker
            .lock()
            .await
            .as_mut()
            .expect("owned coordinator")
            .wait_started(deadline)
            .await
    }

    pub(super) fn handle(&self) -> RolloutHandle {
        self.handle.clone()
    }

    // An unfinished blocking task must never be followed by another blocking
    // join job on the same runtime. This is an observation, not cancellation.
    pub(super) async fn worker_joined(&self) -> bool {
        self.worker.lock().await.is_none()
    }

    pub(super) async fn shutdown(
        &self,
        grace: Duration,
    ) -> Result<RolloutShutdownReport, PlatformError> {
        self.handle.close();
        let deadline = Instant::now().checked_add(grace).ok_or_else(|| {
            super::error(
                PlatformErrorCode::InvalidArgument,
                "rollout-shutdown-deadline",
            )
        })?;
        // Await the existing worker directly. Scheduling another blocking job
        // here would deadlock a control runtime with one blocking thread.
        let mut guard = self.worker.lock().await;
        let joined = match guard.as_mut() {
            Some(worker) => worker.join_until(deadline).await?,
            None => true,
        };
        if joined {
            drop(guard.take());
        }
        let observed = self.handle.snapshot();
        Ok(RolloutShutdownReport {
            worker_joined: joined,
            worker_live: observed.worker_live,
            queued_commands: observed.queued_commands,
            active_commands: observed.active_commands,
            retained_request_bytes: observed.retained_request_bytes,
            response_owners: observed.response_owners,
            response_bytes: observed.response_bytes,
            failed: observed.failed,
        })
    }
}
impl Drop for RolloutRuntime {
    fn drop(&mut self) {
        self.handle.close();
    }
}
