use super::{codec, Cell, StateError, StateScope};
use crate::{
    embedded::{Family, RowKey, StoreError},
    tenant::{row_charge, TenantUsage},
};
use latent_core::TenantId;

pub(crate) fn row_usage(
    tenant: &TenantId,
    key: &RowKey,
    value: &[u8],
) -> Result<TenantUsage, StoreError> {
    let rest = key
        .key
        .strip_prefix(b"state-v1\0")
        .ok_or(StoreError::UnsupportedFormat)?;
    let length = rest.get(..2).ok_or(StoreError::Corrupt)?;
    let length = usize::from(u16::from_le_bytes(
        length.try_into().map_err(|_| StoreError::Corrupt)?,
    ));
    if rest.get(2..2 + length) != Some(tenant.0.as_bytes()) {
        return Err(StoreError::Corrupt);
    }
    if key.family != Family::State {
        return Err(StoreError::UnsupportedFormat);
    }
    let cell = Cell::decode(value, u64::MAX)
        .map_err(StateError::storage_error)
        .map_err(|error| error.unwrap_or(StoreError::Corrupt))?;
    let bytes = row_charge(key, value)?;
    Ok(if cell.value.is_some() {
        TenantUsage {
            state_keys: 1,
            state_bytes: bytes,
            ..TenantUsage::default()
        }
    } else {
        TenantUsage {
            tombstone_keys: 1,
            tombstone_bytes: bytes,
            ..TenantUsage::default()
        }
    })
}
pub(super) fn row_expectation(
    scope: &StateScope,
    key: &[u8],
    original: Option<Vec<u8>>,
) -> Result<crate::embedded::ExpectedRow, StateError> {
    let mut bytes = codec::key_prefix(scope)?;
    bytes.extend_from_slice(key);
    Ok(crate::embedded::ExpectedRow {
        key: RowKey {
            family: Family::State,
            key: bytes,
        },
        value: original,
    })
}
