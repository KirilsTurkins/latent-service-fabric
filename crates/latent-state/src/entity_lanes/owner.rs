use std::fmt;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::Instant;

use super::{
    EntityCancellation, EntityLaneError, EntityLaneRequest, EntityScope, EntityWaitStatus, Inner,
};

pub(super) struct OwnerStamp {
    pub scope: EntityScope,
    pub ticket: u64,
    pub generation: u64,
    pub command_identity: Vec<u8>,
    pub charge: u64,
    pub deadline: Instant,
    pub cancelled: AtomicBool,
    pub revoked: AtomicBool,
    pub cleanup: AtomicBool,
}

/// An observation of one incarnation/owner generation; cloning never owns work.
#[derive(Clone)]
pub struct EntityLaneFence {
    pub(super) stamp: Arc<OwnerStamp>,
}

impl EntityLaneFence {
    #[must_use]
    pub fn scope(&self) -> &EntityScope {
        &self.stamp.scope
    }
    #[must_use]
    pub fn generation(&self) -> u64 {
        self.stamp.generation
    }
}

impl fmt::Debug for EntityLaneFence {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("EntityLaneFence")
            .field("generation", &self.generation())
            .finish_non_exhaustive()
    }
}

struct Release<T> {
    inner: Arc<Inner<T>>,
    stamp: Arc<OwnerStamp>,
}

impl<T> Drop for Release<T> {
    fn drop(&mut self) {
        if let Ok(mut state) = self.inner.state.lock() {
            state.retire(&self.stamp);
        }
    }
}

/// Keeps eligibility charged while actual independently owned physical work lives.
///
/// Clones retain the same owner, and cannot start another guest execution. Move
/// one into every detached engine/commit/cleanup operation before submitting it.
/// Dropping a client future or execution wrapper cannot release those owners.
#[must_use = "physical work must retain its entity owner until actual retirement"]
pub struct EntityPhysicalOwner<T> {
    release: Arc<Release<T>>,
}

impl<T> Clone for EntityPhysicalOwner<T> {
    fn clone(&self) -> Self {
        Self {
            release: Arc::clone(&self.release),
        }
    }
}

impl<T> EntityPhysicalOwner<T> {
    pub(super) fn new(inner: Arc<Inner<T>>, stamp: Arc<OwnerStamp>) -> Self {
        Self {
            release: Arc::new(Release { inner, stamp }),
        }
    }

    #[must_use]
    pub fn fence(&self) -> EntityLaneFence {
        EntityLaneFence {
            stamp: Arc::clone(&self.release.stamp),
        }
    }

    /// Deadline is a cancellation observation, never authority to release work.
    #[must_use]
    pub fn cancellation_requested(&self, now: Instant) -> bool {
        let stamp = &self.release.stamp;
        if now >= stamp.deadline {
            stamp.cancelled.store(true, Ordering::Release);
        }
        stamp.cancelled.load(Ordering::Acquire)
    }

    /// Cleanup remains live ownership, including after revocation or commitment.
    ///
    /// # Errors
    /// Returns `StaleFence` if this physical owner is no longer current, or
    /// `Poisoned` if owner state cannot be checked.
    pub fn begin_cleanup(&self) -> Result<(), EntityLaneError> {
        let state = self
            .release
            .inner
            .state
            .lock()
            .map_err(|_| EntityLaneError::Poisoned)?;
        let stamp = &self.release.stamp;
        if !state
            .lanes
            .get(&stamp.scope)
            .and_then(|lane| lane.active.as_ref())
            .is_some_and(|current| Arc::ptr_eq(current, stamp))
        {
            return Err(EntityLaneError::StaleFence);
        }
        stamp.cleanup.store(true, Ordering::Release);
        Ok(())
    }
}

/// Affine permission to acquire a guest cell for one unchanged accepted command.
#[must_use = "transfer eligibility into the actual execution/commit/cleanup owner"]
pub struct EntityExecution<T> {
    pub(super) request: EntityLaneRequest<T>,
    pub(super) owner: EntityPhysicalOwner<T>,
}

impl<T> EntityExecution<T> {
    pub fn request(&self) -> &EntityLaneRequest<T> {
        &self.request
    }
    #[must_use]
    pub fn fence(&self) -> EntityLaneFence {
        self.owner.fence()
    }
    #[must_use]
    pub fn cancellation_requested(&self, now: Instant) -> bool {
        self.owner.cancellation_requested(now)
    }

    pub fn retain_physical_owner(&self) -> EntityPhysicalOwner<T> {
        self.owner.clone()
    }

    /// Transfer the original command envelope and physical guard into the host's
    /// owned work/commit plan. Seal staging and sever guest references first.
    /// Keep this guard through both physical commit and actual guest cleanup;
    /// durable outbox dispatch acquires its own independent owner afterwards.
    pub fn into_owned_work(self) -> (EntityLaneRequest<T>, EntityPhysicalOwner<T>) {
        (self.request, self.owner)
    }
}

/// An original queued-command reservation; this is not a duplicate-result waiter.
/// Dropping it removes queued work. Once active, detachment leaves physical work
/// unchanged; explicit command cancellation must call `request_cancel`.
#[must_use = "dropping a queued reservation cancels the original accepted command"]
pub struct EntityWaiter<T> {
    inner: Arc<Inner<T>>,
    scope: EntityScope,
    ticket: u64,
    identity: Arc<()>,
}

impl<T> EntityWaiter<T> {
    pub(super) fn new(
        inner: Arc<Inner<T>>,
        scope: EntityScope,
        ticket: u64,
        identity: Arc<()>,
    ) -> Self {
        Self {
            inner,
            scope,
            ticket,
            identity,
        }
    }

    /// # Errors
    /// Returns `StaleFence` for a foreign ticket or `Poisoned` owner state.
    pub fn status(&self) -> Result<EntityWaitStatus, EntityLaneError> {
        let state = self
            .inner
            .state
            .lock()
            .map_err(|_| EntityLaneError::Poisoned)?;
        if !Arc::ptr_eq(&state.identity, &self.identity) {
            return Err(EntityLaneError::StaleFence);
        }
        if let Some(lane) = state.lanes.get(&self.scope) {
            if lane.queue.iter().any(|queued| queued.ticket == self.ticket) {
                return Ok(EntityWaitStatus::Queued);
            }
            if let Some(active) = lane
                .active
                .as_ref()
                .filter(|active| active.ticket == self.ticket)
            {
                return Ok(EntityWaitStatus::Active {
                    generation: active.generation,
                    cleanup: active.cleanup.load(Ordering::Acquire),
                    cancellation_requested: active.cancelled.load(Ordering::Acquire),
                });
            }
        }
        Ok(EntityWaitStatus::Retired)
    }

    /// # Errors
    /// Returns `StaleFence` for a foreign ticket or `Poisoned` owner state.
    pub fn request_cancel(&self) -> Result<EntityCancellation<T>, EntityLaneError> {
        let mut state = self
            .inner
            .state
            .lock()
            .map_err(|_| EntityLaneError::Poisoned)?;
        if !Arc::ptr_eq(&state.identity, &self.identity) {
            return Err(EntityLaneError::StaleFence);
        }
        if let Some(request) = state.remove_queued(&self.scope, self.ticket) {
            return Ok(EntityCancellation::Queued(request));
        }
        if let Some(active) = state
            .lanes
            .get(&self.scope)
            .and_then(|lane| lane.active.as_ref())
            .filter(|active| active.ticket == self.ticket)
        {
            active.cancelled.store(true, Ordering::Release);
            return Ok(EntityCancellation::ActiveRequested);
        }
        Ok(EntityCancellation::Retired)
    }
}

impl<T> Drop for EntityWaiter<T> {
    fn drop(&mut self) {
        if let Ok(mut state) = self.inner.state.lock() {
            // Drop payloads after unlocking: host payload destructors may own
            // other admission/cleanup resources or reenter an observation API.
            let request = state.remove_queued(&self.scope, self.ticket);
            drop(state);
            drop(request);
        }
    }
}
