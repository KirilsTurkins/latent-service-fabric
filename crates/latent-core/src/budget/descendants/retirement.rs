use super::{
    AccountingState, ActivationBudgetInner, BudgetDimension, ParentReservation, ResourceBudget,
};

impl ParentReservation {
    fn retire(&mut self, state: &AccountingState, grant: &ResourceBudget) {
        if let Some(cumulative) = self.cumulative.take() {
            if self.accepted {
                let mut used = state.consumption.clone();
                if state
                    .finalized
                    .as_ref()
                    .is_none_or(|f| f.violation().is_some())
                {
                    // Missing or invalid completion accounting cannot establish
                    // unused capacity. Consume the accepted grant conservatively.
                    for dimension in BudgetDimension::CUMULATIVE {
                        used.set_consumed(dimension, grant.limit_for(dimension));
                    }
                }
                used.child_calls = used
                    .child_calls
                    .checked_add(1)
                    .expect("reserved call plus child ceiling");
                let _ = cumulative.settle_descendant(&used);
            } else {
                let _ = cumulative.refund();
            }
        }
        debug_assert_eq!(state.child_reserved_memory, 0);
        debug_assert_eq!(state.child_observed_memory, 0);
        self.release_memory(state.own_memory_peak);
    }
}
impl Drop for ParentReservation {
    fn drop(&mut self) {
        // Only a never-admitted preparation can reach this fallback with a
        // reservation. Real child ledgers retire through their final Arc below.
        if let Some(cumulative) = self.cumulative.take() {
            if self.accepted {
                let _ = cumulative.commit();
            } else {
                let _ = cumulative.refund();
            }
        }
        self.release_memory(0);
    }
}
impl Drop for ActivationBudgetInner {
    fn drop(&mut self) {
        let state = self
            .state
            .get_mut()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if let Some(parent) = self
            .lineage
            .get_mut()
            .and_then(|lineage| lineage.parent.as_mut())
        {
            parent.retire(state, &self.granted);
        }
    }
}
