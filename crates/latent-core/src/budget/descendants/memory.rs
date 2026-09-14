use super::{AccountingState, ActivationBudget, BudgetDimension, ParentReservation};
use crate::BudgetError;

impl ActivationBudget {
    pub(super) fn reserve_child_memory(&self, bytes: u64) -> Result<(), BudgetError> {
        let mut state = self.lock_state();
        Self::ensure_mutable(&state)?;
        let occupied = state.own_memory_peak + state.child_reserved_memory;
        let limit = self.granted().memory_bytes;
        if bytes > limit - occupied {
            return Err(BudgetError::Exhausted {
                dimension: BudgetDimension::MemoryBytes,
                limit,
                consumed: occupied,
                requested: bytes,
            });
        }
        state.child_reserved_memory += bytes;
        Ok(())
    }
    pub(in crate::budget) fn check_owned_memory(
        &self,
        state: &AccountingState,
        bytes: u64,
    ) -> Result<(), BudgetError> {
        let limit = self.granted().memory_bytes;
        if bytes > limit.saturating_sub(state.child_reserved_memory) {
            return Err(BudgetError::Exhausted {
                dimension: BudgetDimension::MemoryBytes,
                limit,
                consumed: state.own_memory_peak + state.child_reserved_memory,
                requested: bytes,
            });
        }
        Ok(())
    }
    pub(in crate::budget) fn record_owned_memory(&self, state: &mut AccountingState, bytes: u64) {
        let peak = state.own_memory_peak.max(bytes);
        let increase = peak - state.own_memory_peak;
        state.own_memory_peak = peak;
        state.consumption.peak_memory_bytes = state
            .consumption
            .peak_memory_bytes
            .max(peak + state.child_observed_memory);
        if increase != 0 {
            self.propagate_memory(increase, true);
        }
    }
    fn propagate_memory(&self, bytes: u64, increase: bool) {
        let Some(parent) = self
            .inner
            .lineage
            .get()
            .and_then(|lineage| lineage.parent.as_ref())
        else {
            return;
        };
        parent.parent().observe_child_memory(bytes, increase);
    }
    fn observe_child_memory(&self, bytes: u64, increase: bool) {
        // Locks only follow child -> ancestor, never the reverse. The fixed
        // depth bound also bounds this synchronous observation and lock chain.
        let mut state = self.lock_state();
        if increase {
            state.child_observed_memory += bytes;
        } else {
            state.child_observed_memory -= bytes;
        }
        debug_assert!(state.child_observed_memory <= state.child_reserved_memory);
        let observed = state.own_memory_peak + state.child_observed_memory;
        state.consumption.peak_memory_bytes = state.consumption.peak_memory_bytes.max(observed);
        self.propagate_memory(bytes, increase);
    }
}
impl ParentReservation {
    pub(super) fn release_memory(&mut self, observed: u64) {
        if observed != 0 {
            self.parent().observe_child_memory(observed, false);
        }
        if self.memory != 0 {
            let mut state = self.parent().lock_state();
            state.child_reserved_memory -= self.memory;
            drop(state);
            self.memory = 0;
        }
    }
}
