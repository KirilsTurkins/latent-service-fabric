use super::{
    BudgetConsumption, BudgetDimension, BudgetError, ClockSample, EffectiveActivationBudget,
    IncomingDeadline, ResourceBudget,
};

/// Node-selected accounting support, independent of caller-supplied amounts.
/// Existing constructors and configuration retain the Phase 1 profile.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub enum BudgetProfile {
    #[default]
    Phase1,
    Phase3,
}
impl BudgetProfile {
    #[must_use]
    pub const fn supports(self, dimension: BudgetDimension) -> bool {
        dimension.is_phase1_enforced()
            || matches!(
                (self, dimension),
                (
                    Self::Phase3,
                    BudgetDimension::ChildCalls
                        | BudgetDimension::OutboundRequests
                        | BudgetDimension::BlobReadBytes
                        | BudgetDimension::BlobWriteBytes
                )
            )
    }
    pub fn validate_request(self, budget: &ResourceBudget) -> Result<(), BudgetError> {
        for dimension in BudgetDimension::LATER_PHASE {
            let value = budget.limit_for(dimension);
            if !self.supports(dimension) && value != 0 {
                return Err(BudgetError::UnsupportedRequestDimension { dimension, value });
            }
        }
        Ok(())
    }
    pub fn effective(
        self,
        request: &ResourceBudget,
        deployment: &ResourceBudget,
        node: &ResourceBudget,
    ) -> Result<ResourceBudget, BudgetError> {
        self.validate_request(request)?;
        let mut effective = request.intersect(deployment).intersect(node);
        if self == Self::Phase1 {
            effective.zero_later_phase_dimensions();
        } else {
            effective.state_read_bytes = 0;
            effective.state_write_bytes = 0;
            effective.effect_count = 0;
        }
        Ok(effective)
    }
    pub fn validate_report(
        self,
        report: &BudgetConsumption,
        granted: &ResourceBudget,
    ) -> Result<(), BudgetError> {
        if self == Self::Phase1 {
            return report.validate_phase1_report(granted);
        }
        for dimension in BudgetDimension::CUMULATIVE
            .into_iter()
            .chain([BudgetDimension::MemoryBytes])
        {
            let value = report.consumed(dimension);
            if !self.supports(dimension) && value != 0 {
                return Err(BudgetError::UnsupportedConsumptionDimension { dimension, value });
            }
            let limit = granted.limit_for(dimension);
            if value > limit {
                return Err(BudgetError::exhausted(dimension, limit, value, 0));
            }
        }
        Ok(())
    }
}
impl EffectiveActivationBudget {
    /// Uses the existing deadline calculation with an explicitly selected set
    /// of enforced counters. The numeric grant remains a descriptive value.
    pub fn admit_profile_at(
        profile: BudgetProfile,
        request: &ResourceBudget,
        deployment: &ResourceBudget,
        node: &ResourceBudget,
        caller_deadline_unix_millis: Option<u64>,
        sample: ClockSample,
    ) -> Result<Self, BudgetError> {
        let budget = profile.effective(request, deployment, node)?;
        let mut timing = budget.clone();
        timing.zero_later_phase_dimensions();
        let mut grant = Self::admit_at(
            &timing,
            &timing,
            &timing,
            caller_deadline_unix_millis,
            sample,
        )?;
        grant.budget = budget;
        Ok(grant)
    }
    /// Preserves an incoming monotonic deadline through Phase 3 admission.
    pub fn admit_profile_with_deadline_at(
        profile: BudgetProfile,
        request: &ResourceBudget,
        deployment: &ResourceBudget,
        node: &ResourceBudget,
        incoming: &IncomingDeadline,
        sample: ClockSample,
    ) -> Result<Self, BudgetError> {
        let budget = profile.effective(request, deployment, node)?;
        let mut timing = budget.clone();
        timing.zero_later_phase_dimensions();
        let mut grant = Self::admit_with_deadline_at(&timing, &timing, &timing, incoming, sample)?;
        grant.budget = budget;
        Ok(grant)
    }
}

#[cfg(test)]
mod tests;

pub(super) fn closed_budget() -> ResourceBudget {
    ResourceBudget {
        cpu_fuel: 0,
        memory_bytes: 0,
        wall_time_limit_millis: Some(0),
        child_calls: 0,
        outbound_requests: 0,
        state_read_bytes: 0,
        state_write_bytes: 0,
        blob_read_bytes: 0,
        blob_write_bytes: 0,
        log_bytes: 0,
        effect_count: 0,
    }
}

impl super::ActivationBudget {
    /// Backend reports contain that execution's own guest CPU/memory. Child and
    /// provider counters are already conserved by the shared host ledgers.
    pub(super) fn reconcile_phase3_report(
        &self,
        state: &mut super::AccountingState,
        report: &BudgetConsumption,
    ) -> Result<(), BudgetError> {
        let own_cpu =
            state.consumption.cpu_fuel - state.reserved.cpu_fuel - state.child_consumption.cpu_fuel;
        self.consume_locked(
            state,
            BudgetDimension::CpuFuel,
            report.cpu_fuel.saturating_sub(own_cpu),
        )?;
        self.check_owned_memory(state, report.peak_memory_bytes)?;
        self.record_owned_memory(state, report.peak_memory_bytes);
        Ok(())
    }
}
