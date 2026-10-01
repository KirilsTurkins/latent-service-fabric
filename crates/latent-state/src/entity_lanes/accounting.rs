use std::mem::size_of;
use std::time::Instant;

use super::owner::OwnerStamp;
use super::state::{Lane, Queued, State};
use super::{
    EntityCallKind, EntityLaneError, EntityLaneLimit, EntityLaneRequest, EntityLaneSnapshot,
};

fn cap(
    current: u64,
    addition: u64,
    limit: u64,
    kind: EntityLaneLimit,
) -> Result<(), EntityLaneError> {
    if current
        .checked_add(addition)
        .is_none_or(|next| next > limit)
    {
        return Err(EntityLaneError::Backpressure(kind));
    }
    Ok(())
}

fn count(
    current: usize,
    addition: usize,
    limit: usize,
    kind: EntityLaneLimit,
) -> Result<(), EntityLaneError> {
    if current
        .checked_add(addition)
        .is_none_or(|next| next > limit)
    {
        return Err(EntityLaneError::Backpressure(kind));
    }
    Ok(())
}

impl<T> State<T> {
    fn check_shape(
        &self,
        request: &EntityLaneRequest<T>,
        now: Instant,
    ) -> Result<(usize, Instant), EntityLaneError> {
        let limits = &self.limits;
        if request.call_kind == EntityCallKind::SynchronousTransactionalChild {
            return Err(EntityLaneError::NestedTransactionalCall);
        }
        if request.deadline <= now {
            return Err(EntityLaneError::Expired);
        }
        if request.command_identity.is_empty() {
            return Err(EntityLaneError::InvalidCommandIdentity);
        }
        count(
            0,
            request.command_identity.len(),
            limits.command_identity_bytes,
            EntityLaneLimit::CommandIdentityBytes,
        )?;
        let scope_bytes = request
            .scope
            .tenant
            .0
            .len()
            .checked_add(request.scope.namespace.0.len())
            .and_then(|n| n.checked_add(request.scope.entity.0.len()))
            .ok_or(EntityLaneError::Exhausted)?;
        count(
            0,
            scope_bytes,
            limits.scope_bytes,
            EntityLaneLimit::ScopeBytes,
        )?;
        let maximum_wait = now
            .checked_add(limits.maximum_wait_age)
            .ok_or(EntityLaneError::Exhausted)?;
        Ok((scope_bytes, request.deadline.min(maximum_wait)))
    }

    pub(super) fn check_admission(
        &self,
        request: &EntityLaneRequest<T>,
        now: Instant,
    ) -> Result<(u64, Instant), EntityLaneError> {
        let (scope_bytes, wait_until) = self.check_shape(request, now)?;
        let limits = &self.limits;
        let lane = self.lanes.get(&request.scope);
        if lane.is_some_and(|lane| {
            lane.active
                .as_ref()
                .is_some_and(|owner| owner.command_identity == request.command_identity)
                || lane
                    .queue
                    .iter()
                    .any(|q| q.request.command_identity == request.command_identity)
        }) {
            return Err(EntityLaneError::Duplicate);
        }

        let global = self.snapshot(None);
        let tenant = self.snapshot(Some(&request.scope.tenant));
        count(
            global.queued,
            1,
            limits.global_queued,
            EntityLaneLimit::GlobalQueue,
        )?;
        count(
            tenant.queued,
            1,
            limits.tenant_queued,
            EntityLaneLimit::TenantQueue,
        )?;
        count(
            lane.map_or(0, |l| l.queue.len()),
            1,
            limits.entity_queued,
            EntityLaneLimit::EntityQueue,
        )?;
        let new_key = usize::from(lane.is_none());
        count(
            global.keys,
            new_key,
            limits.global_keys,
            EntityLaneLimit::GlobalKeys,
        )?;
        count(
            tenant.keys,
            new_key,
            limits.tenant_keys,
            EntityLaneLimit::TenantKeys,
        )?;

        // Scope copies, identity copies and fixed request/owner bookkeeping have
        // finite explicit charge; the host separately owns the shared ledger.
        let metadata = scope_bytes
            .checked_mul(6)
            .and_then(|n| {
                request
                    .command_identity
                    .len()
                    .checked_mul(2)
                    .and_then(|ids| n.checked_add(ids))
            })
            .and_then(|n| n.checked_add(size_of::<Queued<T>>()))
            .and_then(|n| n.checked_add(size_of::<Lane<T>>()))
            .and_then(|n| n.checked_add(size_of::<OwnerStamp>()))
            .and_then(|n| u64::try_from(n).ok())
            .ok_or(EntityLaneError::Exhausted)?;
        let charge = request
            .retained_bytes
            .checked_add(metadata)
            .ok_or(EntityLaneError::Exhausted)?;
        cap(
            global.retained_bytes(),
            charge,
            limits.global_bytes,
            EntityLaneLimit::GlobalBytes,
        )?;
        cap(
            tenant.retained_bytes(),
            charge,
            limits.tenant_bytes,
            EntityLaneLimit::TenantBytes,
        )?;
        let entity_bytes = lane.map_or(0, Lane::retained_bytes);
        cap(
            entity_bytes,
            charge,
            limits.entity_bytes,
            EntityLaneLimit::EntityBytes,
        )?;
        Ok((charge, wait_until))
    }

    pub(super) fn snapshot(&self, tenant: Option<&latent_core::TenantId>) -> EntityLaneSnapshot {
        let mut snapshot = EntityLaneSnapshot::default();
        for (scope, lane) in &self.lanes {
            if tenant.is_some_and(|tenant| tenant != &scope.tenant) {
                continue;
            }
            snapshot.keys += 1;
            snapshot.queued += lane.queue.len();
            snapshot.queued_bytes += lane.queue.iter().map(|queued| queued.charge).sum::<u64>();
            if let Some(active) = &lane.active {
                snapshot.active += 1;
                snapshot.active_bytes += active.charge;
                snapshot.cleanup +=
                    usize::from(active.cleanup.load(std::sync::atomic::Ordering::Acquire));
            }
        }
        snapshot
    }
}
