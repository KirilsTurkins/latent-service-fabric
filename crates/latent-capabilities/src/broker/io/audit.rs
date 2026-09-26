//! Preserve the actual I/O owner while awaiting a terminal audit write.
use super::{Authority, IoCall, PlatformError};
use crate::broker::{AuditProviderOutcome, CapabilityAuditDurability};

impl IoCall {
    /// Evidence observed by the trusted transport, even after caller cancellation.
    pub fn record_provider_outcome(
        &mut self,
        outcome: AuditProviderOutcome,
    ) -> Result<(), PlatformError> {
        let mut state = self
            .operation
            .execution
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let Authority::Running(call) = &mut state.authority else {
            return Err(super::denied());
        };
        call.record_provider_outcome(outcome)
    }
    pub async fn finish_audit(&mut self) -> CapabilityAuditDurability {
        let deadline = self.deadline();
        let audit = {
            let mut state = self
                .operation
                .execution
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            let Authority::Running(call) = &mut state.authority else {
                return CapabilityAuditDurability::OutcomeUnknown;
            };
            call.take_audit()
        };
        let Some(mut audit) = audit else {
            return CapabilityAuditDurability::NotRequired;
        };
        // Dropping this future submits the prepaid uncertain terminal; the real
        // operation and its buffers/sockets still retain their own charges.
        let durability = audit.finish(deadline).await;
        let mut state = self
            .operation
            .execution
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if let Authority::Running(call) = &mut state.authority {
            call.restore_audit(audit);
        }
        durability
    }
}
