//! A finite reserve carved from the same physical owner's original limits.
//! These permits supply resources; callers still check current recovery policy.

use super::{StoreIoAdmissionError, StoreIoError, StoreIoJob, StoreIoKind, StoreIoOwner};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct StoreIoRecoveryCapacity {
    pub workers: usize,
    pub queued_jobs: usize,
    pub accepted_jobs: usize,
    pub retained_bytes: u64,
    pub job_bytes: u64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct StoreIoRecoverySnapshot {
    pub capacity: Option<StoreIoRecoveryCapacity>,
    pub accepted: usize,
    pub queued: usize,
    pub running: usize,
    pub retained_bytes: u64,
}

impl<S: Send + Sync + 'static> StoreIoOwner<S> {
    /// Install once before opening ordinary admission. No new worker, queue or
    /// budget is created, and no accepted physical owner is displaced.
    pub fn install_recovery_capacity(
        &self,
        reserve: StoreIoRecoveryCapacity,
    ) -> Result<(), StoreIoError> {
        let mut state = self
            .inner
            .control
            .state
            .lock()
            .map_err(|_| StoreIoError::Poisoned)?;
        if state.closed {
            return Err(StoreIoError::AdmissionClosed);
        }
        if state.recovery_capacity == Some(reserve) {
            return Ok(());
        }
        let limits = &state.limits;
        if state.recovery_capacity.is_some()
            || state.accepted != 0
            || reserve.workers == 0
            || reserve.workers >= limits.workers
            || reserve.workers >= limits.active_reads
            || reserve.queued_jobs == 0
            || reserve.queued_jobs >= limits.queued_jobs
            || reserve.accepted_jobs < reserve.queued_jobs
            || reserve.accepted_jobs >= limits.accepted_jobs
            || reserve.queued_jobs > 64
            || reserve.accepted_jobs > 128
            || reserve.retained_bytes == 0
            || reserve.retained_bytes > 64 * 1024 * 1024
            || reserve.retained_bytes >= limits.retained_bytes - limits.resident_bytes
            || reserve.job_bytes == 0
            || reserve.job_bytes > reserve.retained_bytes
            || reserve.job_bytes > limits.job_bytes
        {
            return Err(StoreIoError::InvalidLimits);
        }
        state.recovery_capacity = Some(reserve);
        Ok(())
    }

    /// Status, pause/reconciliation and bounded maintenance use this resource
    /// class after purpose-specific authorization. A stuck writer still blocks
    /// writes; deadline expiry cannot steal its lock or prove its retirement.
    #[allow(clippy::result_large_err)]
    pub fn submit_recovery<T: Send + 'static, F: FnOnce(&S) -> T + Send + 'static>(
        &self,
        kind: StoreIoKind,
        bytes: u64,
        operation: F,
    ) -> Result<StoreIoJob<T>, StoreIoAdmissionError<F>> {
        self.submit_class(kind, bytes, true, operation)
    }

    pub fn recovery_snapshot(&self) -> Result<StoreIoRecoverySnapshot, StoreIoError> {
        let state = self
            .inner
            .control
            .state
            .lock()
            .map_err(|_| StoreIoError::Poisoned)?;
        Ok(StoreIoRecoverySnapshot {
            capacity: state.recovery_capacity,
            accepted: state.recovery_accepted,
            queued: state.queue.iter().filter(|job| job.recovery).count(),
            running: state.recovery_running,
            retained_bytes: state.recovery_bytes,
        })
    }
}
