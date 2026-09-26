//! Conserved child reservations on the original activation ledgers. Retained
//! ancestry consists only of bounded accounting and cancellation metadata.
mod admission;
mod memory;
mod retirement;
#[cfg(test)]
mod tests;

use super::{
    AccountingState, ActivationBudget, ActivationBudgetInner, BudgetConsumption, BudgetDimension,
    BudgetFinalization, BudgetProfile, BudgetReservationGroup, ClockSample,
    EffectiveActivationBudget, ResourceBudget,
};
use crate::{PlatformError, PlatformErrorCode};
use std::{
    fmt,
    sync::{
        atomic::{AtomicUsize, Ordering},
        Arc,
    },
    time::Instant,
};

/// A bounded nonblocking probe of the actual execution cancellation owner.
/// It must not retain this budget or its descendants (which would form a cycle).
/// Each accepted ledger needs its own terminal signal, even when cancellation
/// originates from a shared source. Waiters must wake on cancellation or terminal
/// publication; neither operation may acquire an accounting lock or run work.
pub trait BudgetCancellationProbe: Send + Sync {
    fn is_cancelled(&self) -> bool;
    fn cancelled(&self) -> crate::BoxFuture<'_, ()>;
    fn mark_terminal(&self);
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct DelegationLimits {
    pub maximum_depth: u8,
    pub maximum_live_descendants: u16,
    pub maximum_live_children: u16,
}
impl Default for DelegationLimits {
    fn default() -> Self {
        Self {
            maximum_depth: 8,
            maximum_live_descendants: 64,
            maximum_live_children: 8,
        }
    }
}
impl DelegationLimits {
    pub fn validate(self) -> Result<(), PlatformError> {
        if self.maximum_depth == 0
            || self.maximum_depth > 16
            || self.maximum_live_descendants == 0
            || self.maximum_live_descendants > 256
            || self.maximum_live_children == 0
            || self.maximum_live_children > 32
            || self.maximum_live_children > self.maximum_live_descendants
        {
            return Err(failure(
                PlatformErrorCode::InvalidArgument,
                "descendant-limits",
            ));
        }
        Ok(())
    }
}
#[derive(Debug)]
struct Tree {
    limits: DelegationLimits,
    live: AtomicUsize,
}
pub(super) struct Lineage {
    tree: Arc<Tree>,
    depth: u8,
    live_children: AtomicUsize,
    cancellation: Arc<dyn BudgetCancellationProbe>,
    parent: Option<ParentReservation>,
}
impl fmt::Debug for Lineage {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("Lineage")
            .field("depth", &self.depth)
            .field("live_children", &self.live_children)
            .finish_non_exhaustive()
    }
}
impl Lineage {
    pub(super) fn mark_terminal(&self) {
        self.cancellation.mark_terminal();
    }
}
struct CapacityClaim {
    parent: ActivationBudget,
    tree: Arc<Tree>,
}
struct ParentReservation {
    capacity: CapacityClaim,
    cumulative: Option<BudgetReservationGroup>,
    memory: u64,
    accepted: bool,
}
impl ParentReservation {
    fn parent(&self) -> &ActivationBudget {
        &self.capacity.parent
    }
}

/// Affine pre-admission reservation. Its public grant is only descriptive;
/// copying that grant cannot manufacture another accepted child owner.
#[derive(Debug)]
pub struct ChildBudgetDelegation {
    budget: Option<ActivationBudget>,
}
/// Actual child execution retains this owner or its original ledger until all
/// child/provider/result ownership ends. Dropping an awaiter cannot refund it.
#[derive(Debug)]
pub struct ChildBudgetOwner {
    budget: ActivationBudget,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct DescendantBudgetSnapshot {
    pub depth: u8,
    pub live_descendants: usize,
    pub live_children: usize,
    pub reserved_memory_bytes: u64,
    pub live_observed_child_memory_bytes: u64,
    pub closed: bool,
}
impl ActivationBudget {
    /// Wait on at most seventeen original owner signals (root plus depth limit).
    /// The caller owns this future; no task or waiter is retained by the tree.
    pub async fn descendant_cancelled(&self) {
        let mut signals = Vec::new();
        let mut cursor = self;
        for _ in 0..=16 {
            let Some(lineage) = cursor.inner.lineage.get() else {
                return;
            };
            signals.push(lineage.cancellation.cancelled());
            let Some(parent) = &lineage.parent else {
                break;
            };
            cursor = parent.parent();
        }
        std::future::poll_fn(|context| {
            if self.descendant_is_cancelled() {
                return std::task::Poll::Ready(());
            }
            for signal in &mut signals {
                if signal.as_mut().poll(context).is_ready() {
                    return std::task::Poll::Ready(());
                }
            }
            std::task::Poll::Pending
        })
        .await;
    }

    /// Bind the trusted cancellation owner and immutable finite tree limits to
    /// this original Phase 3 root ledger exactly once. No background task.
    pub fn enable_descendants(
        &self,
        limits: DelegationLimits,
        cancellation: Arc<dyn BudgetCancellationProbe>,
    ) -> Result<(), PlatformError> {
        limits.validate()?;
        if self.profile() != BudgetProfile::Phase3
            || self.inner.closed.load(Ordering::Acquire)
            || self.deadline().monotonic().is_none()
        {
            return Err(denied());
        }
        self.inner
            .lineage
            .set(Lineage {
                tree: Arc::new(Tree {
                    limits,
                    live: AtomicUsize::new(0),
                }),
                depth: 0,
                live_children: AtomicUsize::new(0),
                cancellation,
                parent: None,
            })
            .map_err(|_| denied())
    }
    /// Bounded ancestry observation for a linked execution probe. Terminal or
    /// cancelled ancestors close new delegation and cancel accepted descendants.
    #[must_use]
    pub fn descendant_is_cancelled(&self) -> bool {
        let mut cursor = self;
        for _ in 0..=16 {
            let Some(lineage) = cursor.inner.lineage.get() else {
                return true;
            };
            if cursor.inner.closed.load(Ordering::Acquire) || lineage.cancellation.is_cancelled() {
                return true;
            }
            let Some(parent) = &lineage.parent else {
                return false;
            };
            cursor = parent.parent();
        }
        true
    }
    pub fn descendant_snapshot(&self) -> Result<DescendantBudgetSnapshot, PlatformError> {
        let lineage = self.inner.lineage.get().ok_or_else(denied)?;
        let state = self.lock_state();
        Ok(DescendantBudgetSnapshot {
            depth: lineage.depth,
            live_descendants: lineage.tree.live.load(Ordering::Acquire),
            live_children: lineage.live_children.load(Ordering::Acquire),
            reserved_memory_bytes: state.child_reserved_memory,
            live_observed_child_memory_bytes: state.child_observed_memory,
            closed: self.inner.closed.load(Ordering::Acquire),
        })
    }
    fn check_delegation(&self, now: Instant) -> Result<(), PlatformError> {
        if self.descendant_is_cancelled() {
            return Err(failure(
                PlatformErrorCode::Cancelled,
                "descendant-parent-closed",
            ));
        }
        self.check_deadline_at(now)
            .map_err(|e| e.to_platform_error())
    }
}
impl ChildBudgetDelegation {
    #[must_use]
    pub fn grant(&self) -> EffectiveActivationBudget {
        let budget = self.budget.as_ref().expect("affine delegation");
        EffectiveActivationBudget {
            budget: budget.granted().clone(),
            deadline: budget.deadline().clone(),
        }
    }
    /// The normal node admission result may narrow the reserved grant. This
    /// consumes the sole reservation; admitted descendants cannot be cloned.
    pub fn accept(
        mut self,
        admitted: &EffectiveActivationBudget,
        cancellation: Arc<dyn BudgetCancellationProbe>,
        now: Instant,
    ) -> Result<ChildBudgetOwner, PlatformError> {
        let mut budget = self.budget.take().expect("affine delegation");
        budget.check_delegation(now)?;
        if admitted.budget.intersect(budget.granted()) != admitted.budget
            || admitted.deadline.monotonic().is_none_or(|d| {
                d > budget.deadline().monotonic().expect("finite parent") || d <= now
            })
            || admitted.deadline.admitted_at_monotonic() < budget.inner.started_at
            || admitted.deadline.admitted_at_monotonic() > now
            || cancellation.is_cancelled()
        {
            return Err(denied());
        }
        admitted
            .require_executable_capacity()
            .map_err(|e| e.to_platform_error())?;
        let inner = Arc::get_mut(&mut budget.inner).expect("pre-admission ledger is private");
        inner.granted.clone_from(&admitted.budget);
        inner.deadline.clone_from(&admitted.deadline);
        inner.started_at = admitted.deadline.admitted_at_monotonic();
        let lineage = inner.lineage.get_mut().expect("reserved lineage");
        lineage.cancellation = cancellation;
        lineage.parent.as_mut().expect("child reservation").accepted = true;
        Ok(ChildBudgetOwner { budget })
    }
}
impl ChildBudgetOwner {
    #[must_use]
    pub fn accounting(&self) -> &ActivationBudget {
        &self.budget
    }
    /// Called after the execution owner has established actual completion.
    /// Other retained ledger owners still prevent retirement/refunds.
    #[must_use]
    pub fn finish(self, reported: Option<&BudgetConsumption>, now: Instant) -> BudgetFinalization {
        self.budget.finalize_at(reported, now)
    }
}
fn failure(code: PlatformErrorCode, message: &'static str) -> PlatformError {
    PlatformError {
        code,
        message: message.into(),
        retryable: false,
        details: vec![],
    }
}
fn denied() -> PlatformError {
    failure(
        PlatformErrorCode::PermissionDenied,
        "descendant-grant-invalid",
    )
}
fn capacity() -> PlatformError {
    failure(PlatformErrorCode::ResourceExhausted, "descendant-capacity")
}
