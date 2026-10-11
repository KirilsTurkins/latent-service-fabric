//! Recovery compatibility projections over the immutable physical partition.
//! The constructor preallocates every queue and fixed worker before admission.

use super::{StoreIoAdmissionError, StoreIoError, StoreIoJob, StoreIoKind, StoreIoOwner};

pub type StoreIoRecoveryCapacity = super::StoreIoRecoveryLimits;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct StoreIoRecoverySnapshot {
    pub capacity: Option<StoreIoRecoveryCapacity>,
    pub accepted: usize,
    pub queued: usize,
    pub running: usize,
    pub retained_bytes: u64,
}

impl<S: Send + Sync + 'static> StoreIoOwner<S> {
    /// Validate the constructor's SAME immutable recovery partition. Never
    /// create workers, change limits, or displace an accepted physical owner.
    pub fn install_recovery_capacity(
        &self,
        reserve: StoreIoRecoveryCapacity,
    ) -> Result<(), StoreIoError> {
        let state = self
            .inner
            .control
            .state
            .lock()
            .map_err(|_| StoreIoError::Poisoned)?;
        if state.closed {
            return Err(StoreIoError::AdmissionClosed);
        }
        if state.limits.recovery != Some(reserve) {
            return Err(StoreIoError::InvalidLimits);
        }
        Ok(())
    }

    /// Use only after original purpose-specific authority has accepted this
    /// work. The reserve shares the same physical writer and lifetime ledger.
    #[allow(clippy::result_large_err)]
    pub fn submit_recovery<T: Send + 'static, F: FnOnce(&S) -> T + Send + 'static>(
        &self,
        kind: StoreIoKind,
        bytes: u64,
        operation: F,
    ) -> Result<StoreIoJob<T>, StoreIoAdmissionError<F>> {
        let kind = match kind {
            StoreIoKind::Read | StoreIoKind::RecoveryRead => StoreIoKind::RecoveryRead,
            StoreIoKind::Write | StoreIoKind::RecoveryWrite => StoreIoKind::RecoveryWrite,
        };
        self.submit(kind, bytes, operation)
    }

    pub fn recovery_snapshot(&self) -> Result<StoreIoRecoverySnapshot, StoreIoError> {
        let state = self
            .inner
            .control
            .state
            .lock()
            .map_err(|_| StoreIoError::Poisoned)?;
        Ok(StoreIoRecoverySnapshot {
            capacity: state.limits.recovery,
            accepted: state.recovery_accepted,
            queued: state.recovery_queue.len(),
            running: state.active_recovery_reads + state.active_recovery_writes,
            retained_bytes: state.recovery_retained_bytes,
        })
    }
}
