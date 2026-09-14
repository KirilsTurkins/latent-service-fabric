//! Atomic, affine reservation of the finite cumulative budget dimensions.
use super::{ActivationBudget, BudgetDimension, BudgetError};

/// One original-ledger reservation. A failed multi-dimension admission changes
/// no counter; commit/refund applies to the whole group under one state lock.
#[must_use = "retain until admission, then commit or refund the complete group"]
pub struct BudgetReservationGroup {
    budget: ActivationBudget,
    charges: [Option<(BudgetDimension, u64)>; 9],
    active: bool,
}
impl ActivationBudget {
    pub fn reserve_group(
        &self,
        charges: &[(BudgetDimension, u64)],
    ) -> Result<BudgetReservationGroup, BudgetError> {
        if charges.is_empty() || charges.len() > 9 {
            return Err(BudgetError::InvalidAccountingOperation {
                dimension: BudgetDimension::CpuFuel,
            });
        }
        let mut normalized = [None; 9];
        for &(dimension, amount) in charges {
            let Some(index) = BudgetDimension::CUMULATIVE
                .iter()
                .position(|d| *d == dimension)
            else {
                return Err(BudgetError::InvalidAccountingOperation { dimension });
            };
            if normalized[index].is_some() || amount == 0 {
                return Err(BudgetError::InvalidAccountingOperation { dimension });
            }
            normalized[index] = Some((dimension, amount));
        }
        let mut state = self.lock_state();
        Self::ensure_mutable(&state)?;
        let count = state.outstanding_reservations.checked_add(1).ok_or(
            BudgetError::ArithmeticOverflow {
                dimension: BudgetDimension::CpuFuel,
            },
        )?;
        let mut consumption = state.consumption.clone();
        let mut reserved = state.reserved.clone();
        for &(dimension, amount) in normalized.iter().flatten() {
            let current = consumption.consumed(dimension);
            let next = current
                .checked_add(amount)
                .ok_or(BudgetError::ArithmeticOverflow { dimension })?;
            let limit = self.granted().limit_for(dimension);
            if next > limit {
                return Err(BudgetError::Exhausted {
                    dimension,
                    limit,
                    consumed: current,
                    requested: amount,
                });
            }
            consumption.set_consumed(dimension, next);
            reserved.set_consumed(
                dimension,
                reserved
                    .consumed(dimension)
                    .checked_add(amount)
                    .ok_or(BudgetError::ArithmeticOverflow { dimension })?,
            );
        }
        state.consumption = consumption;
        state.reserved = reserved;
        state.outstanding_reservations = count;
        Ok(BudgetReservationGroup {
            budget: self.clone(),
            charges: normalized,
            active: true,
        })
    }
}
impl BudgetReservationGroup {
    pub fn commit(mut self) -> Result<(), BudgetError> {
        self.close(false)
    }
    pub fn refund(mut self) -> Result<(), BudgetError> {
        self.close(true)
    }
    fn close(&mut self, refund: bool) -> Result<(), BudgetError> {
        if !self.active {
            return Ok(());
        }
        let mut state = self.budget.lock_state();
        self.active = false;
        if state.finalized.is_some() {
            return Err(BudgetError::AccountingFinalized);
        }
        for &(dimension, amount) in self.charges.iter().flatten() {
            let reserved = state.reserved.consumed(dimension);
            state.reserved.set_consumed(dimension, reserved - amount);
            if refund {
                let consumed = state.consumption.consumed(dimension);
                state.consumption.set_consumed(dimension, consumed - amount);
            }
        }
        state.outstanding_reservations -= 1;
        Ok(())
    }
}
impl Drop for BudgetReservationGroup {
    fn drop(&mut self) {
        let _ = self.close(true);
    }
}
