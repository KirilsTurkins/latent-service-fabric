//! Fixed-capacity generic execution-cell pool used by the Phase 0 spike.

mod errors;
mod state;
mod types;

use crate::{CellClass, CellLease, CellPool, CellPoolSnapshot};
use errors::{cancelled_error, cell_class_name, deadline_error, now_unix_millis, pool_error};
use latent_core::{
    ActivationId, BoxFuture, CellId, NodeId, PlatformError, PlatformErrorCode, ResourceBudget,
    TenantId,
};
use state::PoolInner;
use std::collections::{HashMap, VecDeque};
use std::sync::{Arc, Mutex};
use std::time::Duration;
use tokio::sync::oneshot;
use types::{
    IdleCell, LeaseDisposition, PendingGrant, PoolState, Reservation, WaitRegistration,
};

pub(crate) use types::LeaseControl;

const DROPPED_LEASE_REASON: &str = "lease dropped before an explicit release or quarantine";
const GENERATION_EXHAUSTED_REASON: &str = "cell generation counter exhausted";

/// Node-owned configuration for the single Phase 0 cell class.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FixedCellPoolConfig {
    pub node: NodeId,
    pub class: CellClass,
    pub capacity: u32,
    pub queue_capacity: u32,
}

impl FixedCellPoolConfig {
    #[must_use]
    pub fn new(
        node: NodeId,
        class: CellClass,
        capacity: u32,
        queue_capacity: u32,
    ) -> Self {
        Self {
            node,
            class,
            capacity,
            queue_capacity,
        }
    }
}

/// A fixed-capacity, FIFO execution-cell pool with no capsule-owned idle state.
#[derive(Clone)]
pub struct FixedCellPool {
    pub(super) inner: Arc<PoolInner>,
}

impl std::fmt::Debug for FixedCellPool {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("FixedCellPool")
            .field("config", &self.inner.config)
            .field("observations", &self.observations())
            .finish()
    }
}

impl FixedCellPool {
    /// Creates every generic slot up front. Capacity cannot change afterward.
    pub fn new(config: FixedCellPoolConfig) -> Result<Self, PlatformError> {
        if config.capacity == 0 {
            return Err(pool_error(
                PlatformErrorCode::InvalidArgument,
                "fixed cell-pool capacity must be greater than zero",
                false,
                "cell-pool.invalid-capacity",
                [("capacity", config.capacity.to_string())],
            ));
        }

        let capacity = usize::try_from(config.capacity).map_err(|_| {
            pool_error(
                PlatformErrorCode::InvalidArgument,
                "fixed cell-pool capacity does not fit this platform",
                false,
                "cell-pool.invalid-capacity",
                [("capacity", config.capacity.to_string())],
            )
        })?;

        let mut idle = VecDeque::with_capacity(capacity);
        for index in 0..config.capacity {
            idle.push_back(IdleCell {
                id: CellId(format!(
                    "{}:phase0:{}:{index:08x}",
                    config.node.0.as_str(),
                    cell_class_name(config.class)
                )),
                generation: 0,
            });
        }

        Ok(Self {
            inner: Arc::new(PoolInner {
                config,
                state: Mutex::new(PoolState {
                    idle,
                    active: HashMap::new(),
                    waiters: VecDeque::new(),
                    waiting_by_activation: HashMap::new(),
                    quarantined: HashMap::new(),
                    next_waiter_id: 1,
                    next_lease_token: 1,
                }),
            }),
        })
    }

    /// Returns all Phase 0 observations without inspecting capsule metadata.
    #[must_use]
    pub fn observations(&self) -> CellPoolSnapshot {
        self.inner.observations(self.inner.config.class)
    }

    /// Cancels one queued activation. Active leases are not affected.
    pub fn cancel_queued(&self, activation_id: &ActivationId) -> Result<(), PlatformError> {
        self.inner.cancel_waiter(activation_id)
    }

    /// Explicitly removes a cell from reusable capacity after unsafe cleanup.
    pub fn quarantine_lease(
        &self,
        lease: CellLease,
        reason: impl Into<String>,
    ) -> Result<(), PlatformError> {
        let reason = reason.into();
        if reason.trim().is_empty() {
            return Err(pool_error(
                PlatformErrorCode::InvalidArgument,
                "a quarantine reason is required",
                false,
                "cell-pool.invalid-quarantine-reason",
                [("activation_id", lease.activation_id.0.clone())],
            ));
        }
        lease.finish(&self.inner, LeaseDisposition::Quarantine(reason))
    }

    async fn acquire_owned(
        &self,
        activation_id: ActivationId,
        tenant: TenantId,
        class: CellClass,
        budget: ResourceBudget,
    ) -> Result<CellLease, PlatformError> {
        if class != self.inner.config.class {
            return Err(pool_error(
                PlatformErrorCode::InvalidArgument,
                format!(
                    "cell class {} is not configured by this Phase 0 pool",
                    cell_class_name(class)
                ),
                false,
                "cell-pool.unsupported-class",
                [
                    ("requested", cell_class_name(class).to_owned()),
                    (
                        "configured",
                        cell_class_name(self.inner.config.class).to_owned(),
                    ),
                ],
            ));
        }

        let deadline = budget.wall_deadline_unix_millis;
        let now = now_unix_millis();
        if deadline.is_some_and(|value| value <= now) {
            return Err(deadline_error(&activation_id, deadline.unwrap_or(now)));
        }

        match self
            .inner
            .reserve_or_queue(activation_id, tenant, budget, deadline)?
        {
            Reservation::Immediate(lease) => Ok(lease),
            Reservation::Queued {
                waiter_id,
                activation_id,
                receiver,
            } => {
                self.await_queued(waiter_id, activation_id, deadline, receiver)
                    .await
            }
        }
    }

    async fn await_queued(
        &self,
        waiter_id: u64,
        activation_id: ActivationId,
        deadline: Option<u64>,
        mut receiver: oneshot::Receiver<Result<PendingGrant, PlatformError>>,
    ) -> Result<CellLease, PlatformError> {
        let mut registration = WaitRegistration::new(
            Arc::downgrade(&self.inner),
            waiter_id,
            activation_id.clone(),
        );

        let received = if let Some(deadline) = deadline {
            let now = now_unix_millis();
            if deadline <= now {
                registration.expire();
                return Err(deadline_error(&activation_id, deadline));
            }
            let sleep = tokio::time::sleep(Duration::from_millis(deadline - now));
            tokio::pin!(sleep);
            tokio::select! {
                biased;
                () = &mut sleep => {
                    registration.expire();
                    return Err(deadline_error(&activation_id, deadline));
                }
                received = &mut receiver => received,
            }
        } else {
            receiver.await
        };

        registration.disarm();
        match received {
            Ok(Ok(grant)) => {
                if deadline.is_some_and(|value| value <= now_unix_millis()) {
                    drop(grant);
                    Err(deadline_error(
                        &activation_id,
                        deadline.unwrap_or_else(now_unix_millis),
                    ))
                } else {
                    Ok(grant.accept())
                }
            }
            Ok(Err(error)) => Err(error),
            Err(_) => Err(cancelled_error(&activation_id)),
        }
    }
}

impl CellPool for FixedCellPool {
    fn acquire<'a>(
        &'a self,
        activation_id: &'a ActivationId,
        tenant: &'a TenantId,
        class: CellClass,
        budget: &'a ResourceBudget,
    ) -> BoxFuture<'a, Result<CellLease, PlatformError>> {
        let activation_id = activation_id.clone();
        let tenant = tenant.clone();
        let budget = budget.clone();
        Box::pin(async move {
            self.acquire_owned(activation_id, tenant, class, budget)
                .await
        })
    }

    fn release<'a>(&'a self, lease: CellLease) -> BoxFuture<'a, Result<(), PlatformError>> {
        Box::pin(async move { lease.finish(&self.inner, LeaseDisposition::Reusable) })
    }

    fn cancel_waiting<'a>(
        &'a self,
        activation_id: &'a ActivationId,
    ) -> BoxFuture<'a, Result<(), PlatformError>> {
        Box::pin(async move { FixedCellPool::cancel_queued(self, activation_id) })
    }

    fn quarantine<'a>(
        &'a self,
        lease: CellLease,
        reason: String,
    ) -> BoxFuture<'a, Result<(), PlatformError>> {
        Box::pin(async move { FixedCellPool::quarantine_lease(self, lease, reason) })
    }

    fn observations(&self, class: CellClass) -> CellPoolSnapshot {
        self.inner.observations(class)
    }
}

impl CellLease {
    pub(super) fn managed(identity: types::LeaseIdentity, owner: std::sync::Weak<PoolInner>) -> Self {
        Self {
            id: identity.cell.id.clone(),
            activation_id: identity.activation_id.clone(),
            node: identity.node.clone(),
            class: identity.class,
            granted_budget: identity.granted_budget.clone(),
            expires_at_unix_millis: identity.expires_at_unix_millis,
            control: Some(LeaseControl { owner, identity }),
        }
    }

    fn finish(
        mut self,
        owner: &Arc<PoolInner>,
        disposition: LeaseDisposition,
    ) -> Result<(), PlatformError> {
        let Some(control) = self.control.as_ref() else {
            return Err(pool_error(
                PlatformErrorCode::NotFound,
                "cell lease has already been dispositioned",
                false,
                "cell-pool.double-release",
                [("activation_id", self.activation_id.0.clone())],
            ));
        };
        if !control.identity.matches_visible(&self) {
            return Err(pool_error(
                PlatformErrorCode::InvalidArgument,
                "visible cell lease fields were modified after acquisition",
                false,
                "cell-pool.identity-mismatch",
                [
                    ("activation_id", self.activation_id.0.clone()),
                    ("cell_id", self.id.0.clone()),
                ],
            ));
        }
        let expected_owner = control.owner.upgrade().ok_or_else(|| {
            pool_error(
                PlatformErrorCode::Unavailable,
                "cell pool was dropped before the lease was returned",
                false,
                "cell-pool.owner-gone",
                [("activation_id", control.identity.activation_id.0.clone())],
            )
        })?;
        if !Arc::ptr_eq(&expected_owner, owner) {
            return Err(pool_error(
                PlatformErrorCode::InvalidArgument,
                "cell lease belongs to a different pool",
                false,
                "cell-pool.foreign-lease",
                [
                    ("activation_id", control.identity.activation_id.0.clone()),
                    ("cell_id", control.identity.cell.id.0.clone()),
                ],
            ));
        }

        let identity = control.identity.clone();
        let result = owner.finish_lease(identity, disposition);
        if result.is_ok() {
            self.control.take();
        }
        result
    }

    pub(super) fn reclaim_unaccepted(&mut self) {
        if let Some(control) = self.control.take() {
            control.reclaim_unaccepted();
        }
    }
}

impl std::fmt::Debug for CellLease {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("CellLease")
            .field("id", &self.id)
            .field("activation_id", &self.activation_id)
            .field("node", &self.node)
            .field("class", &self.class)
            .field("granted_budget", &self.granted_budget)
            .field("expires_at_unix_millis", &self.expires_at_unix_millis)
            .finish()
    }
}

impl PartialEq for CellLease {
    fn eq(&self, other: &Self) -> bool {
        self.id == other.id
            && self.activation_id == other.activation_id
            && self.node == other.node
            && self.class == other.class
            && self.granted_budget == other.granted_budget
            && self.expires_at_unix_millis == other.expires_at_unix_millis
    }
}

impl Eq for CellLease {}

impl Drop for CellLease {
    fn drop(&mut self) {
        if let Some(control) = self.control.take() {
            control.quarantine_dropped();
        }
    }
}

#[cfg(test)]
mod tests;
