use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::Instant;

use super::owner::OwnerStamp;
use super::{
    EntityDispatch, EntityExecution, EntityLaneError, EntityLanes, EntityPhysicalOwner,
    EntityRejected, EntityRejection, EntityScope,
};

impl<T> EntityLanes<T> {
    /// Select at most one command from the next eligible key, before cell lease.
    ///
    /// Each free key has one round-robin position, independent of its backlog.
    /// Tenant/global active limits include physical cleanup. Current authority is
    /// rechecked outside the lane lock while the newly selected owner is held;
    /// it must also be rechecked atomically at the store's final commit boundary.
    ///
    /// # Errors
    /// Returns `Exhausted` without consuming work when generations are depleted,
    /// `StaleFence` for an inconsistent ready table, or `Poisoned` owner state.
    pub fn try_start_next(
        &self,
        now: Instant,
        mut current_authority: impl FnMut(&EntityScope, &T) -> bool,
    ) -> Result<Option<EntityDispatch<T>>, EntityLaneError> {
        let execution = {
            let mut state = self
                .inner
                .state
                .lock()
                .map_err(|_| EntityLaneError::Poisoned)?;
            if state.snapshot(None).active >= state.limits.global_active {
                return Ok(state.take_expired(now).map(EntityDispatch::Rejected));
            }
            let mut selected = None;
            let candidates = state.ready.len();
            for _ in 0..candidates {
                let Some(scope) = state.ready.pop_front() else {
                    break;
                };
                if state.snapshot(Some(scope.tenant())).active >= state.limits.tenant_active {
                    state.ready.push_back(scope);
                    continue;
                }
                selected = Some(scope);
                break;
            }
            let Some(scope) = selected else {
                return Ok(state.take_expired(now).map(EntityDispatch::Rejected));
            };
            let Some(generation) = state.next_generation.checked_add(1) else {
                state.ready.push_front(scope);
                return Err(EntityLaneError::Exhausted);
            };
            let queued = state
                .lanes
                .get_mut(&scope)
                .and_then(|lane| lane.queue.pop_front())
                .ok_or(EntityLaneError::StaleFence)?;
            if queued.wait_until <= now {
                if state
                    .lanes
                    .get(&scope)
                    .is_some_and(|lane| !lane.queue.is_empty())
                {
                    state.ready.push_back(scope.clone());
                }
                state.remove_empty(&scope);
                return Ok(Some(EntityDispatch::Rejected(EntityRejected {
                    reason: EntityRejection::WaitExpired,
                    request: queued.request,
                })));
            }
            let stamp = Arc::new(OwnerStamp {
                scope: scope.clone(),
                ticket: queued.ticket,
                generation,
                command_identity: queued.request.command_identity.clone(),
                charge: queued.charge,
                deadline: queued.request.deadline,
                cancelled: AtomicBool::new(false),
                revoked: AtomicBool::new(false),
                cleanup: AtomicBool::new(false),
            });
            state.next_generation = generation;
            state
                .lanes
                .get_mut(&scope)
                .ok_or(EntityLaneError::StaleFence)?
                .active = Some(Arc::clone(&stamp));
            EntityExecution {
                request: queued.request,
                owner: EntityPhysicalOwner::new(Arc::clone(&self.inner), stamp),
            }
        };
        let authorized =
            current_authority(execution.request().scope(), execution.request().payload());
        let fence = execution.fence();
        let rejection = if !authorized || fence.stamp.revoked.load(Ordering::Acquire) {
            Some(EntityRejection::AuthorityChanged)
        } else if execution.cancellation_requested(now) {
            Some(EntityRejection::CancelledBeforeExecution)
        } else {
            None
        };
        if let Some(reason) = rejection {
            let (request, owner) = execution.into_owned_work();
            drop(owner);
            Ok(Some(EntityDispatch::Rejected(EntityRejected {
                reason,
                request,
            })))
        } else {
            Ok(Some(EntityDispatch::Ready(execution)))
        }
    }
}
