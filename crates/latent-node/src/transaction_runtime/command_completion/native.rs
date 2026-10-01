use latent_commit::atomic::{AtomicError, PhysicalAttemptWork};
use latent_core::HostMemoryReservation;
use latent_state::protected_store::ProtectedStoreOperation;
use std::sync::Arc;

/// This guard moves into the one accepted worker callback. Queue refusal/drop
/// before callback entry is a positive never-started observation. A panic after
/// entry retains quarantine rather than claiming physical completion.
pub(super) struct NativeCommandWork {
    operation: Option<ProtectedStoreOperation>,
    attempt: Option<PhysicalAttemptWork>,
    _memory: Option<Arc<HostMemoryReservation>>,
    entered: bool,
}
impl NativeCommandWork {
    pub fn new(
        operation: ProtectedStoreOperation,
        attempt: Option<PhysicalAttemptWork>,
        memory: Option<Arc<HostMemoryReservation>>,
    ) -> Self {
        Self {
            operation: Some(operation),
            attempt,
            _memory: memory,
            entered: false,
        }
    }
    pub fn enter(&mut self) {
        self.entered = true;
    }
    pub fn complete(mut self) {
        if let Some(work) = self.attempt.take() {
            work.retire();
        }
        if let Some(operation) = self.operation.take() {
            drop(operation.retire());
        }
    }
    pub fn into_operation(mut self) -> Result<ProtectedStoreOperation, AtomicError> {
        if let Some(work) = self.attempt.take() {
            work.retire();
        }
        self.operation.take().ok_or(AtomicError::RecoveryRequired)
    }
}
impl Drop for NativeCommandWork {
    fn drop(&mut self) {
        if !self.entered {
            if let Some(work) = self.attempt.take() {
                work.retire();
            }
            if let Some(operation) = self.operation.take() {
                drop(operation.retire());
            }
        }
    }
}
