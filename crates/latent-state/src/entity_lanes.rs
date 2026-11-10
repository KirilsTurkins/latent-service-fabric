//! Bounded, invocation-local entity execution eligibility.
//!
//! The caller supplies a trusted tenant/namespace/incarnation/entity scope and
//! an original accepted command invocation. This module neither grants that
//! authority nor supplies durable deduplication. The opaque payload retains the
//! accepted publication/schema pin unchanged while queued. Durable admission,
//! replay and final commit must use the host's current authority.
//!
//! Drive `try_start_next` from the existing scheduler before acquiring a guest
//! cell. There are no entity workers or timers. Monotonic wait limits are checked
//! on dispatch; the host must drive dispatch while work is pending. One physical
//! owner per key survives cancellation, deadline, commit and cleanup. Transfer a
//! physical guard into each independently owned executor/commit/cleanup operation;
//! only dropping the last such guard retires eligibility. Observation tickets and
//! fences do not retain physical ownership.

#![deny(clippy::all, clippy::pedantic)]
// Rejection returns the existing owned request. Boxing it would allocate after
// resource admission failed, and discarding it would lose the pinned command.
#![allow(clippy::result_large_err)]

mod accounting;
mod dispatch;
mod owner;
mod state;
mod types;

pub use owner::{EntityExecution, EntityLaneFence, EntityPhysicalOwner, EntityWaiter};
pub use types::{
    EntityCallKind, EntityCancellation, EntityDispatch, EntityLaneError, EntityLaneLimit,
    EntityLaneLimits, EntityLaneRequest, EntityLaneSnapshot, EntityRejected, EntityRejection,
    EntityScope, EntitySubmitError, EntityWaitStatus,
};

use std::sync::{Arc, Mutex};
use std::task::Waker;
use std::time::Instant;

use latent_core::{StateNamespaceId, TenantId};
use state::{Queued, State};

/// A shared finite owner table, containing only accepted/active/cleanup work.
pub struct EntityLanes<T> {
    inner: Arc<Inner<T>>,
}

struct Inner<T> {
    state: Mutex<State<T>>,
}

/// One coherent observation for the existing shared scheduler driver.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct EntityDispatchReadiness {
    pub ready: bool,
    pub next_deadline: Option<Instant>,
}

impl<T> Clone for EntityLanes<T> {
    fn clone(&self) -> Self {
        Self {
            inner: Arc::clone(&self.inner),
        }
    }
}

impl<T> EntityLanes<T> {
    /// # Errors
    /// Returns `InvalidLimits` for any zero capacity or zero wait age.
    pub fn new(limits: EntityLaneLimits) -> Result<Self, EntityLaneError> {
        limits.validate()?;
        Ok(Self {
            inner: Arc::new(Inner {
                state: Mutex::new(State::new(limits)),
            }),
        })
    }

    /// Submit an already authorized original command invocation. The caller
    /// must use durable admission and replay before starting guest work.
    ///
    /// The host charges payload allocations before constructing the request.
    /// `retained_bytes` accounts for its owned payload; this owner also charges
    /// a conservative finite envelope for request/scope/identity metadata.
    ///
    /// # Errors
    /// Returns the original owned request on invalid, expired, nested, duplicate,
    /// capacity-limited or exhausted admission, or poisoned owner state.
    pub fn enqueue(
        &self,
        request: EntityLaneRequest<T>,
        now: Instant,
    ) -> Result<EntityWaiter<T>, EntitySubmitError<T>> {
        let Ok(mut state) = self.inner.state.lock() else {
            return Err(EntitySubmitError {
                reason: EntityLaneError::Poisoned,
                request,
            });
        };
        let accepted = (|| {
            let (charge, wait_until) = state.check_admission(&request, now)?;
            let ticket = state
                .next_ticket
                .checked_add(1)
                .ok_or(EntityLaneError::Exhausted)?;
            Ok((charge, wait_until, ticket))
        })();
        let (charge, wait_until, ticket) = match accepted {
            Ok(accepted) => accepted,
            Err(reason) => return Err(EntitySubmitError { reason, request }),
        };
        let waiter = EntityWaiter::new(
            Arc::clone(&self.inner),
            request.scope.clone(),
            ticket,
            Arc::clone(&state.identity),
        );
        state.next_ticket = ticket;
        state.insert(Queued {
            request,
            ticket,
            wait_until,
            charge,
        });
        let wake = state.dispatcher.take();
        drop(state);
        if let Some(wake) = wake {
            wake.wake();
        }
        Ok(waiter)
    }

    /// Register the one shared dispatcher and observe eligibility atomically.
    /// The caller drives `try_start_next` while ready and arms its existing
    /// shared timer for `next_deadline` when waiting. A later enqueue or actual
    /// owner retirement wakes this registration; no per-entity task is created.
    ///
    /// # Errors
    /// Returns `Poisoned` if the coherent lane state cannot be observed.
    pub fn register_dispatch_waker(
        &self,
        now: Instant,
        waker: &Waker,
    ) -> Result<EntityDispatchReadiness, EntityLaneError> {
        let candidate = waker.clone();
        let mut state = self
            .inner
            .state
            .lock()
            .map_err(|_| EntityLaneError::Poisoned)?;
        let next_deadline = state
            .lanes
            .values()
            .flat_map(|lane| lane.queue.iter())
            .map(|queued| queued.wait_until)
            .min();
        let expired = next_deadline.is_some_and(|deadline| deadline <= now);
        let available = state.snapshot(None).active < state.limits.global_active
            && state.ready.iter().any(|scope| {
                state.snapshot(Some(scope.tenant())).active < state.limits.tenant_active
            });
        let ready = expired || available;
        let previous = std::mem::replace(
            &mut state.dispatcher,
            if ready { None } else { Some(candidate) },
        );
        drop(state);
        drop(previous);
        Ok(EntityDispatchReadiness {
            ready,
            next_deadline,
        })
    }

    /// Remove only the matching dispatcher registration during driver shutdown.
    ///
    /// # Errors
    /// Returns `Poisoned` if the coherent lane state cannot be observed.
    pub fn clear_dispatch_waker(&self, waker: &Waker) -> Result<bool, EntityLaneError> {
        let mut state = self
            .inner
            .state
            .lock()
            .map_err(|_| EntityLaneError::Poisoned)?;
        let registered = state
            .dispatcher
            .as_ref()
            .is_some_and(|registered| registered.will_wake(waker));
        let removed = if registered {
            state.dispatcher.take()
        } else {
            None
        };
        drop(state);
        drop(removed);
        Ok(registered)
    }

    /// # Errors
    /// Returns `Poisoned` when coherent owner accounting cannot be established.
    pub fn snapshot(&self) -> Result<EntityLaneSnapshot, EntityLaneError> {
        let state = self
            .inner
            .state
            .lock()
            .map_err(|_| EntityLaneError::Poisoned)?;
        Ok(state.snapshot(None))
    }

    /// Reject a stale, foreign or explicitly revoked owner observation.
    ///
    /// This is a local ownership fence, not a replacement for the namespace
    /// store's atomic authorization/incarnation and command-attempt fence.
    ///
    /// # Errors
    /// Returns `StaleFence` for retired, foreign or revoked observations, or
    /// `Poisoned` when owner state cannot be checked.
    pub fn validate_fence(&self, fence: &EntityLaneFence) -> Result<(), EntityLaneError> {
        let state = self
            .inner
            .state
            .lock()
            .map_err(|_| EntityLaneError::Poisoned)?;
        state.validate_fence(&fence.stamp)
    }

    /// Remove queued reservations and revoke live owners without releasing them.
    ///
    /// The returned original requests let the host persist their disposition.
    /// Future submissions must still check current trusted namespace authority;
    /// no dormant revocation table or namespace history is retained here.
    ///
    /// # Errors
    /// Returns `Poisoned` when revocation cannot safely update owner state.
    pub fn revoke_namespace(
        &self,
        tenant: &TenantId,
        namespace: &StateNamespaceId,
        incarnation: u64,
    ) -> Result<Vec<EntityRejected<T>>, EntityLaneError> {
        let mut state = self
            .inner
            .state
            .lock()
            .map_err(|_| EntityLaneError::Poisoned)?;
        Ok(state.revoke_namespace(tenant, namespace, incarnation))
    }
}

#[cfg(test)]
mod tests;
