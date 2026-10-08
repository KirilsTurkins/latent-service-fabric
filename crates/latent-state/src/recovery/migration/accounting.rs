//! Migration contributes only its own exact progress/metadata originals. The
//! original tenant owner performs every checked category change and row CAS.
use super::AggregateMigrationProgress;
use crate::{
    embedded::{AtomicBatch, ReadView, RowKey, StoreError},
    tenant::{prepare_update, row_charge, TenantDelta, TenantRecord, TenantUsage},
};
use latent_core::TenantId;

pub(super) fn append(
    view: &ReadView,
    tenant: &TenantId,
    key: &RowKey,
    original: Option<&[u8]>,
    next: &[u8],
    batch: &mut AtomicBatch,
) -> Result<(), StoreError> {
    // State/namespace/history/LSU contributions are rebuilt by their canonical
    // owner. The supported migration producer contributes its Maintenance row.
    prepare_update(
        view,
        tenant,
        TenantDelta {
            removed: metadata(key, original)?,
            added: metadata(key, Some(next))?,
        },
    )?
    .rebuild_batch(batch)
}

pub(super) fn candidate_quota(
    batch: &AtomicBatch,
    tenant: &TenantId,
) -> Result<Option<Vec<u8>>, StoreError> {
    let key = crate::tenant::quota_key(tenant)?;
    let mut rows = batch.mutations.iter().filter(|row| row.key == key);
    let bytes = match rows.next() {
        Some(row) => Some(row.value.clone().ok_or(StoreError::Corrupt)?),
        None => None,
    };
    if rows.next().is_some() {
        return Err(StoreError::Corrupt);
    }
    Ok(bytes)
}

pub(super) fn require_staged(
    view: &ReadView,
    key: &RowKey,
    bytes: &[u8],
    progress: &AggregateMigrationProgress,
) -> Result<(), StoreError> {
    let original = progress.quota_expectation(false)?;
    let staged = progress.quota_expectation(true)?;
    if view.get_bounded(&staged.key, crate::tenant::RECORD_BYTES)? != staged.value {
        return Err(StoreError::Conflict);
    }
    let namespace = progress.source_namespace()?;
    let current = crate::tenant::inspect(view, &namespace.tenant)?;
    let Some(source_bytes) = original.value else {
        return if current.is_none() {
            Ok(())
        } else {
            Err(StoreError::Corrupt)
        };
    };
    let source = TenantRecord::decode(&source_bytes)?;
    let history = progress.history_expectation()?;
    let paused = progress.staged_history()?;
    let stage_added = sum(
        metadata(&history.key, Some(&paused))?,
        metadata(key, Some(bytes))?,
    )?;
    let stage_removed = metadata(&history.key, history.value.as_deref())?;
    // Verify the stored Stage quota using the SAME canonical arithmetic. This
    // temporary inverse plan is never submitted, and cannot renew a quota.
    let mut inverse = AtomicBatch::default();
    prepare_update(
        view,
        &namespace.tenant,
        TenantDelta {
            removed: stage_added,
            added: stage_removed,
        },
    )?
    .append_to(&mut inverse)?;
    let reverted = TenantRecord::decode(
        &candidate_quota(&inverse, &namespace.tenant)?.ok_or(StoreError::Corrupt)?,
    )?;
    if reverted.quota != source.quota
        || reverted.usage != source.usage
        || Some(reverted.generation) != source.generation.checked_add(2)
    {
        return Err(StoreError::Corrupt);
    }
    Ok(())
}

fn metadata(key: &RowKey, bytes: Option<&[u8]>) -> Result<TenantUsage, StoreError> {
    Ok(match bytes {
        Some(bytes) => TenantUsage {
            metadata_rows: 1,
            metadata_bytes: row_charge(key, bytes)?,
            ..TenantUsage::default()
        },
        None => TenantUsage::default(),
    })
}

fn sum(left: TenantUsage, right: TenantUsage) -> Result<TenantUsage, StoreError> {
    Ok(TenantUsage {
        metadata_rows: left
            .metadata_rows
            .checked_add(right.metadata_rows)
            .ok_or(StoreError::Capacity)?,
        metadata_bytes: left
            .metadata_bytes
            .checked_add(right.metadata_bytes)
            .ok_or(StoreError::Capacity)?,
        ..TenantUsage::default()
    })
}
