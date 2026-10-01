//! Descriptive, one-floor cleanup for the existing namespace destruction owner.
//! Permission and actual lifecycle drain remain host-owned final acceptance.
use super::{plan, RetiredCommand, RetryIndex};
use crate::atomic::{
    record::{attempt_row_key, command_row_key, result_row_key},
    retention::StepGuard,
    writer::{fenced_error, row_charge, usage_row_key, Usage},
    AtomicError, Identity, MaintenanceClock, ResultMaintenanceOwner,
};
use latent_core::{StateNamespaceId, TenantId};
use latent_state::{
    embedded::{AtomicBatch, EmbeddedStore, ExpectedRow, ReadView, RowKey},
    namespace::{NamespaceRecord, NamespaceStatus, NamespaceVersion},
    reservation::reservation_key,
};

/// Host-selected identity and exact durable namespace version. A caller cannot
/// supply an active-count guess or a force flag. Knowing these values is not a
/// destructive grant or proof that live lifecycle owners have drained.
#[derive(Debug, Clone)]
pub struct FloorReleaseRequest {
    pub tenant: TenantId,
    pub namespace: StateNamespaceId,
    pub expected: NamespaceVersion,
    pub command: Identity,
}

/// One bounded plan owns the original shared maintenance step until physical
/// publication finishes. It contains no native view, authority or worker.
pub struct PreparedFloorRelease<'a> {
    step: StepGuard<'a>,
    plan: plan::Plan,
    floor: RetiredCommand,
    before: NamespaceRecord,
    after: NamespaceRecord,
    reclaimed_bytes: u64,
}
impl PreparedFloorRelease<'_> {
    #[must_use]
    pub fn batch(&self) -> &AtomicBatch {
        &self.plan.batch
    }
    #[must_use]
    pub fn before(&self) -> &NamespaceRecord {
        &self.before
    }
    #[must_use]
    pub fn after(&self) -> &NamespaceRecord {
        &self.after
    }
    #[must_use]
    pub fn floor(&self) -> &RetiredCommand {
        &self.floor
    }
    #[must_use]
    pub const fn reclaimed_bytes(&self) -> u64 {
        self.reclaimed_bytes
    }

    /// Compose only the existing management owner's bounded operation/audit
    /// rows. Exact duplicate expectations must agree; replacement rows cannot
    /// override this cleanup's namespace, quota, guard or identity mutations.
    pub fn append_management_batch(&mut self, batch: AtomicBatch) -> Result<(), AtomicError> {
        if batch.mutations.iter().any(|row| {
            self.plan
                .batch
                .expectations
                .iter()
                .any(|old| old.key == row.key)
        }) {
            return Err(AtomicError::Corrupt);
        }
        self.plan.append(batch)
    }

    /// Drop the planning view before calling. Final acceptance must hold the
    /// current explicit namespace-destroy policy and actual lifecycle drain,
    /// and publish its audit/receipt in the composed physical batch. The native
    /// reader gate and exact row CAS run before that callback. Policy failure,
    /// stale observations or a physically live reader cannot delete a floor.
    pub fn publish(
        self,
        store: &EmbeddedStore,
        accept: impl FnOnce(
            &NamespaceRecord,
            &NamespaceRecord,
            &RetiredCommand,
        ) -> Result<(), AtomicError>,
    ) -> Result<NamespaceRecord, AtomicError> {
        let Self {
            step,
            plan,
            floor,
            before,
            after,
            ..
        } = self;
        store
            .apply_reclamation_fenced(plan.batch, || accept(&before, &after, &floor))
            .map_err(fenced_error)?;
        drop(step);
        Ok(after)
    }
}

impl ResultMaintenanceOwner {
    /// Release one already terminalized/purged identity only in a retired
    /// namespace. Ordinary expiry, deployment deletion and recovery reads never
    /// call this operation. Quiescing alone is insufficient; original results,
    /// pending reservations, effects, payloads and inboxes must already drain.
    pub fn prepare_floor_release<'a>(
        &'a self,
        view: &ReadView,
        request: &FloorReleaseRequest,
        clock: MaintenanceClock,
    ) -> Result<PreparedFloorRelease<'a>, AtomicError> {
        let step = self.enter()?;
        let CapturedFloor {
            before,
            floor,
            floor_key,
            bytes,
            namespace_key,
            mut plan,
        } = CapturedFloor::read(view, request)?;
        clock.time.check(floor.retired_at)?;
        let (mut usage, usage_key, old_usage) = Usage::read_row(
            view,
            usage_row_key(&request.tenant.0, &request.namespace.0, floor.incarnation)?,
        )?;
        drained(&before, &usage)?;
        let progress = usage
            .review_clock
            .clone()
            .ok_or(AtomicError::RecoveryRequired)?;
        clock.next(&progress)?;
        absent_dependencies(view, &mut plan, request.command)?;
        let removed = row_charge(&floor_key, &bytes)?;
        usage.results = usage.results.checked_sub(1).ok_or(AtomicError::Corrupt)?;
        usage.result_bytes = usage
            .result_bytes
            .checked_sub(removed)
            .ok_or(AtomicError::Corrupt)?;
        let mut after = before.clone();
        after.pins.retained_results = after
            .pins
            .retained_results
            .checked_sub(1)
            .ok_or(AtomicError::Corrupt)?;
        after.version.generation = after
            .version
            .generation
            .checked_add(1)
            .ok_or(AtomicError::Limit)?;
        let mut reclaimed_bytes = removed;
        let next_usage = if usage.results == 0 {
            let quota_charge = row_charge(
                &usage_key,
                old_usage.as_deref().ok_or(AtomicError::Corrupt)?,
            )?;
            if usage.result_bytes != quota_charge {
                return Err(AtomicError::Corrupt);
            }
            reclaimed_bytes = reclaimed_bytes
                .checked_add(quota_charge)
                .ok_or(AtomicError::Limit)?;
            None
        } else {
            plan::advance(&mut usage, progress, clock, reclaimed_bytes, true)?;
            usage.check(&after)?;
            Some(usage.encode()?)
        };
        after.validate().map_err(|_| AtomicError::Corrupt)?;
        plan.replace(floor_key, Some(bytes), None)?;
        plan.replace(usage_key, old_usage, next_usage)?;
        plan.mutation(
            namespace_key,
            Some(after.encode().map_err(|_| AtomicError::Corrupt)?),
        )?;
        Ok(PreparedFloorRelease {
            step,
            plan,
            floor,
            before,
            after,
            reclaimed_bytes,
        })
    }
}

struct CapturedFloor {
    before: NamespaceRecord,
    floor: RetiredCommand,
    floor_key: RowKey,
    bytes: Vec<u8>,
    namespace_key: RowKey,
    plan: plan::Plan,
}
impl CapturedFloor {
    fn read(view: &ReadView, request: &FloorReleaseRequest) -> Result<Self, AtomicError> {
        crate::atomic::id(&request.tenant.0)?;
        crate::atomic::id(&request.namespace.0)?;
        if request.expected.incarnation == 0
            || request.expected.generation == 0
            || request.command == Identity([0; 32])
        {
            return Err(AtomicError::Invalid);
        }
        let rows = latent_state::recovery::maintenance::namespace_expectations(
            view,
            &request.tenant,
            &request.namespace,
            request.expected.incarnation,
        )?;
        let before = NamespaceRecord::decode(rows[1].value.as_deref().ok_or(AtomicError::Corrupt)?)
            .map_err(|_| AtomicError::Corrupt)?;
        if before.version != request.expected {
            return Err(AtomicError::Conflict);
        }
        if before.status != NamespaceStatus::Retired {
            return Err(AtomicError::RecoveryRequired);
        }
        let namespace_key = rows[1].key.clone();
        let mut plan = plan::Plan::default();
        for row in rows {
            plan.expect(row)?;
        }
        let floor_key = command_row_key(request.command);
        let bytes = view.get(&floor_key)?.ok_or(AtomicError::NotFound)?;
        if !RetiredCommand::is_present(&bytes) {
            return Err(AtomicError::RecoveryRequired);
        }
        let floor = RetiredCommand::decode(&bytes)?;
        if floor.command != request.command
            || floor.tenant != request.tenant.0
            || floor.namespace_name != request.namespace.0
            || floor.incarnation != request.expected.incarnation
        {
            return Err(AtomicError::Conflict);
        }
        Ok(Self {
            before,
            floor,
            floor_key,
            bytes,
            namespace_key,
            plan,
        })
    }
}

fn drained(namespace: &NamespaceRecord, usage: &Usage) -> Result<(), AtomicError> {
    if !usage.accounted {
        return Err(AtomicError::UnsupportedFormat);
    }
    if namespace.pins.unresolved_effects != 0
        || namespace.pins.payload_references != 0
        || namespace.pins.inbox_protection != 0
        || usage.effects != 0
        || usage.effect_bytes != 0
        || usage.payload_bytes != 0
        || usage.reserved != 0
        || usage.recovery_reserved != 0
    {
        return Err(AtomicError::RecoveryRequired);
    }
    if usage.results == 0 || namespace.pins.retained_results != usage.results {
        return Err(AtomicError::Corrupt);
    }
    Ok(())
}

fn absent_dependencies(
    view: &ReadView,
    plan: &mut plan::Plan,
    command: Identity,
) -> Result<(), AtomicError> {
    let mut keys = Vec::with_capacity(49);
    keys.push(reservation_key(&command.bytes())?);
    // The supported original attempt codec has a closed maximum of sixteen.
    // Every previous result and retry backpointer must actually be gone.
    for attempt in 1..=16 {
        keys.push(attempt_row_key(command, attempt));
        keys.push(result_row_key(command, attempt));
        if attempt >= 2 {
            keys.push(RetryIndex::row_key(command, attempt));
        }
    }
    for key in keys {
        if view.get(&key)?.is_some() {
            return Err(AtomicError::Corrupt);
        }
        plan.expect(ExpectedRow { key, value: None })?;
    }
    Ok(())
}
