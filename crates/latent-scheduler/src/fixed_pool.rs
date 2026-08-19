//! Fixed-capacity generic execution-cell pool used by the Phase 0 spike.

use crate::{CellClass, CellLease, CellPool, CellPoolSnapshot};
use latent_core::{
    ActivationId, BoxFuture, CellId, ErrorDetail, Metadata, NodeId, PlatformError,
    PlatformErrorCode, ResourceBudget, TenantId,
};
use std::collections::{HashMap, HashSet, VecDeque};
use std::sync::{Arc, Mutex, MutexGuard, Weak};
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use tokio::sync::oneshot;
use tokio::time::Instant;

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
    inner: Arc<PoolInner>,
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
    /// Creates all generic slots up front. Capacity cannot change afterward.
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

        let reservation = self
            .inner
            .reserve_or_queue(activation_id, tenant, budget, deadline)?;
        match reservation {
            Reservation::Immediate(lease) => Ok(lease),
            Reservation::Queued {
                waiter_id,
                activation_id,
                receiver,
            } => {
                self.await_queued(waiter_id, activation_id, deadline, now, receiver)
                    .await
            }
        }
    }

    async fn await_queued(
        &self,
        waiter_id: u64,
        activation_id: ActivationId,
        deadline: Option<u64>,
        queued_at_unix_millis: u64,
        mut receiver: oneshot::Receiver<Result<PendingGrant, PlatformError>>,
    ) -> Result<CellLease, PlatformError> {
        let mut registration = WaitRegistration::new(
            Arc::downgrade(&self.inner),
            waiter_id,
            activation_id.clone(),
        );

        let received = if let Some(deadline) = deadline {
            let wait_millis = deadline.saturating_sub(queued_at_unix_millis);
            let sleep = tokio::time::sleep_until(
                Instant::now() + Duration::from_millis(wait_millis),
            );
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
            Err(_) => Err(pool_error(
                PlatformErrorCode::Cancelled,
                "cell acquisition was cancelled while waiting",
                false,
                "cell-pool.waiter-cancelled",
                [("activation_id", activation_id.0)],
            )),
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
    fn managed(identity: LeaseIdentity, owner: Weak<PoolInner>) -> Self {
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

    fn reclaim_unaccepted(&mut self) {
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

enum Reservation {
    Immediate(CellLease),
    Queued {
        waiter_id: u64,
        activation_id: ActivationId,
        receiver: oneshot::Receiver<Result<PendingGrant, PlatformError>>,
    },
}

pub(crate) struct PoolInner {
    config: FixedCellPoolConfig,
    state: Mutex<PoolState>,
}

impl PoolInner {
    fn reserve_or_queue(
        self: &Arc<Self>,
        activation_id: ActivationId,
        tenant: TenantId,
        budget: ResourceBudget,
        deadline: Option<u64>,
    ) -> Result<Reservation, PlatformError> {
        let mut state = self.lock_state();
        if state.active.contains_key(&activation_id)
            || state.waiting_by_activation.contains_key(&activation_id)
        {
            return Err(pool_error(
                PlatformErrorCode::AlreadyExists,
                "activation already owns or is waiting for a cell",
                false,
                "cell-pool.duplicate-acquisition",
                [("activation_id", activation_id.0)],
            ));
        }

        if let Some(cell) = state.idle.pop_front() {
            let token = match state.take_lease_token() {
                Ok(token) => token,
                Err(error) => {
                    state.idle.push_front(cell);
                    return Err(error);
                }
            };
            let lease = Self::activate_locked(
                self,
                &mut state,
                token,
                cell,
                LeaseRequest {
                    activation_id,
                    tenant,
                    budget,
                    deadline,
                },
            );
            state.assert_invariants(&self.config);
            return Ok(Reservation::Immediate(lease));
        }

        if state.active.is_empty() && state.quarantined.len() == self.configured_capacity() {
            return Err(all_quarantined_error(
                &activation_id,
                state.quarantined.len(),
            ));
        }

        let queue_capacity = usize::try_from(self.config.queue_capacity)
            .expect("u32 queue capacity fits usize on supported hosts");
        if state.waiters.len() >= queue_capacity {
            return Err(pool_error(
                PlatformErrorCode::ResourceExhausted,
                "fixed cell-pool wait queue is full",
                true,
                "cell-pool.queue-full",
                [
                    ("queue_depth", state.waiters.len().to_string()),
                    ("queue_capacity", self.config.queue_capacity.to_string()),
                ],
            ));
        }

        let waiter_id = state.take_waiter_id()?;
        let (sender, receiver) = oneshot::channel();
        state
            .waiting_by_activation
            .insert(activation_id.clone(), waiter_id);
        state.waiters.push_back(Waiter {
            id: waiter_id,
            activation_id: activation_id.clone(),
            tenant,
            budget,
            deadline,
            sender,
        });
        state.assert_invariants(&self.config);
        Ok(Reservation::Queued {
            waiter_id,
            activation_id,
            receiver,
        })
    }

    fn activate_locked(
        owner: &Arc<Self>,
        state: &mut PoolState,
        token: u64,
        cell: IdleCell,
        request: LeaseRequest,
    ) -> CellLease {
        let LeaseRequest {
            activation_id,
            tenant,
            budget,
            deadline,
        } = request;
        let identity = LeaseIdentity {
            token,
            cell,
            activation_id: activation_id.clone(),
            tenant,
            node: owner.config.node.clone(),
            class: owner.config.class,
            granted_budget: budget,
            expires_at_unix_millis: deadline.unwrap_or(u64::MAX),
        };
        let previous = state.active.insert(activation_id, identity.clone());
        debug_assert!(previous.is_none(), "duplicate active activation inserted");
        CellLease::managed(identity, Arc::downgrade(owner))
    }

    fn finish_lease(
        self: &Arc<Self>,
        identity: LeaseIdentity,
        disposition: LeaseDisposition,
    ) -> Result<(), PlatformError> {
        let deliveries = {
            let mut state = self.lock_state();
            let Some(active) = state.active.get(&identity.activation_id) else {
                return Err(pool_error(
                    PlatformErrorCode::NotFound,
                    "cell lease is no longer active",
                    false,
                    "cell-pool.stale-release",
                    [
                        ("activation_id", identity.activation_id.0.clone()),
                        ("cell_id", identity.cell.id.0.clone()),
                    ],
                ));
            };
            if !active.matches_active(&identity) {
                return Err(pool_error(
                    PlatformErrorCode::InvalidArgument,
                    "cell lease identity does not match the active lease",
                    false,
                    "cell-pool.identity-mismatch",
                    [
                        ("activation_id", identity.activation_id.0.clone()),
                        ("cell_id", identity.cell.id.0.clone()),
                    ],
                ));
            }

            let active = state
                .active
                .remove(&identity.activation_id)
                .expect("active lease checked above");
            let deliveries = match disposition {
                LeaseDisposition::Reusable => {
                    if let Some(generation) = active.cell.generation.checked_add(1) {
                        Self::assign_cell_locked(
                            self,
                            &mut state,
                            IdleCell {
                                id: active.cell.id,
                                generation,
                            },
                            now_unix_millis(),
                        )
                    } else {
                        state.quarantined.insert(
                            active.cell.id.clone(),
                            QuarantinedCell {
                                cell: active.cell,
                                _reason: GENERATION_EXHAUSTED_REASON.to_owned(),
                            },
                        );
                        Self::fail_waiters_if_unserviceable_locked(&mut state)
                    }
                }
                LeaseDisposition::Quarantine(reason) => {
                    state.quarantined.insert(
                        active.cell.id.clone(),
                        QuarantinedCell {
                            cell: active.cell,
                            _reason: reason,
                        },
                    );
                    Self::fail_waiters_if_unserviceable_locked(&mut state)
                }
            };
            state.assert_invariants(&self.config);
            deliveries
        };
        deliver(deliveries);
        Ok(())
    }

    fn assign_cell_locked(
        owner: &Arc<Self>,
        state: &mut PoolState,
        cell: IdleCell,
        now: u64,
    ) -> Vec<Delivery> {
        let mut deliveries = Vec::new();
        loop {
            let Some(waiter) = state.waiters.pop_front() else {
                state.idle.push_back(cell);
                return deliveries;
            };
            state.waiting_by_activation.remove(&waiter.activation_id);

            if waiter.sender.is_closed() {
                continue;
            }
            if waiter.deadline.is_some_and(|deadline| deadline <= now) {
                deliveries.push(Delivery::Error {
                    sender: waiter.sender,
                    error: deadline_error(
                        &waiter.activation_id,
                        waiter.deadline.unwrap_or(now),
                    ),
                });
                continue;
            }

            let token = match state.take_lease_token() {
                Ok(token) => token,
                Err(error) => {
                    state.idle.push_back(cell);
                    deliveries.push(Delivery::Error {
                        sender: waiter.sender,
                        error,
                    });
                    return deliveries;
                }
            };
            let lease = Self::activate_locked(
                owner,
                state,
                token,
                cell,
                LeaseRequest {
                    activation_id: waiter.activation_id,
                    tenant: waiter.tenant,
                    budget: waiter.budget,
                    deadline: waiter.deadline,
                },
            );
            deliveries.push(Delivery::Grant {
                sender: waiter.sender,
                grant: PendingGrant::new(lease),
            });
            return deliveries;
        }
    }

    fn fail_waiters_if_unserviceable_locked(state: &mut PoolState) -> Vec<Delivery> {
        if !state.idle.is_empty() || !state.active.is_empty() {
            return Vec::new();
        }

        let quarantined = state.quarantined.len();
        let mut deliveries = Vec::with_capacity(state.waiters.len());
        while let Some(waiter) = state.waiters.pop_front() {
            state.waiting_by_activation.remove(&waiter.activation_id);
            deliveries.push(Delivery::Error {
                sender: waiter.sender,
                error: all_quarantined_error(&waiter.activation_id, quarantined),
            });
        }
        deliveries
    }

    fn cancel_waiter(&self, activation_id: &ActivationId) -> Result<(), PlatformError> {
        let sender = {
            let mut state = self.lock_state();
            let Some(waiter_id) = state.waiting_by_activation.remove(activation_id) else {
                return Err(pool_error(
                    PlatformErrorCode::NotFound,
                    "activation is not waiting for a cell",
                    false,
                    "cell-pool.waiter-not-found",
                    [("activation_id", activation_id.0.clone())],
                ));
            };
            let index = state
                .waiters
                .iter()
                .position(|waiter| waiter.id == waiter_id)
                .expect("waiter index tracked by activation map");
            let waiter = state
                .waiters
                .remove(index)
                .expect("waiter index checked above");
            state.assert_invariants(&self.config);
            waiter.sender
        };
        let _ = sender.send(Err(cancelled_error(activation_id)));
        Ok(())
    }

    fn remove_waiter(&self, waiter_id: u64, activation_id: &ActivationId) {
        let mut state = self.lock_state();
        if state.waiting_by_activation.get(activation_id) != Some(&waiter_id) {
            return;
        }
        state.waiting_by_activation.remove(activation_id);
        if let Some(index) = state.waiters.iter().position(|waiter| waiter.id == waiter_id) {
            state.waiters.remove(index);
        }
        state.assert_invariants(&self.config);
    }

    fn observations(&self, requested_class: CellClass) -> CellPoolSnapshot {
        if requested_class != self.config.class {
            return CellPoolSnapshot {
                class: requested_class,
                capacity: 0,
                available: 0,
                queue_depth: 0,
                active_leases: 0,
                quarantined: 0,
            };
        }
        let state = self.lock_state();
        CellPoolSnapshot {
            class: requested_class,
            capacity: self.config.capacity,
            available: len_u32(state.idle.len()),
            queue_depth: len_u32(state.waiters.len()),
            active_leases: len_u32(state.active.len()),
            quarantined: len_u32(state.quarantined.len()),
        }
    }

    fn configured_capacity(&self) -> usize {
        usize::try_from(self.config.capacity)
            .expect("u32 capacity fits usize on supported hosts")
    }

    fn lock_state(&self) -> MutexGuard<'_, PoolState> {
        self.state.lock().unwrap_or_else(std::sync::PoisonError::into_inner)
    }
}

struct PoolState {
    idle: VecDeque<IdleCell>,
    active: HashMap<ActivationId, LeaseIdentity>,
    waiters: VecDeque<Waiter>,
    waiting_by_activation: HashMap<ActivationId, u64>,
    quarantined: HashMap<CellId, QuarantinedCell>,
    next_waiter_id: u64,
    next_lease_token: u64,
}

impl PoolState {
    fn take_waiter_id(&mut self) -> Result<u64, PlatformError> {
        let current = self.next_waiter_id;
        self.next_waiter_id = current.checked_add(1).ok_or_else(sequence_exhausted)?;
        Ok(current)
    }

    fn take_lease_token(&mut self) -> Result<u64, PlatformError> {
        let current = self.next_lease_token;
        self.next_lease_token = current.checked_add(1).ok_or_else(sequence_exhausted)?;
        Ok(current)
    }

    fn assert_invariants(&self, config: &FixedCellPoolConfig) {
        debug_assert_eq!(
            self.idle.len() + self.active.len() + self.quarantined.len(),
            usize::try_from(config.capacity).expect("u32 capacity fits usize"),
            "fixed cell capacity changed"
        );
        debug_assert_eq!(
            self.waiters.len(),
            self.waiting_by_activation.len(),
            "waiter indexes diverged"
        );
        let configured_capacity =
            usize::try_from(config.capacity).expect("u32 capacity fits usize");
        let cell_ids: HashSet<&CellId> = self
            .idle
            .iter()
            .map(|cell| &cell.id)
            .chain(self.active.values().map(|identity| &identity.cell.id))
            .chain(self.quarantined.keys())
            .collect();
        debug_assert_eq!(cell_ids.len(), configured_capacity, "cell slots duplicated");
        debug_assert!(self
            .active
            .iter()
            .all(|(activation_id, identity)| activation_id == &identity.activation_id));
        debug_assert!(self
            .quarantined
            .iter()
            .all(|(cell_id, quarantined)| cell_id == &quarantined.cell.id));
        debug_assert!(self.waiters.iter().all(|waiter| {
            self.waiting_by_activation.get(&waiter.activation_id) == Some(&waiter.id)
        }));
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct IdleCell {
    id: CellId,
    generation: u64,
}

#[derive(Debug, Clone)]
pub(crate) struct LeaseIdentity {
    token: u64,
    cell: IdleCell,
    activation_id: ActivationId,
    tenant: TenantId,
    node: NodeId,
    class: CellClass,
    granted_budget: ResourceBudget,
    expires_at_unix_millis: u64,
}

impl LeaseIdentity {
    fn matches_active(&self, other: &Self) -> bool {
        self.token == other.token
            && self.cell == other.cell
            && self.activation_id == other.activation_id
            && self.tenant == other.tenant
            && self.node == other.node
            && self.class == other.class
            && self.granted_budget == other.granted_budget
            && self.expires_at_unix_millis == other.expires_at_unix_millis
    }

    fn matches_visible(&self, lease: &CellLease) -> bool {
        self.cell.id == lease.id
            && self.activation_id == lease.activation_id
            && self.node == lease.node
            && self.class == lease.class
            && self.granted_budget == lease.granted_budget
            && self.expires_at_unix_millis == lease.expires_at_unix_millis
    }
}

struct LeaseRequest {
    activation_id: ActivationId,
    tenant: TenantId,
    budget: ResourceBudget,
    deadline: Option<u64>,
}

struct Waiter {
    id: u64,
    activation_id: ActivationId,
    tenant: TenantId,
    budget: ResourceBudget,
    deadline: Option<u64>,
    sender: oneshot::Sender<Result<PendingGrant, PlatformError>>,
}

#[derive(Debug)]
struct QuarantinedCell {
    cell: IdleCell,
    _reason: String,
}

pub(crate) struct LeaseControl {
    owner: Weak<PoolInner>,
    identity: LeaseIdentity,
}

impl LeaseControl {
    fn reclaim_unaccepted(self) {
        if let Some(owner) = self.owner.upgrade() {
            let _ = owner.finish_lease(self.identity, LeaseDisposition::Reusable);
        }
    }

    fn quarantine_dropped(self) {
        if let Some(owner) = self.owner.upgrade() {
            let _ = owner.finish_lease(
                self.identity,
                LeaseDisposition::Quarantine(DROPPED_LEASE_REASON.to_owned()),
            );
        }
    }
}

#[derive(Debug)]
pub(crate) enum LeaseDisposition {
    Reusable,
    Quarantine(String),
}

struct PendingGrant {
    lease: Option<CellLease>,
}

impl PendingGrant {
    fn new(lease: CellLease) -> Self {
        Self { lease: Some(lease) }
    }

    fn accept(mut self) -> CellLease {
        self.lease.take().expect("pending grant contains one lease")
    }
}

impl Drop for PendingGrant {
    fn drop(&mut self) {
        if let Some(mut lease) = self.lease.take() {
            lease.reclaim_unaccepted();
        }
    }
}

enum Delivery {
    Grant {
        sender: oneshot::Sender<Result<PendingGrant, PlatformError>>,
        grant: PendingGrant,
    },
    Error {
        sender: oneshot::Sender<Result<PendingGrant, PlatformError>>,
        error: PlatformError,
    },
}

fn deliver(deliveries: Vec<Delivery>) {
    for delivery in deliveries {
        match delivery {
            Delivery::Grant { sender, grant } => {
                if let Err(result) = sender.send(Ok(grant)) {
                    if let Ok(grant) = result {
                        drop(grant);
                    }
                }
            }
            Delivery::Error { sender, error } => {
                let _ = sender.send(Err(error));
            }
        }
    }
}

struct WaitRegistration {
    owner: Weak<PoolInner>,
    waiter_id: u64,
    activation_id: ActivationId,
    armed: bool,
}

impl WaitRegistration {
    fn new(owner: Weak<PoolInner>, waiter_id: u64, activation_id: ActivationId) -> Self {
        Self {
            owner,
            waiter_id,
            activation_id,
            armed: true,
        }
    }

    fn disarm(&mut self) {
        self.armed = false;
    }

    fn expire(&mut self) {
        if self.armed {
            if let Some(owner) = self.owner.upgrade() {
                owner.remove_waiter(self.waiter_id, &self.activation_id);
            }
            self.armed = false;
        }
    }
}

impl Drop for WaitRegistration {
    fn drop(&mut self) {
        if self.armed {
            if let Some(owner) = self.owner.upgrade() {
                owner.remove_waiter(self.waiter_id, &self.activation_id);
            }
        }
    }
}

fn now_unix_millis() -> u64 {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis();
    u64::try_from(millis).unwrap_or(u64::MAX)
}

fn len_u32(length: usize) -> u32 {
    u32::try_from(length).expect("pool collection length is bounded by u32 configuration")
}

fn sequence_exhausted() -> PlatformError {
    pool_error(
        PlatformErrorCode::Internal,
        "cell-pool identifier sequence exhausted",
        false,
        "cell-pool.sequence-exhausted",
        [("scope", "phase0")],
    )
}

fn all_quarantined_error(activation_id: &ActivationId, quarantined: usize) -> PlatformError {
    pool_error(
        PlatformErrorCode::Unavailable,
        "all configured cells are quarantined",
        true,
        "cell-pool.all-quarantined",
        [
            ("activation_id", activation_id.0.clone()),
            ("quarantined", quarantined.to_string()),
        ],
    )
}

fn deadline_error(activation_id: &ActivationId, deadline: u64) -> PlatformError {
    pool_error(
        PlatformErrorCode::DeadlineExceeded,
        "cell acquisition deadline expired while waiting",
        false,
        "cell-pool.deadline-exceeded",
        [
            ("activation_id", activation_id.0.clone()),
            ("deadline_unix_millis", deadline.to_string()),
        ],
    )
}

fn cancelled_error(activation_id: &ActivationId) -> PlatformError {
    pool_error(
        PlatformErrorCode::Cancelled,
        "cell acquisition was cancelled while waiting",
        false,
        "cell-pool.waiter-cancelled",
        [("activation_id", activation_id.0.clone())],
    )
}

fn pool_error<I, K, V>(
    code: PlatformErrorCode,
    message: impl Into<String>,
    retryable: bool,
    kind: &str,
    fields: I,
) -> PlatformError
where
    I: IntoIterator<Item = (K, V)>,
    K: Into<String>,
    V: Into<String>,
{
    let fields: Metadata = fields
        .into_iter()
        .map(|(key, value)| (key.into(), value.into()))
        .collect();
    PlatformError {
        code,
        message: message.into(),
        retryable,
        details: vec![ErrorDetail {
            kind: kind.to_owned(),
            fields,
        }],
    }
}

fn cell_class_name(class: CellClass) -> &'static str {
    match class {
        CellClass::Tiny => "tiny",
        CellClass::Small => "small",
        CellClass::Standard => "standard",
        CellClass::Large => "large",
        CellClass::ExtraLarge => "extra-large",
    }
}

#[cfg(test)]
mod tests {
    use super::{now_unix_millis, FixedCellPool, FixedCellPoolConfig, LeaseDisposition};
    use crate::{CellClass, CellPool};
    use latent_core::{
        ActivationId, CellId, NodeId, PlatformErrorCode, ResourceBudget, TenantId,
    };
    use std::time::Duration;

    fn pool(capacity: u32, queue_capacity: u32) -> FixedCellPool {
        FixedCellPool::new(FixedCellPoolConfig::new(
            NodeId("node-test".to_owned()),
            CellClass::Standard,
            capacity,
            queue_capacity,
        ))
        .expect("valid fixed pool")
    }

    fn budget(deadline: Option<u64>) -> ResourceBudget {
        ResourceBudget {
            cpu_fuel: 10_000,
            memory_bytes: 1_048_576,
            wall_deadline_unix_millis: deadline,
            child_calls: 0,
            outbound_requests: 0,
            state_read_bytes: 0,
            state_write_bytes: 0,
            blob_read_bytes: 0,
            blob_write_bytes: 0,
            log_bytes: 1_024,
            effect_count: 0,
        }
    }

    async fn acquire(
        pool: &FixedCellPool,
        activation: &str,
        deadline: Option<u64>,
    ) -> Result<crate::CellLease, latent_core::PlatformError> {
        pool.acquire(
            &ActivationId(activation.to_owned()),
            &TenantId("tenant-test".to_owned()),
            CellClass::Standard,
            &budget(deadline),
        )
        .await
    }

    async fn wait_for_queue_depth(pool: &FixedCellPool, expected: u32) {
        for _ in 0..100 {
            if pool.observations().queue_depth == expected {
                return;
            }
            tokio::task::yield_now().await;
        }
        panic!("queue depth did not become {expected}");
    }

    async fn wait_for_settled(pool: &FixedCellPool) {
        for _ in 0..100 {
            let observations = pool.observations();
            if observations.queue_depth == 0 && observations.active_leases == 0 {
                return;
            }
            tokio::task::yield_now().await;
        }
        panic!("pool did not settle");
    }

    #[tokio::test]
    async fn capacity_is_fixed_and_concurrent_acquisition_is_bounded() {
        let pool = pool(2, 2);
        let first = acquire(&pool, "activation-1", None)
            .await
            .expect("first lease");
        let second = acquire(&pool, "activation-2", None)
            .await
            .expect("second lease");
        let observations = pool.observations();
        assert_eq!(observations.capacity, 2);
        assert_eq!(observations.available, 0);
        assert_eq!(observations.active_leases, 2);

        let waiter_pool = pool.clone();
        let waiter = tokio::spawn(async move {
            acquire(&waiter_pool, "activation-3", None).await
        });
        wait_for_queue_depth(&pool, 1).await;
        assert_eq!(pool.observations().active_leases, 2);

        pool.release(first).await.expect("return first lease");
        let third = waiter.await.expect("waiter task").expect("third lease");
        let observations = pool.observations();
        assert_eq!(observations.capacity, 2);
        assert_eq!(observations.active_leases, 2);
        assert_eq!(observations.available, 0);

        pool.release(second).await.expect("return second lease");
        pool.release(third).await.expect("return third lease");
        assert_eq!(pool.observations().available, 2);
    }

    #[tokio::test]
    async fn bounded_queue_rejects_excess_work_deterministically() {
        let pool = pool(1, 1);
        let lease = acquire(&pool, "activation-owner", None)
            .await
            .expect("owner lease");
        let waiter_pool = pool.clone();
        let waiter = tokio::spawn(async move {
            acquire(&waiter_pool, "activation-waiting", None).await
        });
        wait_for_queue_depth(&pool, 1).await;

        let error = acquire(&pool, "activation-rejected", None)
            .await
            .expect_err("full queue must reject");
        assert_eq!(error.code, PlatformErrorCode::ResourceExhausted);
        assert_eq!(pool.observations().queue_depth, 1);

        pool.cancel_queued(&ActivationId("activation-waiting".to_owned()))
            .expect("cancel waiter");
        let cancellation = waiter
            .await
            .expect("waiter task")
            .expect_err("waiter cancelled");
        assert_eq!(cancellation.code, PlatformErrorCode::Cancelled);
        pool.release(lease).await.expect("return owner lease");
    }

    #[tokio::test]
    async fn cancelled_waiter_never_receives_a_later_lease() {
        let pool = pool(1, 1);
        let lease = acquire(&pool, "activation-owner", None)
            .await
            .expect("owner lease");
        let waiter_pool = pool.clone();
        let waiter = tokio::spawn(async move {
            acquire(&waiter_pool, "activation-cancelled", None).await
        });
        wait_for_queue_depth(&pool, 1).await;

        pool.cancel_queued(&ActivationId("activation-cancelled".to_owned()))
            .expect("cancel waiting activation");
        let error = waiter
            .await
            .expect("waiter task")
            .expect_err("cancelled waiter");
        assert_eq!(error.code, PlatformErrorCode::Cancelled);
        pool.release(lease).await.expect("return owner lease");

        let observations = pool.observations();
        assert_eq!(observations.available, 1);
        assert_eq!(observations.active_leases, 0);
        assert_eq!(observations.queue_depth, 0);
    }

    #[tokio::test(start_paused = true)]
    async fn expired_waiter_never_receives_a_later_lease() {
        let pool = pool(1, 1);
        let lease = acquire(&pool, "activation-owner", None)
            .await
            .expect("owner lease");
        let deadline = now_unix_millis().saturating_add(1_000);
        let waiter_pool = pool.clone();
        let waiter = tokio::spawn(async move {
            acquire(&waiter_pool, "activation-expired", Some(deadline)).await
        });
        wait_for_queue_depth(&pool, 1).await;

        tokio::time::advance(Duration::from_millis(1_001)).await;
        let error = waiter
            .await
            .expect("waiter task")
            .expect_err("waiter must expire");
        assert_eq!(error.code, PlatformErrorCode::DeadlineExceeded);

        pool.release(lease).await.expect("return owner lease");
        let observations = pool.observations();
        assert_eq!(observations.available, 1);
        assert_eq!(observations.active_leases, 0);
        assert_eq!(observations.queue_depth, 0);
    }

    #[tokio::test]
    async fn dropping_a_live_lease_quarantines_its_cell() {
        let pool = pool(2, 0);
        let lease = acquire(&pool, "activation-dropped", None)
            .await
            .expect("lease");
        drop(lease);

        let observations = pool.observations();
        assert_eq!(observations.capacity, 2);
        assert_eq!(observations.available, 1);
        assert_eq!(observations.active_leases, 0);
        assert_eq!(observations.quarantined, 1);
    }

    #[tokio::test]
    async fn explicit_quarantine_removes_unsafe_capacity() {
        let pool = pool(1, 0);
        let lease = acquire(&pool, "activation-unsafe", None)
            .await
            .expect("lease");
        pool.quarantine_lease(lease, "backend reset failed")
            .expect("quarantine cell");

        let observations = pool.observations();
        assert_eq!(observations.capacity, 1);
        assert_eq!(observations.available, 0);
        assert_eq!(observations.active_leases, 0);
        assert_eq!(observations.quarantined, 1);
        let error = acquire(&pool, "activation-next", None)
            .await
            .expect_err("all quarantined pool is unavailable");
        assert_eq!(error.code, PlatformErrorCode::Unavailable);
    }

    #[tokio::test]
    async fn duplicate_activation_and_identity_mismatch_cannot_inflate_capacity() {
        let pool = pool(1, 0);
        let mut lease = acquire(&pool, "activation-original", None)
            .await
            .expect("lease");
        let duplicate = acquire(&pool, "activation-original", None)
            .await
            .expect_err("duplicate activation");
        assert_eq!(duplicate.code, PlatformErrorCode::AlreadyExists);

        lease.id = CellId("forged-cell".to_owned());
        let error = pool
            .release(lease)
            .await
            .expect_err("forged identity must fail");
        assert_eq!(error.code, PlatformErrorCode::InvalidArgument);
        let observations = pool.observations();
        assert_eq!(observations.capacity, 1);
        assert_eq!(observations.available, 0);
        assert_eq!(observations.active_leases, 0);
        assert_eq!(observations.quarantined, 1);
    }

    #[tokio::test]
    async fn duplicate_return_cannot_inflate_available_capacity() {
        let pool = pool(1, 0);
        let lease = acquire(&pool, "activation-once", None)
            .await
            .expect("lease");
        let identity = lease
            .control
            .as_ref()
            .expect("managed lease")
            .identity
            .clone();

        pool.inner
            .finish_lease(identity.clone(), LeaseDisposition::Reusable)
            .expect("first return");
        let error = pool
            .inner
            .finish_lease(identity, LeaseDisposition::Reusable)
            .expect_err("second return must fail");
        assert_eq!(error.code, PlatformErrorCode::NotFound);
        drop(lease);

        let observations = pool.observations();
        assert_eq!(observations.capacity, 1);
        assert_eq!(observations.available, 1);
        assert_eq!(observations.active_leases, 0);
        assert_eq!(observations.quarantined, 0);
    }

    #[tokio::test]
    async fn task_cancellation_race_preserves_exact_capacity_accounting() {
        for iteration in 0..32 {
            let pool = pool(1, 1);
            let owner = acquire(&pool, &format!("owner-{iteration}"), None)
                .await
                .expect("owner lease");
            let waiter_pool = pool.clone();
            let waiter = tokio::spawn(async move {
                acquire(&waiter_pool, &format!("waiter-{iteration}"), None).await
            });
            wait_for_queue_depth(&pool, 1).await;

            pool.release(owner).await.expect("release owner");
            waiter.abort();
            match waiter.await {
                Ok(Ok(lease)) => drop(lease),
                Ok(Err(error)) => assert_eq!(error.code, PlatformErrorCode::Cancelled),
                Err(join_error) => assert!(join_error.is_cancelled()),
            }
            wait_for_settled(&pool).await;

            let observations = pool.observations();
            assert_eq!(observations.capacity, 1);
            assert_eq!(observations.queue_depth, 0);
            assert_eq!(observations.active_leases, 0);
            assert_eq!(
                observations.available + observations.quarantined,
                observations.capacity
            );
        }
    }

    #[tokio::test]
    async fn quarantining_the_last_cell_fails_waiters_without_hanging() {
        let pool = pool(1, 1);
        let lease = acquire(&pool, "activation-owner", None)
            .await
            .expect("owner lease");
        let waiter_pool = pool.clone();
        let waiter = tokio::spawn(async move {
            acquire(&waiter_pool, "activation-waiting", None).await
        });
        wait_for_queue_depth(&pool, 1).await;

        pool.quarantine_lease(lease, "backend reset failed")
            .expect("quarantine final cell");
        let error = waiter
            .await
            .expect("waiter task")
            .expect_err("unserviceable waiter");
        assert_eq!(error.code, PlatformErrorCode::Unavailable);

        let observations = pool.observations();
        assert_eq!(observations.queue_depth, 0);
        assert_eq!(observations.active_leases, 0);
        assert_eq!(observations.quarantined, 1);
    }

    #[tokio::test]
    async fn unsupported_classes_report_zero_observed_capacity() {
        let pool = pool(1, 0);
        let observations = CellPool::observations(&pool, CellClass::Tiny);
        assert_eq!(observations.capacity, 0);
        assert_eq!(observations.available, 0);
        let error = pool
            .acquire(
                &ActivationId("activation-tiny".to_owned()),
                &TenantId("tenant-test".to_owned()),
                CellClass::Tiny,
                &budget(None),
            )
            .await
            .expect_err("unsupported class");
        assert_eq!(error.code, PlatformErrorCode::InvalidArgument);
    }
}
