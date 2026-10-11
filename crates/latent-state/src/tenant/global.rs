//! One fixed closed global metadata allowance, using original control-row CAS.
//! Singleton worst-case headroom reserves recovery/retention control slots.
use super::{codec, guard_key, row_charge, GlobalMetadataAllowance};
use crate::embedded::{AtomicBatch, ExpectedRow, Family, ReadView, RowKey, StoreError};

pub const INSTALLED_GLOBAL_ALLOWANCE: GlobalMetadataAllowance = GlobalMetadataAllowance {
    rows: 64,
    bytes: 256 * 1024,
};
pub(super) const CONTROL_RECEIPT_PREFIX: &[u8] = b"dispatch-control-receipt-v1\0";
const OWNER: &[u8] = b"dispatch-owner-v1\0";
const CONTROL: &[u8] = b"dispatch-control-v1\0";
const SINGLETONS: [(&[u8], usize); 6] = [
    (super::GUARD_PREFIX, super::GUARD_BYTES),
    (crate::recovery::GUARD_KEY, crate::recovery::GUARD_BYTES),
    (b"result-retention-v1\0", 2048),
    (OWNER, 21),
    (CONTROL, 4096),
    (
        crate::store_identity::KEY,
        crate::store_identity::MAXIMUM_ENCODED_BYTES,
    ),
];

/// Called by the original global-control producer while its native view is
/// retained. Original owner/state CAS serializes receipt creation. The immutable
/// installation guard fences a legacy plan across reviewed setup.
pub fn prepare_global_metadata_update(
    view: &ReadView,
    batch: &mut AtomicBatch,
    validate_receipt: impl Fn(&RowKey, &[u8]) -> Result<(), StoreError>,
) -> Result<(), StoreError> {
    let original = view.get_bounded(&guard_key(), super::GUARD_BYTES)?;
    let guard = ExpectedRow {
        key: guard_key(),
        value: original.clone(),
    };
    let mut matching = batch.expectations.iter().filter(|row| row.key == guard.key);
    if let Some(old) = matching.next() {
        if matching.next().is_some() || old.value != guard.value {
            return Err(StoreError::Conflict);
        }
    }
    if batch.mutations.iter().any(|row| row.key == guard.key) {
        return Err(StoreError::Corrupt);
    }
    if let Some(original) = original {
        codec::Guard::decode(&original)?;
        validate_plan(view, batch)?;
        validate_capacity(view, batch, validate_receipt)?;
    }
    if !batch.expectations.iter().any(|row| row.key == guard.key) {
        if batch.expectations.len() >= 1024 {
            return Err(StoreError::Capacity);
        }
        batch.expectations.push(guard);
    }
    Ok(())
}
fn key(bytes: &[u8]) -> RowKey {
    RowKey {
        family: Family::Maintenance,
        key: bytes.to_vec(),
    }
}
fn validate_plan(view: &ReadView, batch: &AtomicBatch) -> Result<(), StoreError> {
    if batch.mutations.len() > 3 || batch.expectations.len() > 1024 {
        return Err(StoreError::Capacity);
    }
    for bytes in [OWNER, CONTROL] {
        let expected_key = key(bytes);
        let actual = view.get_bounded(&expected_key, 4096)?;
        let mut rows = batch
            .expectations
            .iter()
            .filter(|row| row.key == expected_key);
        let original = rows.next().ok_or(StoreError::Corrupt)?;
        if rows.next().is_some() || original.value != actual {
            return Err(StoreError::Conflict);
        }
        if batch
            .mutations
            .iter()
            .filter(|row| row.key == expected_key && row.value.is_some())
            .count()
            != 1
        {
            return Err(StoreError::Corrupt);
        }
    }
    let mut receipts = 0;
    for row in &batch.mutations {
        if row.key.family != Family::Maintenance {
            return Err(StoreError::UnsupportedFormat);
        }
        let maximum = if row.key.key.as_slice() == OWNER {
            21
        } else if row.key.key.as_slice() == CONTROL {
            4096
        } else if row.key.key.starts_with(CONTROL_RECEIPT_PREFIX) {
            receipts += 1;
            4096
        } else {
            return Err(StoreError::UnsupportedFormat);
        };
        if row.value.as_ref().is_none_or(|bytes| bytes.len() > maximum) {
            return Err(StoreError::Capacity);
        }
        if row.key.key.starts_with(CONTROL_RECEIPT_PREFIX) {
            if row.key.key.len() != CONTROL_RECEIPT_PREFIX.len() + 32 {
                return Err(StoreError::Corrupt);
            }
            let mut expectations = batch.expectations.iter().filter(|old| old.key == row.key);
            if expectations.next().is_none_or(|old| old.value.is_some())
                || expectations.next().is_some()
            {
                return Err(StoreError::Corrupt);
            }
        }
    }
    if receipts != 1 {
        return Err(StoreError::Corrupt);
    }
    Ok(())
}
fn validate_capacity(
    view: &ReadView,
    batch: &AtomicBatch,
    validate_receipt: impl Fn(&RowKey, &[u8]) -> Result<(), StoreError>,
) -> Result<(), StoreError> {
    let mut bytes = 0u64;
    for (prefix, maximum) in SINGLETONS {
        view.get_bounded(&key(prefix), maximum)?;
        bytes = bytes
            .checked_add(row_charge(&key(prefix), &vec![0; maximum])?)
            .ok_or(StoreError::Capacity)?;
    }
    let maximum =
        usize::try_from(INSTALLED_GLOBAL_ALLOWANCE.rows).map_err(|_| StoreError::Capacity)?;
    let mut rows = 0usize;
    let mut after = None;
    loop {
        // Fits the original producer's 64KiB retained RecoveryWrite job; no
        // whole allowance-sized buffer or independently growing worker pool.
        let page = view.scan_after(
            Family::Maintenance,
            CONTROL_RECEIPT_PREFIX,
            after.as_deref(),
            3,
            16 * 1024,
        )?;
        rows = rows
            .checked_add(page.rows.len())
            .ok_or(StoreError::Capacity)?;
        if rows + SINGLETONS.len() + 1 > maximum {
            return Err(StoreError::Capacity);
        }
        for (key, value) in &page.rows {
            if value.len() > 4096 {
                return Err(StoreError::Capacity);
            }
            validate_receipt(key, value)?;
            bytes = bytes
                .checked_add(row_charge(key, value)?)
                .ok_or(StoreError::Capacity)?;
            if bytes > INSTALLED_GLOBAL_ALLOWANCE.bytes {
                return Err(StoreError::Capacity);
            }
        }
        after = page.resume;
        if after.is_none() {
            break;
        }
    }
    for row in batch
        .mutations
        .iter()
        .filter(|row| row.key.key.starts_with(CONTROL_RECEIPT_PREFIX))
    {
        if view.get_bounded(&row.key, 4096)?.is_some() {
            return Err(StoreError::Conflict);
        }
        validate_receipt(&row.key, row.value.as_deref().ok_or(StoreError::Corrupt)?)?;
        bytes = bytes
            .checked_add(row_charge(
                &row.key,
                row.value.as_deref().ok_or(StoreError::Corrupt)?,
            )?)
            .ok_or(StoreError::Capacity)?;
    }
    if bytes > INSTALLED_GLOBAL_ALLOWANCE.bytes {
        return Err(StoreError::Capacity);
    }
    Ok(())
}
