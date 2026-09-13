mod handle;
mod state;
use crate::{
    closed, deadline,
    worker::{self, Command},
    CoordinatorLimits, CoordinatorSnapshot, Result,
};
use latent_audit::AuditHandle;
use latent_control_store::{rollouts::RolloutLimits, DirectoryDeploymentRepository};
pub(crate) use state::{RequestCharge, Shared};
use std::{
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc, Mutex,
    },
    time::Instant,
};
use tokio::{
    runtime::Handle,
    sync::{mpsc, oneshot},
    task::JoinHandle,
};

pub struct RolloutCoordinator;
#[derive(Clone)]
pub struct RolloutHandle {
    pub(crate) owner: Arc<Owner>,
}
pub struct RolloutWorker {
    owner: Arc<Owner>,
    task: Option<JoinHandle<()>>,
    started: Option<oneshot::Receiver<Result<()>>>,
}
pub(crate) struct Owner {
    sender: Mutex<Option<mpsc::Sender<Command>>>,
    pub shared: Arc<Shared>,
    audit: AuditHandle,
    store_limits: RolloutLimits,
    canary: Option<latent_telemetry::BoundedPhase2CanaryOutcomeWindow>,
}
impl Owner {
    fn close(&self) {
        self.shared.closed.store(true, Ordering::Release);
        self.shared.shutdown.notify_one();
        drop(
            self.sender
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner)
                .take(),
        );
    }
}
impl Drop for Owner {
    fn drop(&mut self) {
        self.close();
    }
}

impl RolloutCoordinator {
    /// One actual blocking control worker, using the supplied runtime for async
    /// preparation. Await startup, and join it before shutting down audit/runtime.
    pub fn start(
        repository: Arc<DirectoryDeploymentRepository>,
        audit: AuditHandle,
        limits: CoordinatorLimits,
        runtime: &Handle,
    ) -> Result<(RolloutHandle, RolloutWorker)> {
        let limits = limits.validate()?;
        let store_limits = repository.rollout_limits();
        let (sender, receiver) = mpsc::channel(limits.maximum_queued_commands);
        let shared = Arc::new(Shared {
            limits,
            pages: crate::lease::PageBudget::new(limits),
            closed: AtomicBool::new(false),
            failed: AtomicBool::new(false),
            started: AtomicBool::new(false),
            live: AtomicBool::new(false),
            completed: AtomicBool::new(false),
            shutdown: tokio::sync::Notify::new(),
            stats: Mutex::default(),
            canary_windows: std::sync::atomic::AtomicUsize::new(0),
            canary_bytes: std::sync::atomic::AtomicUsize::new(0),
        });
        let owner = Arc::new(Owner {
            sender: Mutex::new(Some(sender)),
            shared: Arc::clone(&shared),
            audit: audit.clone(),
            store_limits,
            canary: repository.canary_hub().cloned(),
        });
        let (started, startup) = oneshot::channel();
        let clock = runtime.clone();
        let task = runtime.spawn_blocking(move || {
            shared.live.store(true, Ordering::Release);
            let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                clock.block_on(worker::run(
                    repository,
                    audit,
                    receiver,
                    Arc::clone(&shared),
                    started,
                ));
            }));
            if result.is_err() {
                shared.failed.store(true, Ordering::Release);
            }
            shared.closed.store(true, Ordering::Release);
            shared.live.store(false, Ordering::Release);
            shared.completed.store(true, Ordering::Release);
        });
        Ok((
            RolloutHandle {
                owner: Arc::clone(&owner),
            },
            RolloutWorker {
                owner,
                task: Some(task),
                started: Some(startup),
            },
        ))
    }
}

impl RolloutWorker {
    pub async fn wait_started(&mut self, expires: Instant) -> Result<()> {
        if let Some(started) = self.started.as_mut() {
            let result = tokio::time::timeout_at(expires.into(), started)
                .await
                .map_err(|_| deadline())?
                .map_err(|_| closed())?;
            self.started = None;
            result?;
        }
        if Instant::now() >= expires {
            return Err(deadline());
        }
        if self.owner.shared.failed.load(Ordering::Acquire) {
            return Err(closed());
        }
        Ok(())
    }
    pub fn close(&self) {
        self.owner.close();
    }
    #[must_use]
    pub fn snapshot(&self) -> CoordinatorSnapshot {
        self.owner.shared.snapshot()
    }
    /// A timeout keeps the same task handle and all actual work ownership.
    pub async fn join_until(&mut self, expires: Instant) -> Result<bool> {
        self.close();
        if let Some(task) = self.task.as_mut() {
            match tokio::time::timeout_at(expires.into(), task).await {
                Ok(result) => {
                    self.task = None;
                    result.map_err(|_| closed())?;
                }
                Err(_) => return Ok(false),
            }
        }
        if self.owner.shared.failed.load(Ordering::Acquire) {
            return Err(closed());
        }
        Ok(Instant::now() < expires)
    }
}
impl Drop for RolloutWorker {
    fn drop(&mut self) {
        self.close();
    }
}
