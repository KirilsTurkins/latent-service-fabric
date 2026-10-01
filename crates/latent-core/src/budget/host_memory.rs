//! Actual Phase 4 native buffers share the original guest memory ceiling.
use super::{ActivationBudget, BudgetDimension, BudgetError, BudgetProfile};

#[derive(Debug)]
#[must_use = "retain through actual native buffer destruction, including after finalization"]
pub struct HostMemoryReservation {
    budget: ActivationBudget,
    bytes: u64,
}
impl ActivationBudget {
    /// Reserve before allocating transaction/view metadata, IO payloads or
    /// canonical copies. Terminal observation cannot release live native bytes.
    pub fn reserve_host_memory(&self, bytes: u64) -> Result<HostMemoryReservation, BudgetError> {
        if self.profile() != BudgetProfile::Phase4 || bytes == 0 || self.has_budget_parent() {
            return Err(BudgetError::InvalidAccountingOperation {
                dimension: BudgetDimension::MemoryBytes,
            });
        }
        let mut state = self.lock_state();
        Self::ensure_mutable(&state)?;
        let occupied = state
            .own_memory_peak
            .max(state.pending_runtime_memory.unwrap_or(0))
            + state.child_reserved_memory
            + state.host_reserved_memory;
        let limit = self.granted().memory_bytes;
        if bytes > limit.saturating_sub(occupied) {
            return Err(BudgetError::Exhausted {
                dimension: BudgetDimension::MemoryBytes,
                limit,
                consumed: occupied,
                requested: bytes,
            });
        }
        let count = state.outstanding_reservations.checked_add(1).ok_or(
            BudgetError::ArithmeticOverflow {
                dimension: BudgetDimension::MemoryBytes,
            },
        )?;
        state.host_reserved_memory += bytes;
        state.outstanding_reservations = count;
        state.consumption.peak_memory_bytes = state
            .consumption
            .peak_memory_bytes
            .max(state.own_memory_peak + state.child_observed_memory + state.host_reserved_memory);
        Ok(HostMemoryReservation {
            budget: self.clone(),
            bytes,
        })
    }
}
impl Drop for HostMemoryReservation {
    fn drop(&mut self) {
        let mut state = self.budget.lock_state();
        state.host_reserved_memory -= self.bytes;
        state.outstanding_reservations -= 1;
    }
}
