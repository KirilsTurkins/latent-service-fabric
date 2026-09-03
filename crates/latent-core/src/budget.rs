//! Hierarchical invocation resource budgets.

/// Maximum resources delegated to an activation and its descendants.
///
/// Every numeric member is an exact hard ceiling: zero means that no amount of
/// that resource is granted.  It never means "use a default".  This makes the
/// same value safe to use in an invocation request, a deployment ceiling, and
/// a node ceiling.
///
/// `wall_time_limit_millis` is deliberately relative.  It is measured from
/// admission/grant, never from deployment creation or document parsing.  A
/// missing value adds no wall-time constraint; `Some(0)` grants no wall time.
/// An invocation's caller-supplied absolute deadline is carried separately by
/// the invocation envelope and is combined with these relative limits by
/// [`ResourceBudget::effective_deadline_unix_millis`].
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ResourceBudget {
    pub cpu_fuel: u64,
    pub memory_bytes: u64,
    pub wall_time_limit_millis: Option<u64>,
    pub child_calls: u32,
    pub outbound_requests: u32,
    pub state_read_bytes: u64,
    pub state_write_bytes: u64,
    pub blob_read_bytes: u64,
    pub blob_write_bytes: u64,
    pub log_bytes: u64,
    pub effect_count: u32,
}

impl ResourceBudget {
    /// Returns the strict intersection of two independently granted budgets.
    ///
    /// The caller must pass only concrete grants/ceilings.  `None` for a
    /// relative wall-time limit means that particular layer is unconstrained;
    /// all other dimensions are always exact numeric ceilings.
    #[must_use]
    pub fn intersect(&self, ceiling: &Self) -> Self {
        Self {
            cpu_fuel: self.cpu_fuel.min(ceiling.cpu_fuel),
            memory_bytes: self.memory_bytes.min(ceiling.memory_bytes),
            wall_time_limit_millis: minimum_optional(
                self.wall_time_limit_millis,
                ceiling.wall_time_limit_millis,
            ),
            child_calls: self.child_calls.min(ceiling.child_calls),
            outbound_requests: self.outbound_requests.min(ceiling.outbound_requests),
            state_read_bytes: self.state_read_bytes.min(ceiling.state_read_bytes),
            state_write_bytes: self.state_write_bytes.min(ceiling.state_write_bytes),
            blob_read_bytes: self.blob_read_bytes.min(ceiling.blob_read_bytes),
            blob_write_bytes: self.blob_write_bytes.min(ceiling.blob_write_bytes),
            log_bytes: self.log_bytes.min(ceiling.log_bytes),
            effect_count: self.effect_count.min(ceiling.effect_count),
        }
    }

    /// Computes the absolute deadline used after admission.
    ///
    /// The result is the earliest of the caller's explicit absolute deadline
    /// and each relative wall-time limit measured from `admitted_at_unix_millis`.
    /// Passing no caller deadline and no relative limits returns `None`.
    #[must_use]
    pub fn effective_deadline_unix_millis<'a>(
        admitted_at_unix_millis: u64,
        caller_deadline_unix_millis: Option<u64>,
        limits: impl IntoIterator<Item = &'a Self>,
    ) -> Option<u64> {
        limits
            .into_iter()
            .filter_map(|budget| {
                budget
                    .wall_time_limit_millis
                    .map(|limit| admitted_at_unix_millis.saturating_add(limit))
            })
            .fold(caller_deadline_unix_millis, |effective, candidate| {
                Some(effective.map_or(candidate, |current| current.min(candidate)))
            })
    }
}

fn minimum_optional(first: Option<u64>, second: Option<u64>) -> Option<u64> {
    match (first, second) {
        (Some(first), Some(second)) => Some(first.min(second)),
        (Some(value), None) | (None, Some(value)) => Some(value),
        (None, None) => None,
    }
}

/// Resources consumed by a completed or interrupted activation.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct BudgetConsumption {
    pub cpu_fuel: u64,
    pub peak_memory_bytes: u64,
    pub wall_time_micros: u64,
    pub child_calls: u32,
    pub outbound_requests: u32,
    pub state_read_bytes: u64,
    pub state_write_bytes: u64,
    pub blob_read_bytes: u64,
    pub blob_write_bytes: u64,
    pub log_bytes: u64,
    pub effect_count: u32,
}

#[cfg(test)]
mod tests {
    use super::*;

    fn budget(wall_time_limit_millis: Option<u64>) -> ResourceBudget {
        ResourceBudget {
            cpu_fuel: 10,
            memory_bytes: 20,
            wall_time_limit_millis,
            child_calls: 30,
            outbound_requests: 40,
            state_read_bytes: 50,
            state_write_bytes: 60,
            blob_read_bytes: 70,
            blob_write_bytes: 80,
            log_bytes: 90,
            effect_count: 100,
        }
    }

    #[test]
    fn intersection_uses_the_strictest_ceiling_without_default_zeroes() {
        let requested = budget(None);
        let mut deployment = budget(Some(250));
        deployment.cpu_fuel = 8;
        deployment.memory_bytes = 16;
        deployment.effect_count = 75;

        let granted = requested.intersect(&deployment);

        assert_eq!(granted.cpu_fuel, 8);
        assert_eq!(granted.memory_bytes, 16);
        assert_eq!(granted.effect_count, 75);
        assert_eq!(granted.wall_time_limit_millis, Some(250));
    }

    #[test]
    fn effective_deadline_combines_caller_and_relative_ceilings() {
        let request = budget(Some(500));
        let deployment = budget(Some(250));
        let node = budget(None);

        assert_eq!(
            ResourceBudget::effective_deadline_unix_millis(
                1_000,
                Some(1_400),
                [&request, &deployment, &node],
            ),
            Some(1_250)
        );
    }

    #[test]
    fn a_zero_relative_limit_is_not_an_unspecified_default() {
        let zero = budget(Some(0));
        assert_eq!(
            ResourceBudget::effective_deadline_unix_millis(1_000, None, [&zero]),
            Some(1_000)
        );
    }
}
