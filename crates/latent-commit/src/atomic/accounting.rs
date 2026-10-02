//! One upper ledger contribution to the original lower tenant counter.
use super::{writer::Usage, AtomicError};
use latent_core::TenantId;
use latent_state::{
    embedded::{AtomicBatch, Family, ReadView},
    tenant::{self, PreparedTenantUpdate, TenantDelta, TenantUsage},
};

pub(super) fn capture(
    view: &ReadView,
    tenant: &TenantId,
    batch: &AtomicBatch,
) -> Result<PreparedTenantUpdate, AtomicError> {
    let origin = tenant::prepare_update(view, tenant, TenantDelta::default())?;
    if origin.is_legacy() {
        return Ok(origin);
    }
    let mut removed = TenantUsage::default();
    let mut added = TenantUsage::default();
    for row in batch.mutations.iter().filter(|row| {
        row.key.family == Family::Maintenance
            && row
                .key
                .key
                .starts_with(latent_state::reservation::QUOTA_PREFIX)
    }) {
        validate_tenant_key(&row.key.key, tenant)?;
        let mut matching = batch.expectations.iter().filter(|old| old.key == row.key);
        let expected = matching.next().ok_or(AtomicError::Corrupt)?;
        if matching.next().is_some() {
            return Err(AtomicError::Corrupt);
        }
        for (value, total) in [
            (expected.value.as_deref(), &mut removed),
            (row.value.as_deref(), &mut added),
        ] {
            if let Some(value) = value {
                let usage = Usage::decode(value)?;
                if !usage.accounted {
                    return Err(AtomicError::UnsupportedFormat);
                }
                for (amount, slot) in [
                    (usage.results, &mut total.result_rows),
                    (usage.result_bytes, &mut total.result_bytes),
                    (usage.effects, &mut total.effect_rows),
                    (usage.effect_bytes, &mut total.effect_bytes),
                    (usage.payload_bytes, &mut total.payload_bytes),
                    (usage.recovery_reserved, &mut total.recovery_bytes),
                ] {
                    *slot = slot.checked_add(amount).ok_or(AtomicError::Limit)?;
                }
            }
        }
    }
    Ok(tenant::prepare_update(
        view,
        tenant,
        TenantDelta { removed, added },
    )?)
}

fn validate_tenant_key(key: &[u8], tenant: &TenantId) -> Result<(), AtomicError> {
    let bytes = key
        .strip_prefix(latent_state::reservation::QUOTA_PREFIX)
        .and_then(|bytes| bytes.strip_prefix(b"ns-v1\0"))
        .ok_or(AtomicError::Corrupt)?;
    let header = bytes.get(..2).ok_or(AtomicError::Corrupt)?;
    let length = usize::from(u16::from_le_bytes(
        header.try_into().map_err(|_| AtomicError::Corrupt)?,
    ));
    if bytes.get(2..2 + length) != Some(tenant.0.as_bytes()) {
        return Err(AtomicError::Corrupt);
    }
    Ok(())
}

pub(super) fn apply(
    view: &ReadView,
    tenant: &TenantId,
    batch: &mut AtomicBatch,
) -> Result<(), AtomicError> {
    let origin = capture(view, tenant, batch)?;
    if origin.is_legacy() {
        origin.append_to(batch)?;
    } else {
        origin.rebuild_batch(batch)?;
    }
    Ok(())
}
