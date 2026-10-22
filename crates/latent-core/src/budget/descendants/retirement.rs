use super::{
    AccountingState, ActivationBudgetInner, BudgetDimension, ParentReservation, ResourceBudget,
};

impl ParentReservation {
    fn settle_cumulative(&self, state: &AccountingState, grant: &ResourceBudget) {
        // Take once, then release this mutex before following child -> parent
        // accounting locks or dropping the ordinary parent reservation owner.
        let cumulative = self
            .cumulative
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .take();
        if let Some(cumulative) = cumulative {
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
    }
    fn retire_memory(&mut self, state: &AccountingState) {
        debug_assert_eq!(state.child_reserved_memory, 0);
        debug_assert_eq!(state.child_observed_memory, 0);
        debug_assert_eq!(state.host_reserved_memory, 0);
        debug_assert_eq!(state.host_observed_memory, 0);
        self.release_memory(state.own_memory_peak);
    }
}
impl Drop for ParentReservation {
    fn drop(&mut self) {
        // A never-admitted preparation may still own this fallback group.
        // Accepted cumulative groups settle at the final ordinary owner;
        // physical memory/capacity retires only with the final Inner Arc.
        if let Some(cumulative) = self
            .cumulative
            .get_mut()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .take()
        {
            if self.accepted {
                let _ = cumulative.commit();
            } else {
                let _ = cumulative.refund();
            }
        }
        self.release_memory(0);
    }
}
impl ActivationBudgetInner {
    pub(in crate::budget) fn settle_parent_cumulative(&self) {
        if let Some(parent) = self
            .lineage
            .get()
            .and_then(|lineage| lineage.parent.as_ref())
        {
            let state = self.lock_state();
            parent.settle_cumulative(&state, &self.granted);
        }
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
            parent.settle_cumulative(state, &self.granted);
            parent.retire_memory(state);
        }
    }
}
