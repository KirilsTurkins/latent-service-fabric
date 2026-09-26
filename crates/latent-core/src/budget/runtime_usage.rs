use super::{ActivationBudget, BudgetDimension, BudgetError};

impl ActivationBudget {
    /// Records a runtime fuel delta and confirmed memory peak in one transaction.
    ///
    /// Finalization, an invalid memory peak, fuel overflow or fuel exhaustion
    /// leaves both counters unchanged. Existing provisional reservations and
    /// log accounting retain their original commit/refund semantics. Callers
    /// advance their runtime observation watermarks only after success.
    pub fn observe_runtime_usage(
        &self,
        fuel_delta: u64,
        confirmed_peak: u64,
    ) -> Result<(), BudgetError> {
        let mut state = self.lock_state();
        Self::ensure_mutable(&state)?;
        self.check_owned_memory(&state, confirmed_peak)?;
        self.consume_locked(&mut state, BudgetDimension::CpuFuel, fuel_delta)?;
        self.record_owned_memory(&mut state, confirmed_peak);
        Ok(())
    }
}

#[cfg(test)]
mod tests;
