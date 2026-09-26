use super::{
    capacity, denied, ActivationBudget, Arc, AtomicUsize, BudgetDimension, BudgetProfile,
    CapacityClaim, ChildBudgetDelegation, ClockSample, EffectiveActivationBudget, Lineage,
    Ordering, ParentReservation, PlatformError, ResourceBudget,
};
use crate::IncomingDeadline;

impl ActivationBudget {
    /// Reserve an intersected child grant before normal node admission. No cell,
    /// worker, queue or execution authority is created by this operation.
    pub fn delegate_at(
        &self,
        request: &ResourceBudget,
        deployment: &ResourceBudget,
        node: &ResourceBudget,
        incoming: Option<&IncomingDeadline>,
        sample: ClockSample,
    ) -> Result<ChildBudgetDelegation, PlatformError> {
        self.check_delegation(sample.monotonic())?;
        let lineage = self.inner.lineage.get().ok_or_else(denied)?;
        if lineage.depth >= lineage.tree.limits.maximum_depth {
            return Err(capacity());
        }
        let mut remaining = self.remaining_at(sample.monotonic());
        remaining.child_calls = remaining.child_calls.checked_sub(1).ok_or_else(capacity)?;
        let ceiling = node.intersect(&remaining);
        let parent_deadline = self.deadline().monotonic().ok_or_else(denied)?;
        let parent_unix = self.deadline().unix_millis().ok_or_else(denied)?;
        let incoming = incoming
            .filter(|d| d.monotonic() < parent_deadline)
            .copied()
            .unwrap_or_else(|| IncomingDeadline::new(parent_deadline, parent_unix));
        let grant = EffectiveActivationBudget::admit_profile_with_deadline_at(
            BudgetProfile::Phase3,
            request,
            deployment,
            &ceiling,
            &incoming,
            sample,
        )
        .map_err(|e| e.to_platform_error())?;
        grant
            .require_executable_capacity()
            .map_err(|e| e.to_platform_error())?;
        let capacity = CapacityClaim::acquire(self, lineage)?;
        let mut charges = [(BudgetDimension::CpuFuel, 0); 9];
        let mut charge_count = 0;
        for dimension in BudgetDimension::CUMULATIVE {
            let mut amount = grant.budget.limit_for(dimension);
            if dimension == BudgetDimension::ChildCalls {
                amount += 1;
            }
            if amount != 0 {
                charges[charge_count] = (dimension, amount);
                charge_count += 1;
            }
        }
        let cumulative = self
            .reserve_group(&charges[..charge_count])
            .map_err(|e| e.to_platform_error())?;
        let mut parent = ParentReservation {
            capacity,
            cumulative: Some(cumulative),
            memory: 0,
            accepted: false,
        };
        self.reserve_child_memory(grant.budget.memory_bytes)
            .map_err(|e| e.to_platform_error())?;
        parent.memory = grant.budget.memory_bytes;
        self.check_delegation(sample.monotonic())?;
        let budget = ActivationBudget::with_profile(grant, BudgetProfile::Phase3)
            .map_err(|e| e.to_platform_error())?;
        budget
            .inner
            .lineage
            .set(Lineage {
                tree: Arc::clone(&lineage.tree),
                depth: lineage.depth + 1,
                live_children: AtomicUsize::new(0),
                cancellation: Arc::clone(&lineage.cancellation),
                parent: Some(parent),
            })
            .expect("private new child ledger");
        Ok(ChildBudgetDelegation {
            budget: Some(budget),
        })
    }
}
impl CapacityClaim {
    fn acquire(parent: &ActivationBudget, lineage: &Lineage) -> Result<Self, PlatformError> {
        let increment = |counter: &AtomicUsize, maximum: usize| {
            counter
                .fetch_update(Ordering::AcqRel, Ordering::Acquire, |n| {
                    (n < maximum).then_some(n + 1)
                })
                .map(|_| ())
                .map_err(|_| capacity())
        };
        increment(
            &lineage.live_children,
            usize::from(lineage.tree.limits.maximum_live_children),
        )?;
        if let Err(error) = increment(
            &lineage.tree.live,
            usize::from(lineage.tree.limits.maximum_live_descendants),
        ) {
            lineage.live_children.fetch_sub(1, Ordering::AcqRel);
            return Err(error);
        }
        Ok(Self {
            parent: parent.clone(),
            tree: Arc::clone(&lineage.tree),
        })
    }
}
impl Drop for CapacityClaim {
    fn drop(&mut self) {
        self.parent
            .inner
            .lineage
            .get()
            .expect("configured parent")
            .live_children
            .fetch_sub(1, Ordering::AcqRel);
        self.tree.live.fetch_sub(1, Ordering::AcqRel);
    }
}
