//! One actual durable worker, retained across waiter cancellation and join timeout.
use latent_audit::{AuditHandle, AuditLimits, AuditWorker, DirectoryPhase2AuditJournal};
use latent_core::{node_metadata::NodeMetadataArc, PlatformError, PlatformErrorCode};
use serde::Serialize;
use std::{
    path::PathBuf,
    sync::Mutex,
    time::{Duration, Instant},
};
use tokio::runtime::Handle;

pub(super) struct AuditRuntime {
    handle: AuditHandle,
    worker: NodeMetadataArc<Mutex<Option<AuditWorker>>>,
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
                // This is the single original node metadata allowance. Audit
                // exists before providers, and can exist without providers.
                // The later broker can reuse only this exact owner AND ceiling;
                // a different broker limit refuses instead of widening either.
                let metadata = latent_core::node_metadata::NodeMetadataOwner::new(
                    limits.maximum_metadata_bytes,
                )
                .map_err(|_| {
                    failure(
                        PlatformErrorCode::ResourceExhausted,
                        "audit-native-capacity",
                    )
                })?;
                // Pay the real outer shared worker/header before the journal
                // allocates or starts its worker. This same owner survives a
                // cancelled shutdown waiter and a retained join timeout.
                let worker_owner =
                    NodeMetadataArc::<Mutex<Option<AuditWorker>>>::prepare_fixed(&metadata, 0)
                        .map_err(|_| {
                            failure(
                                PlatformErrorCode::ResourceExhausted,
                                "audit-native-capacity",
                            )
                        })?;
                let (handle, worker) =
                    DirectoryPhase2AuditJournal::open_with_node_metadata(root, limits, metadata)?;
                Ok(Some(Self {
                    handle,
                    worker: worker_owner.allocate(Mutex::new(Some(worker))),
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
    #[cfg(all(test, target_os = "linux", target_arch = "x86_64"))]
    pub(super) fn retirement_observer(&self) -> Self {
        Self {
            handle: self.handle(),
            worker: self.worker.clone(),
            runtime: self.runtime.clone(),
        }
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
        let owner = self.worker.clone();
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
