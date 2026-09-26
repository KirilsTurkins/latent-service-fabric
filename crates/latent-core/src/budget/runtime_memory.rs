use super::{ActivationBudget, BudgetDimension, BudgetError};

/// One in-flight native linear-memory allocation. Capacity is excluded from
/// child delegation before allocation, and becomes observed usage only after
/// success. Dropping a failed allocation releases its pending capacity.
#[derive(Debug)]
#[must_use = "confirm successful native growth, or drop the failed allocation"]
pub struct RuntimeMemoryReservation {
    budget: ActivationBudget,
    peak: u64,
    pending: bool,
}
impl ActivationBudget {
    pub fn reserve_runtime_memory(
        &self,
        peak: u64,
    ) -> Result<RuntimeMemoryReservation, BudgetError> {
        if self.profile() != super::BudgetProfile::Phase3 {
            return Err(BudgetError::InvalidAccountingOperation {
                dimension: BudgetDimension::MemoryBytes,
            });
        }
        let mut state = self.lock_state();
        Self::ensure_mutable(&state)?;
        if state.pending_runtime_memory.is_some() {
            return Err(BudgetError::InvalidAccountingOperation {
                dimension: BudgetDimension::MemoryBytes,
            });
        }
        self.check_owned_memory(&state, peak)?;
        state.pending_runtime_memory = Some(peak);
        Ok(RuntimeMemoryReservation {
            budget: self.clone(),
            peak,
            pending: true,
        })
    }
}
impl RuntimeMemoryReservation {
    /// Called after the allocator has confirmed success. Finalization may freeze
    /// a conservative report while an allocation is pending; settling ownership
    /// cannot reopen or change that report.
    pub fn confirm(mut self) {
        let mut state = self.budget.lock_state();
        state.pending_runtime_memory = None;
        self.budget.record_owned_memory(&mut state, self.peak);
        self.pending = false;
    }
}
impl Drop for RuntimeMemoryReservation {
    fn drop(&mut self) {
        if self.pending {
            self.budget.lock_state().pending_runtime_memory = None;
        }
    }
}
