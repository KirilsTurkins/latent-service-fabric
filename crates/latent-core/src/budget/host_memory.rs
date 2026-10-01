//! Native allocation ownership in the original activation ledger. Linear
//! memory observations exclude these bytes, so neither path charges them twice.
use super::{ActivationBudget, BudgetDimension, BudgetError, BudgetProfile};

/// Affine capacity reserved before a native allocation. Call `confirm` only
/// after allocation succeeds; retain this guard with the actual allocation,
/// including a quarantined owner. Dropping an awaiter is not retirement.
#[derive(Debug)]
#[must_use = "retain with the actual native allocation"]
pub struct HostMemoryReservation {
    budget: ActivationBudget,
    bytes: u64,
    confirmed: bool,
}

impl ActivationBudget {
    pub fn reserve_host_memory(&self, bytes: u64) -> Result<HostMemoryReservation, BudgetError> {
        let transaction = self.profile() == BudgetProfile::Phase4;
        if !matches!(
            self.profile(),
            BudgetProfile::Phase3 | BudgetProfile::Phase4
        ) || (transaction && (bytes == 0 || self.has_budget_parent()))
        {
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
        if bytes > self.granted().memory_bytes.saturating_sub(occupied) {
            return Err(BudgetError::Exhausted {
                dimension: BudgetDimension::MemoryBytes,
                limit: self.granted().memory_bytes,
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
        if transaction {
            // The transaction host prepays its finite native working set.
            // Preserve that original Phase 4 observation while Phase 3 runtime
            // allocations remain explicitly confirmed after allocation.
            state.host_observed_memory += bytes;
            let observed =
                state.own_memory_peak + state.host_observed_memory + state.child_observed_memory;
            state.consumption.peak_memory_bytes = state.consumption.peak_memory_bytes.max(observed);
        }
        Ok(HostMemoryReservation {
            budget: self.clone(),
            bytes,
            confirmed: transaction,
        })
    }

    /// Outstanding native capacity, including allocation preparations. This
    /// observation creates no new allowance or authority.
    #[must_use]
    pub fn host_memory_bytes(&self) -> u64 {
        self.lock_state().host_reserved_memory
    }
}

impl HostMemoryReservation {
    pub fn confirm(&mut self) {
        if self.confirmed {
            return;
        }
        let mut state = self.budget.lock_state();
        state.host_observed_memory += self.bytes;
        let observed =
            state.own_memory_peak + state.host_observed_memory + state.child_observed_memory;
        state.consumption.peak_memory_bytes = state.consumption.peak_memory_bytes.max(observed);
        self.budget.propagate_memory(self.bytes, true);
        self.confirmed = true;
    }
}

impl Drop for HostMemoryReservation {
    fn drop(&mut self) {
        let mut state = self.budget.lock_state();
        state.host_reserved_memory -= self.bytes;
        state.outstanding_reservations -= 1;
        if self.confirmed {
            state.host_observed_memory -= self.bytes;
            self.budget.propagate_memory(self.bytes, false);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{ClockSample, EffectiveActivationBudget, ResourceBudget};
    use std::time::Instant;

    fn budget() -> ActivationBudget {
        let limits = ResourceBudget {
            cpu_fuel: 100,
            memory_bytes: 1000,
            wall_time_limit_millis: Some(1000),
            child_calls: 0,
            outbound_requests: 0,
            state_read_bytes: 0,
            state_write_bytes: 0,
            blob_read_bytes: 0,
            blob_write_bytes: 0,
            log_bytes: 0,
            effect_count: 0,
        };
        let grant = EffectiveActivationBudget::admit_profile_at(
            BudgetProfile::Phase3,
            &limits,
            &limits,
            &limits,
            None,
            ClockSample::new(1000, Instant::now()),
        )
        .unwrap();
        ActivationBudget::with_profile(grant, BudgetProfile::Phase3).unwrap()
    }

    #[test]
    fn native_and_linear_memory_compete_before_allocation_and_failed_preparations_roll_back() {
        let budget = budget();
        budget.observe_peak_memory(600).unwrap();
        let pending = budget.reserve_host_memory(400).unwrap();
        assert_eq!(budget.remaining_at(Instant::now()).memory_bytes, 0);
        assert!(budget.reserve_runtime_memory(601).is_err());
        assert!(budget.reserve_host_memory(1).is_err());
        assert_eq!(budget.snapshot_at(Instant::now()).peak_memory_bytes, 600);
        drop(pending);
        assert_eq!(budget.remaining_at(Instant::now()).memory_bytes, 400);
        assert_eq!(budget.host_memory_bytes(), 0);
    }

    #[test]
    fn actual_native_owner_keeps_capacity_after_terminal_report_and_settles_once() {
        let budget = budget();
        let mut owner = budget.reserve_host_memory(250).unwrap();
        owner.confirm();
        owner.confirm();
        budget.observe_peak_memory(600).unwrap();
        let terminal = budget.finalize_at(None, Instant::now());
        assert_eq!(terminal.consumption().peak_memory_bytes, 850);
        assert_eq!(budget.host_memory_bytes(), 250);
        assert!(budget.reserve_host_memory(1).is_err());
        drop(owner);
        assert_eq!(budget.host_memory_bytes(), 0);
        assert_eq!(budget.finalize_at(None, Instant::now()), terminal);
    }
}
