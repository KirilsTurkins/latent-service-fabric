//! Recovery resources are installed in the original fixed startup profile.
//! These compatibility ports validate that profile; they cannot grow capacity.
use super::{
    StoreIoAdmissionError, StoreIoError, StoreIoJob, StoreIoKind, StoreIoOwner,
    StoreIoRecoveryLimits,
};

pub type StoreIoRecoveryCapacity = StoreIoRecoveryLimits;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct StoreIoRecoverySnapshot {
    pub capacity: Option<StoreIoRecoveryCapacity>,
    pub accepted: usize,
    pub queued: usize,
    pub running: usize,
    pub retained_bytes: u64,
}

impl<S: Send + Sync + 'static> StoreIoOwner<S> {
    /// Confirm the exact recovery partition selected before worker creation.
    /// Missing configuration, changed limits or a live owner cannot install or
    /// displace workers, queues, buffers or reservations after startup.
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
        if state.accepted != 0 || state.limits.recovery != Some(reserve) {
            return Err(StoreIoError::InvalidLimits);
        }
        Ok(())
    }

    /// Use the existing fixed recovery lane after current purpose-specific
    /// authorization. Its writes share the original single-writer fence.
    #[allow(clippy::result_large_err)]
    pub fn submit_recovery<T: Send + 'static, F: FnOnce(&S) -> T + Send + 'static>(
        &self,
        kind: StoreIoKind,
        bytes: u64,
        operation: F,
    ) -> Result<StoreIoJob<T>, StoreIoAdmissionError<F>> {
        let kind = if kind.is_write() {
            StoreIoKind::RecoveryWrite
        } else {
            StoreIoKind::RecoveryRead
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
