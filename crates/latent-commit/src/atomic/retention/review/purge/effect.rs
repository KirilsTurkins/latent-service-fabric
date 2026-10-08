use super::super::{operation::Captured, RetentionAudit};
use crate::atomic::{
    writer::{row_charge, Usage},
    AtomicError,
};
use latent_effects::dispatch_store::DispatchCatalog;
use latent_state::embedded::{Family, ReadView};

pub(super) fn one(
    view: &ReadView,
    captured: &mut Captured,
    audit: &mut RetentionAudit,
    usage: &mut Usage,
) -> Result<u64, AtomicError> {
    let effect = captured
        .record
        .effects
        .get(usize::try_from(audit.purged).map_err(|_| AtomicError::Limit)?)
        .ok_or(AtomicError::Corrupt)?;
    let closure = DispatchCatalog::retention_rows(view, &effect.hex())?;
    if !closure.record.disposition().terminal() {
        return Err(AtomicError::RecoveryRequired);
    }
    let authority = closure.record.authority()?;
    super::super::operation::verify_effect(&captured.record, &authority, *effect)?;
    usage.effect_bytes = usage
        .effect_bytes
        .checked_sub(DispatchCatalog::retention_charge(&authority)?)
        .ok_or(AtomicError::Corrupt)?;
    usage.effects = usage.effects.checked_sub(1).ok_or(AtomicError::Corrupt)?;
    captured.namespace.pins.unresolved_effects = captured
        .namespace
        .pins
        .unresolved_effects
        .checked_sub(1)
        .ok_or(AtomicError::Corrupt)?;
    captured.namespace.pins.payload_references = captured
        .namespace
        .pins
        .payload_references
        .checked_sub(1)
        .ok_or(AtomicError::Corrupt)?;
    let mut reclaimed = 0u64;
    for row in closure.expectations {
        let destructive = closure.reclaim.contains(&row.key);
        if destructive {
            let bytes = row.value.as_ref().ok_or(AtomicError::Corrupt)?;
            if row.key.family == Family::PayloadReference {
                usage.payload_bytes = usage
                    .payload_bytes
                    .checked_sub(row_charge(&row.key, bytes)?)
                    .ok_or(AtomicError::Corrupt)?;
            }
            reclaimed = reclaimed
                .checked_add((row.key.key.len() + bytes.len() + 1) as u64)
                .ok_or(AtomicError::Limit)?;
            captured.plan.mutation(row.key.clone(), None)?;
        }
        captured.plan.expect(row)?;
    }
    audit.purged = audit.purged.checked_add(1).ok_or(AtomicError::Limit)?;
    Ok(reclaimed)
}
