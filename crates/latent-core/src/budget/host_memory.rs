//! Native allocation ownership in the original activation ledger. Linear
//! memory observations exclude these bytes, so neither path charges them twice.
use super::{
    AccountingState, ActivationBudget, ActivationBudgetInner, BudgetDimension, BudgetError,
    BudgetProfile, ResourceBudget,
};
use std::sync::{Arc, MutexGuard};

/// Private physical-memory retention of the SAME original accounting state.
/// It cannot consume, finalize, delegate or create an ordinary budget owner.
#[derive(Debug)]
pub(super) struct HostMemoryAccounting {
    pub(super) inner: Arc<ActivationBudgetInner>,
}
impl HostMemoryAccounting {
    pub(super) fn new(budget: &ActivationBudget) -> Self {
        Self {
            inner: Arc::clone(&budget.inner),
        }
    }
    fn lock_state(&self) -> MutexGuard<'_, AccountingState> {
        self.inner.lock_state()
    }
    fn granted(&self) -> &ResourceBudget {
        &self.inner.granted
    }
    fn propagate_memory(&self, bytes: u64, increase: bool) {
        self.inner.propagate_memory(bytes, increase);
    }
    fn is_same_instance(&self, budget: &ActivationBudget) -> bool {
        Arc::ptr_eq(&self.inner, &budget.inner)
    }
}
// Keep every existing native reservation and billing Arc layout unchanged.
const _: () =
    assert!(std::mem::size_of::<HostMemoryAccounting>() == std::mem::size_of::<ActivationBudget>());
const _: () = assert!(
    std::mem::align_of::<HostMemoryAccounting>() == std::mem::align_of::<ActivationBudget>()
);

/// Affine capacity reserved before a native allocation. Call `confirm` only
/// after allocation succeeds; retain this guard with the actual allocation,
/// including a quarantined owner. Dropping an awaiter is not retirement.
#[derive(Debug)]
#[must_use = "retain with the actual native allocation"]
pub struct HostMemoryReservation {
    budget: HostMemoryAccounting,
    bytes: u64,
    confirmed_bytes: u64,
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
            budget: HostMemoryAccounting::new(self),
            bytes,
            confirmed_bytes: if transaction { bytes } else { 0 },
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
    #[must_use]
    pub fn is_from_budget(&self, budget: &ActivationBudget) -> bool {
        self.budget.is_same_instance(budget)
    }

    /// Reserved capacity, including storage whose allocation has not completed.
    #[must_use]
    pub fn bytes(&self) -> u64 {
        self.bytes
    }

    /// Reserve additional capacity before allocation, without allocating a
    /// collection of guards. Existing confirmed storage stays charged while a
    /// replacement is allocated; callers include both capacities during growth.
    pub fn grow(&mut self, additional: u64) -> Result<(), BudgetError> {
        if additional == 0 {
            return Ok(());
        }
        let mut state = self.budget.lock_state();
        ActivationBudget::ensure_mutable(&state)?;
        let occupied = state
            .own_memory_peak
            .max(state.pending_runtime_memory.unwrap_or(0))
            + state.child_reserved_memory
            + state.host_reserved_memory;
        if additional > self.budget.granted().memory_bytes.saturating_sub(occupied) {
            return Err(BudgetError::Exhausted {
                dimension: BudgetDimension::MemoryBytes,
                limit: self.budget.granted().memory_bytes,
                consumed: occupied,
                requested: additional,
            });
        }
        self.bytes = self
            .bytes
            .checked_add(additional)
            .ok_or(BudgetError::ArithmeticOverflow {
                dimension: BudgetDimension::MemoryBytes,
            })?;
        state.host_reserved_memory += additional;
        Ok(())
    }

    /// Release only capacity whose storage is already gone (or never allocated).
    /// Peak consumption remains monotonic, including replacement overlap.
    pub fn shrink(&mut self, bytes: u64) {
        assert!(
            bytes <= self.bytes,
            "native memory reservation cannot grow on shrink"
        );
        let mut state = self.budget.lock_state();
        state.host_reserved_memory -= self.bytes - bytes;
        self.bytes = bytes;
        if self.confirmed_bytes > bytes {
            let released = self.confirmed_bytes - bytes;
            state.host_observed_memory -= released;
            self.budget.propagate_memory(released, false);
            self.confirmed_bytes = bytes;
        }
    }

    /// Retire an observed allocation only after its physical storage is gone.
    /// Its original envelope capacity remains reserved for later owned copies;
    /// this creates no allowance and cannot lower the monotonic memory peak.
    pub fn retire_confirmed_bytes(&mut self, bytes: u64) {
        assert!(
            bytes <= self.confirmed_bytes,
            "native retirement exceeds confirmed physical storage"
        );
        if bytes == 0 {
            return;
        }
        let mut state = self.budget.lock_state();
        state.host_observed_memory -= bytes;
        self.budget.propagate_memory(bytes, false);
        self.confirmed_bytes -= bytes;
    }

    pub fn confirm(&mut self) {
        self.confirm_bytes(self.bytes);
    }

    /// Confirm storage that actually exists inside a larger pending envelope.
    /// Remaining capacity still competes with every original memory owner.
    pub fn confirm_bytes(&mut self, bytes: u64) {
        assert!(
            bytes <= self.bytes,
            "native confirmation exceeds reserved capacity"
        );
        let newly_confirmed = bytes.saturating_sub(self.confirmed_bytes);
        if newly_confirmed == 0 {
            return;
        }
        let mut state = self.budget.lock_state();
        state.host_observed_memory += newly_confirmed;
        let observed =
            state.own_memory_peak + state.host_observed_memory + state.child_observed_memory;
        state.consumption.peak_memory_bytes = state.consumption.peak_memory_bytes.max(observed);
        self.budget.propagate_memory(newly_confirmed, true);
        self.confirmed_bytes += newly_confirmed;
    }
}

impl Drop for HostMemoryReservation {
    fn drop(&mut self) {
        let mut state = self.budget.lock_state();
        state.host_reserved_memory -= self.bytes;
        state.outstanding_reservations -= 1;
        if self.confirmed_bytes != 0 {
            state.host_observed_memory -= self.confirmed_bytes;
            self.budget.propagate_memory(self.confirmed_bytes, false);
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
        assert_eq!(budget.outstanding_reservations(), 1);
        budget.observe_peak_memory(600).unwrap();
        let report = crate::BudgetConsumption {
            peak_memory_bytes: 600,
            ..crate::BudgetConsumption::default()
        };
        let terminal = budget.finalize_at(Some(&report), Instant::now());
        assert!(terminal.violation().is_none());
        assert_eq!(terminal.consumption().peak_memory_bytes, 850);
        assert_eq!(budget.host_memory_bytes(), 250);
        assert!(budget.reserve_host_memory(1).is_err());
        drop(owner);
        assert_eq!(budget.outstanding_reservations(), 0);
        assert_eq!(budget.host_memory_bytes(), 0);
        assert_eq!(budget.finalize_at(None, Instant::now()), terminal);

        // An aggregate snapshot is not an own-guest report. Strict
        // reconciliation must still reject that double-counted input.
        let duplicate = self::budget();
        let mut native = duplicate.reserve_host_memory(250).unwrap();
        native.confirm();
        duplicate.observe_peak_memory(600).unwrap();
        let aggregate = duplicate.snapshot_at(Instant::now());
        assert_eq!(aggregate.peak_memory_bytes, 850);
        let refused = duplicate.finalize_at(Some(&aggregate), Instant::now());
        assert!(matches!(
            refused.violation(),
            Some(BudgetError::Exhausted {
                dimension: BudgetDimension::MemoryBytes,
                limit: 1000,
                consumed: 850,
                requested: 850,
            })
        ));
        assert_eq!(duplicate.host_memory_bytes(), 250);
        drop(native);
        assert_eq!(duplicate.host_memory_bytes(), 0);
        assert_eq!(duplicate.outstanding_reservations(), 0);
    }

    #[test]
    fn growing_overlap_competes_before_allocation_and_shrink_keeps_peak() {
        let budget = budget();
        budget.observe_peak_memory(100).unwrap();
        let mut memory = budget.reserve_host_memory(300).unwrap();
        memory.confirm();
        assert_eq!(budget.outstanding_reservations(), 1);
        assert!(memory.grow(601).is_err());
        assert_eq!(memory.bytes(), 300);
        assert_eq!(budget.host_memory_bytes(), 300);
        memory.grow(500).unwrap(); // original300 and replacement500 overlap
        assert_eq!(budget.host_memory_bytes(), 800);
        assert!(budget.reserve_runtime_memory(201).is_err());
        memory.confirm();
        memory.shrink(500); // original allocation was actually destroyed
        assert_eq!(budget.host_memory_bytes(), 500);
        assert_eq!(budget.snapshot_at(Instant::now()).peak_memory_bytes, 900);
        memory.confirm();
        drop(memory);
        assert_eq!(budget.host_memory_bytes(), 0);
        assert_eq!(budget.outstanding_reservations(), 0);
        assert_eq!(budget.snapshot_at(Instant::now()).peak_memory_bytes, 900);
    }

    #[test]
    fn failed_pending_replacement_refunds_only_unallocated_capacity() {
        let budget = budget();
        let mut memory = budget.reserve_host_memory(100).unwrap();
        memory.confirm();
        memory.grow(400).unwrap();
        memory.shrink(100); // allocation failed; original100 still exists
        assert_eq!(budget.host_memory_bytes(), 100);
        assert_eq!(budget.snapshot_at(Instant::now()).peak_memory_bytes, 100);
        drop(memory);
        assert_eq!(budget.host_memory_bytes(), 0);
        assert_eq!(budget.outstanding_reservations(), 0);
    }

    #[test]
    fn partial_confirmation_keeps_pending_capacity_without_inventing_allocated_peak() {
        let budget = budget();
        let mut memory = budget.reserve_host_memory(900).unwrap();
        memory.confirm_bytes(10);
        assert_eq!(budget.host_memory_bytes(), 900);
        assert_eq!(budget.snapshot_at(Instant::now()).peak_memory_bytes, 10);
        assert!(budget.reserve_host_memory(101).is_err());
        memory.confirm_bytes(5); // idempotent; never refunds actual live storage
        assert_eq!(budget.snapshot_at(Instant::now()).peak_memory_bytes, 10);
        memory.shrink(20); // pending lifting capacity was not needed
        memory.confirm();
        assert_eq!(budget.snapshot_at(Instant::now()).peak_memory_bytes, 20);
        drop(memory);
        assert_eq!(budget.host_memory_bytes(), 0);
        assert_eq!(budget.outstanding_reservations(), 0);
    }
    #[test]
    fn original_native_envelope_reuses_only_retired_storage_without_refunding_capacity() {
        let budget = budget();
        let mut memory = budget.reserve_host_memory(900).unwrap();
        memory.confirm_bytes(600);
        memory.retire_confirmed_bytes(400);
        assert_eq!(memory.bytes(), 900);
        assert_eq!(memory.confirmed_bytes, 200);
        assert_eq!(budget.host_memory_bytes(), 900);
        assert_eq!(budget.outstanding_reservations(), 1);
        assert!(budget.reserve_host_memory(101).is_err());
        assert_eq!(budget.snapshot_at(Instant::now()).peak_memory_bytes, 600);
        // A later terminal copy is admitted within the SAME original envelope.
        // The remaining live200 overlaps its newly allocated500, not old600.
        memory.confirm_bytes(700);
        assert_eq!(budget.snapshot_at(Instant::now()).peak_memory_bytes, 700);
        memory.retire_confirmed_bytes(700);
        assert_eq!(budget.host_memory_bytes(), 900);
        assert_eq!(memory.confirmed_bytes, 0);
        assert!(budget.reserve_runtime_memory(101).is_err());
        drop(memory);
        assert_eq!(budget.host_memory_bytes(), 0);
        assert_eq!(budget.outstanding_reservations(), 0);
        assert_eq!(budget.snapshot_at(Instant::now()).peak_memory_bytes, 700);
    }

    #[test]
    fn native_envelope_refuses_unobserved_retirement_before_mutating_original_ledger() {
        let budget = budget();
        let mut memory = budget.reserve_host_memory(900).unwrap();
        memory.confirm_bytes(100);
        let rejected = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            memory.retire_confirmed_bytes(101);
        }));
        assert!(rejected.is_err());
        assert_eq!(memory.confirmed_bytes, 100);
        assert_eq!(budget.host_memory_bytes(), 900);
        assert_eq!(budget.outstanding_reservations(), 1);
        assert_eq!(budget.snapshot_at(Instant::now()).peak_memory_bytes, 100);
        memory.retire_confirmed_bytes(100);
        drop(memory);
        assert_eq!(budget.host_memory_bytes(), 0);
        assert_eq!(budget.outstanding_reservations(), 0);
    }
}
