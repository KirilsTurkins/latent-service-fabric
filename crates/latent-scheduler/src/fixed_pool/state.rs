use super::errors::{
    all_quarantined_error, cancelled_error, deadline_error, len_u32, pool_error, WallClock,
};
use super::types::{
    deliver, Delivery, IdleCell, LeaseDisposition, LeaseIdentity, LeaseRequest, PendingGrant,
    PoolState, QuarantinedCell, Reservation, Waiter,
};
use super::{FixedCellPoolConfig, GENERATION_EXHAUSTED_REASON, LEASE_TOKEN_EXHAUSTED_REASON};
use crate::{CellClass, CellLease, CellPoolSnapshot};
use latent_core::{ActivationId, PlatformError, PlatformErrorCode, ResourceBudget, TenantId};
use std::sync::{Arc, Mutex, MutexGuard};
use tokio::sync::oneshot;

pub(super) struct PoolInner {
    pub(super) config: FixedCellPoolConfig,
    pub(super) clock: Arc<dyn WallClock>,
    pub(super) state: Mutex<PoolState>,
}

impl PoolInner {
    pub(super) fn reserve_or_queue(
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
                    Self::quarantine_token_exhaustion_locked(&mut state, cell);
                    state.assert_invariants(&self.config);
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

    pub(super) fn finish_lease(
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
                            self.clock.now_unix_millis(),
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
                    error: deadline_error(&waiter.activation_id, waiter.deadline.unwrap_or(now)),
                });
                continue;
            }

            let token = match state.take_lease_token() {
                Ok(token) => token,
                Err(error) => {
                    Self::quarantine_token_exhaustion_locked(state, cell);
                    deliveries.push(Delivery::Error {
                        sender: waiter.sender,
                        error: error.clone(),
                    });
                    Self::fail_all_waiters_locked(state, &error, &mut deliveries);
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

    fn quarantine_token_exhaustion_locked(state: &mut PoolState, cell: IdleCell) {
        state.quarantined.insert(
            cell.id.clone(),
            QuarantinedCell {
                cell,
                _reason: LEASE_TOKEN_EXHAUSTED_REASON.to_owned(),
            },
        );
    }

    fn fail_all_waiters_locked(
        state: &mut PoolState,
        error: &PlatformError,
        deliveries: &mut Vec<Delivery>,
    ) {
        while let Some(waiter) = state.waiters.pop_front() {
            state.waiting_by_activation.remove(&waiter.activation_id);
            deliveries.push(Delivery::Error {
                sender: waiter.sender,
                error: error.clone(),
            });
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

    pub(super) fn cancel_waiter(&self, activation_id: &ActivationId) -> Result<(), PlatformError> {
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

    pub(super) fn remove_waiter(&self, waiter_id: u64, activation_id: &ActivationId) {
        let mut state = self.lock_state();
        if state.waiting_by_activation.get(activation_id) != Some(&waiter_id) {
            return;
        }
        state.waiting_by_activation.remove(activation_id);
        if let Some(index) = state
            .waiters
            .iter()
            .position(|waiter| waiter.id == waiter_id)
        {
            state.waiters.remove(index);
        }
        state.assert_invariants(&self.config);
    }

    pub(super) fn observations(&self, requested_class: CellClass) -> CellPoolSnapshot {
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
        usize::try_from(self.config.capacity).expect("u32 capacity fits usize on supported hosts")
    }

    fn lock_state(&self) -> MutexGuard<'_, PoolState> {
        self.state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
    }
}
