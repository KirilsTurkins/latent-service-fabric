//! One actual durable worker, retained across waiter cancellation and join timeout.
use latent_audit::{AuditHandle, AuditLimits, AuditWorker, DirectoryPhase2AuditJournal};
use latent_core::{PlatformError, PlatformErrorCode};
use serde::Serialize;
use std::{
    path::PathBuf,
    sync::{Arc, Mutex},
    time::{Duration, Instant},
};
use tokio::runtime::Handle;

pub(super) struct AuditRuntime {
    handle: AuditHandle,
    worker: Arc<Mutex<Option<AuditWorker>>>,
    runtime: Handle,
}

#[derive(Debug, Clone, Copy, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct AuditShutdownReport {
    pub worker_joined: bool,
    pub queued_operations: usize,
    pub query_owners: usize,
    pub query_bytes: usize,
    pub pending_attempts: usize,
    pub reserved_records: usize,
    pub stage_bytes: usize,
    pub recovery_pending: bool,
    pub unknown_outcomes: u64,
    pub previous_session_loss_unknown: bool,
}
impl AuditShutdownReport {
    pub(super) fn clean(self) -> bool {
        self.worker_joined
            && self.queued_operations == 0
            && self.query_owners == 0
            && self.query_bytes == 0
            && self.pending_attempts == 0
            && self.reserved_records == 0
            && self.stage_bytes == 0
            && !self.recovery_pending
    }
}

impl AuditRuntime {
    pub(super) async fn open(
        root: PathBuf,
        limits: Option<AuditLimits>,
        runtime: Handle,
    ) -> Result<Option<Self>, PlatformError> {
        let worker_runtime = runtime.clone();
        runtime
            .spawn_blocking(move || {
                let Some(limits) = limits else {
                    // Exact NotFound is the only absence. A symlink, inaccessible
                    // path, partial marker or prior audit root cannot disable audit.
                    return match std::fs::symlink_metadata(&root) {
                        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(None),
                        _ => Err(failure(
                            PlatformErrorCode::PermissionDenied,
                            "audit-mode-downgrade-forbidden",
                        )),
                    };
                };
                let (handle, worker) = DirectoryPhase2AuditJournal::open(root, limits)?;
                Ok(Some(Self {
                    handle,
                    worker: Arc::new(Mutex::new(Some(worker))),
                    runtime: worker_runtime,
                }))
            })
            .await
            .map_err(|_| {
                failure(
                    PlatformErrorCode::Unavailable,
                    "audit-startup-worker-failed",
                )
            })?
    }
    pub(super) fn handle(&self) -> AuditHandle {
        self.handle.clone()
    }
    pub(super) async fn shutdown(
        &self,
        grace: Duration,
    ) -> Result<AuditShutdownReport, PlatformError> {
        self.handle.close();
        let deadline = Instant::now().checked_add(grace).ok_or_else(|| {
            failure(
                PlatformErrorCode::InvalidArgument,
                "audit-shutdown-deadline-invalid",
            )
        })?;
        let owner = Arc::clone(&self.worker);
        let joined = self
            .runtime
            .spawn_blocking(move || {
                let mut guard = owner.lock().map_err(|_| {
                    failure(
                        PlatformErrorCode::Unavailable,
                        "audit-worker-owner-unavailable",
                    )
                })?;
                let complete = match guard.as_mut() {
                    Some(worker) => worker.join_until(deadline)?,
                    None => true,
                };
                if complete {
                    drop(guard.take());
                }
                // A timeout leaves the real worker in the same owner. Dropping a
                // waiting future cannot release its root lock or accepted work.
                Ok::<_, PlatformError>(complete)
            })
            .await
            .map_err(|_| {
                failure(
                    PlatformErrorCode::Unavailable,
                    "audit-shutdown-worker-failed",
                )
            })??;
        let snapshot = self.handle.snapshot();
        Ok(AuditShutdownReport {
            worker_joined: joined,
            queued_operations: snapshot.queued_operations,
            query_owners: snapshot.query_owners,
            query_bytes: snapshot.query_bytes,
            pending_attempts: snapshot.pending_attempts,
            reserved_records: snapshot.reserved_records,
            stage_bytes: snapshot.stage_bytes,
            recovery_pending: snapshot.recovery_pending,
            unknown_outcomes: snapshot.unknown_outcomes,
            previous_session_loss_unknown: snapshot.previous_session_loss_unknown,
        })
    }
}
impl Drop for AuditRuntime {
    fn drop(&mut self) {
        // Library Worker Drop only closes admission; actual storage and budget
        // remain owned by its existing thread until all accepted work finishes.
        self.handle.close();
    }
}
fn failure(code: PlatformErrorCode, message: &'static str) -> PlatformError {
    PlatformError {
        code,
        message: message.into(),
        retryable: false,
        details: Vec::new(),
    }
}
