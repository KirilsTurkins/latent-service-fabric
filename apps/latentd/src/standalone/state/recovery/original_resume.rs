//! Original unattempted work is distinct from restored recovery activation.
use latent_effects::dispatch::{Disposition, EffectRecord};
use latent_state::{
    embedded::{Family, ReadView, StoreError},
    namespace::{
        compatibility::{RetainedFormat, RetainedInventory, RetainedKind},
        history::HistoryStatus,
        NamespaceStatus,
    },
    recovery::namespace_resume::{
        NamespaceResumeObservation, NamespaceResumePlan, NamespaceResumeRequest,
    },
};
use std::{collections::BTreeMap, time::Instant};

pub(super) fn prepare(
    view: &ReadView,
    request: &NamespaceResumeRequest,
    inventory: &RetainedInventory,
    deadline: Instant,
    current: impl FnOnce() -> Result<(), StoreError>,
) -> Result<NamespaceResumePlan, StoreError> {
    NamespaceResumePlan::prepare(view, request, |view, request, observed| {
        if inventory.total().unresolved != 0 {
            require_original_pending(view, request, &observed, inventory, deadline)?;
        } else {
            inventory
                .require_retirement_drained()
                .map_err(|_| StoreError::Unavailable)?;
        }
        current()
    })
}

fn require_original_pending(
    view: &ReadView,
    request: &NamespaceResumeRequest,
    observed: &NamespaceResumeObservation<'_>,
    inventory: &RetainedInventory,
    deadline: Instant,
) -> Result<(), StoreError> {
    if observed.guard.is_some()
        || observed.history.status != HistoryStatus::Ready
        || (observed.original_receipt.is_none()
            && observed.namespace.status != NamespaceStatus::Quiescing)
        || observed.namespace.tenant != request.scope.tenant
        || observed.namespace.id != request.scope.namespace
        || observed.namespace.version.incarnation != request.scope.incarnation
        || observed.namespace.state_schema != request.scope.state_schema
        || inventory.entries().iter().any(|(format, count)| {
            count.unresolved != 0 && format.kind != RetainedKind::EffectEnvelope
        })
    {
        return Err(StoreError::Unavailable);
    }
    let mut decoded = BTreeMap::<RetainedFormat, u64>::new();
    latent_state::recovery::snapshot::visit_view(view, deadline, |_, key, bytes| {
        if key.family != Family::Outbox {
            return Ok(());
        }
        let effect = EffectRecord::decode(bytes).map_err(|_| StoreError::Corrupt)?;
        let authority = effect.authority().map_err(|_| StoreError::Corrupt)?;
        let scope = authority.scope();
        if scope.tenant != observed.namespace.tenant.0
            || scope.namespace != observed.namespace.id.0
            || scope.incarnation != observed.namespace.version.incarnation
        {
            return Err(StoreError::UnsupportedFormat);
        }
        if effect.disposition().terminal() {
            return Ok(());
        }
        if effect.disposition() != Disposition::Pending
            || effect.attempts() != 0
            || effect.owner_epoch() != 0
            || effect.claim_generation() != 0
            || effect.history_sequence() != 0
            || effect.send_started()
            || effect.retry_at_millis() != 0
            || effect.latest().is_some()
            || effect.recovery_close_digest().is_some()
        {
            return Err(StoreError::Unavailable);
        }
        let (identity, version) = effect.durable_format();
        let count = decoded
            .entry(RetainedFormat {
                kind: RetainedKind::EffectEnvelope,
                identity: format!("{identity}:{version}"),
            })
            .or_default();
        *count = count.checked_add(1).ok_or(StoreError::Capacity)?;
        Ok(())
    })?;
    if decoded.is_empty()
        || decoded.iter().any(|(format, count)| {
            inventory
                .entries()
                .get(format)
                .map(|entry| entry.unresolved)
                != Some(*count)
        })
        || inventory.entries().iter().any(|(format, count)| {
            count.unresolved != 0 && decoded.get(format).copied() != Some(count.unresolved)
        })
    {
        return Err(StoreError::Unavailable);
    }
    Ok(())
}

#[cfg(all(test, target_os = "linux", target_arch = "x86_64"))]
mod tests;
