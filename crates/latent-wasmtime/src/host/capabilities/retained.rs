//! Only the contiguous backing of Store-retained capability directories.
use latent_core::{ActivationBudget, BudgetProfile, HostMemoryReservation, PlatformErrorCode};
use std::alloc::Layout;

// The reservation is inline in the paid HostState/Store Box; it needs no
// separate owner Box. This covers the original backing allocator bookkeeping,
// consistently with the existing codec/context allocation envelope, not RSS.
const ALLOCATION_BOOKKEEPING: usize = 64;

pub(super) struct Retained<T> {
    values: Vec<T>,
    // Actual elements AND the actual Vec backing die before this reservation.
    memory: Option<HostMemoryReservation>,
    budget: Option<ActivationBudget>,
}
impl<T> Default for Retained<T> {
    fn default() -> Self {
        Self {
            values: Vec::new(),
            memory: None,
            budget: None,
        }
    }
}
impl<T> Retained<T> {
    pub(super) fn new(budget: &ActivationBudget) -> Self {
        Self {
            budget: matches!(
                budget.profile(),
                BudgetProfile::Phase3 | BudgetProfile::Phase4
            )
            .then(|| budget.clone()),
            ..Self::default()
        }
    }

    /// No owner/value is consumed on failure. Call only after original
    /// authorization/validation, before building the corresponding guest DTO.
    pub(super) fn prepare_one(&mut self) -> wasmtime::Result<()> {
        let Some(budget) = &self.budget else {
            // Phase1 retains its original Vec::push allocation timing/growth.
            return Ok(());
        };
        let required = self.values.len().checked_add(1).ok_or_else(overflow)?;
        if required <= self.values.capacity() || size_of::<T>() == 0 {
            return Ok(());
        }
        let capacity = required.checked_next_power_of_two().unwrap_or(required);
        let layout = Layout::array::<T>(capacity).map_err(|_| overflow())?;
        let bytes = layout
            .size()
            .checked_add(ALLOCATION_BOOKKEEPING)
            .and_then(|n| u64::try_from(n).ok())
            .ok_or_else(overflow)?;
        // Full new backing admission while ALL old capacity remains live.
        // Preserve the original typed BudgetError and its exact metadata.
        let memory = budget
            .reserve_host_memory(bytes)
            .map_err(wasmtime::Error::new)?;
        let mut replacement = Self {
            // Pinned Rust1.97.1 Global Vec/RawVec uses this exact nonzero
            // Layout/capacity (the same construction as exact context pairs).
            // This is not a reserve_exact followed by an unknown growth bound.
            values: Vec::with_capacity(capacity),
            memory: Some(memory),
            budget: self.budget.clone(),
        };
        debug_assert_eq!(replacement.values.capacity(), capacity);
        // Attach fields before confirmation, including its unwind cleanup.
        replacement.memory.as_mut().unwrap().confirm();
        let old = std::mem::replace(self, replacement);
        let old = OwningIter {
            values: old.values.into_iter(),
            _memory: old.memory,
            _budget: old.budget,
        };
        for value in old {
            // Capacity was already admitted and allocated. No user callback,
            // await, cloning, or reallocation occurs during these moves.
            self.values.push(value);
        }
        Ok(())
    }

    /// The caller has completed prepare_one without an intervening await or
    /// reentrant callback. Selected execution has no unaccounted fallback.
    pub(super) fn push_prepared(&mut self, value: T) {
        assert!(
            self.budget.is_none()
                || self.values.len() < self.values.capacity()
                || size_of::<T>() == 0
        );
        self.values.push(value);
    }
}
struct OwningIter<T> {
    values: std::vec::IntoIter<T>,
    // Vec::IntoIter retains its backing even after its last element is moved.
    _memory: Option<HostMemoryReservation>,
    _budget: Option<ActivationBudget>,
}
impl<T> Iterator for OwningIter<T> {
    type Item = T;
    fn next(&mut self) -> Option<T> {
        self.values.next()
    }
}
fn overflow() -> wasmtime::Error {
    super::host_error(crate::containment::platform_error(
        PlatformErrorCode::ResourceExhausted,
        "capability-lowering-directory-capacity",
        false,
    ))
}

#[cfg(test)]
mod tests;
