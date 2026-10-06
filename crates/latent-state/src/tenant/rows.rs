//! Actual complete-envelope state and metadata preimages. Upper command/effect
//! accounting contributes its original reserved ledger delta separately.
use super::{row_charge, TenantDelta, TenantUsage};
use crate::embedded::{AtomicBatch, Family, StoreError};
use latent_core::TenantId;

pub(super) fn batch_delta(
    tenant: &TenantId,
    batch: &AtomicBatch,
) -> Result<TenantDelta, StoreError> {
    if batch.mutations.len() > 1024 || batch.expectations.len() > 1024 {
        return Err(StoreError::Capacity);
    }
    let mut delta = TenantDelta::default();
    for (index, row) in batch.mutations.iter().enumerate() {
        if row.key.family != Family::Namespace
            && row.key.family != Family::State
            && !(row.key.family == Family::Maintenance
                && row.key.key.starts_with(b"state-usage-v1\0"))
        {
            continue;
        }
        if batch.mutations[..index]
            .iter()
            .any(|old| old.key == row.key)
        {
            return Err(StoreError::Corrupt);
        }
        let mut matching = batch.expectations.iter().filter(|old| old.key == row.key);
        let original = matching.next().ok_or(StoreError::Corrupt)?;
        if matching.next().is_some() {
            return Err(StoreError::Corrupt);
        }
        for (value, usage) in [
            (original.value.as_deref(), &mut delta.removed),
            (row.value.as_deref(), &mut delta.added),
        ] {
            if let Some(value) = value {
                let contribution = if row.key.family == Family::State {
                    crate::session::tenant_row_usage(tenant, &row.key, value)?
                } else {
                    if value.len() > 8192 {
                        return Err(StoreError::Capacity);
                    }
                    TenantUsage {
                        metadata_rows: 1,
                        metadata_bytes: row_charge(&row.key, value)?,
                        ..TenantUsage::default()
                    }
                };
                let addition = TenantDelta {
                    added: contribution,
                    ..TenantDelta::default()
                };
                *usage = TenantDelta {
                    added: *usage,
                    ..TenantDelta::default()
                }
                .combined(addition)?
                .added;
            }
        }
    }
    Ok(delta)
}
