//! Finite, explicitly installed tenant accounting. Quotas are reviewed inputs,
//! never inferred from namespace ceilings. The original reserved writer and
//! current host policy own installation and every physical publication.
//!
//! An absent guard is the explicit lower-store legacy profile. Once installed,
//! missing tenants, changed limits and inconsistent counter originals refuse
//! admission. Business owners compose one guarded counter update into the SAME
//! state/command/effect transaction; descriptors grant no access or retry.

mod codec;
mod install;
mod rows;
mod update;

use crate::embedded::{Family, ReadView, RowKey, StoreError};
pub use install::{
    configuration_digest, prepare_install, require_installation, PreparedTenantInstallation,
};
use latent_core::TenantId;
pub use update::{prepare_metadata_update, prepare_update, PreparedTenantUpdate, TenantDelta};

pub const MAXIMUM_TENANTS: usize = 32;
pub const GUARD_BYTES: usize = 12 * 1024;
pub const RECORD_BYTES: usize = 1024;
pub const GUARD_PREFIX: &[u8] = b"tenant-accounting-v1\0";
pub const QUOTA_PREFIX: &[u8] = b"tenant-quota-v1\0";

/// Actual encoded key/value plus family byte and a conservative 64-byte index
/// allowance. Logical charges do not replace the original physical file fence.
pub fn row_charge(key: &RowKey, value: &[u8]) -> Result<u64, StoreError> {
    u64::try_from(key.key.len())
        .ok()
        .and_then(|bytes| bytes.checked_add(value.len() as u64))
        .and_then(|bytes| bytes.checked_add(65))
        .ok_or(StoreError::Capacity)
}

/// Durable ownership and precharged obligations, not remaining runtime fuel.
/// Results include command/attempt/inbox identities and promised body space;
/// effect bytes include the finite delivery/history reservation. Metadata has
/// an independent allowance, including this preinstalled accounting record.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct TenantUsage {
    pub state_keys: u64,
    pub state_bytes: u64,
    pub tombstone_keys: u64,
    pub tombstone_bytes: u64,
    pub result_rows: u64,
    pub result_bytes: u64,
    pub effect_rows: u64,
    pub effect_bytes: u64,
    pub payload_bytes: u64,
    pub recovery_bytes: u64,
    pub metadata_rows: u64,
    pub metadata_bytes: u64,
}
impl TenantUsage {
    fn values(self) -> [u64; 12] {
        [
            self.state_keys,
            self.state_bytes,
            self.tombstone_keys,
            self.tombstone_bytes,
            self.result_rows,
            self.result_bytes,
            self.effect_rows,
            self.effect_bytes,
            self.payload_bytes,
            self.recovery_bytes,
            self.metadata_rows,
            self.metadata_bytes,
        ]
    }
    fn from_values(values: [u64; 12]) -> Self {
        Self {
            state_keys: values[0],
            state_bytes: values[1],
            tombstone_keys: values[2],
            tombstone_bytes: values[3],
            result_rows: values[4],
            result_bytes: values[5],
            effect_rows: values[6],
            effect_bytes: values[7],
            payload_bytes: values[8],
            recovery_bytes: values[9],
            metadata_rows: values[10],
            metadata_bytes: values[11],
        }
    }
    fn validate(self) -> Result<(), StoreError> {
        for (index, value) in self.values().into_iter().enumerate() {
            let maximum = if [0, 2, 4, 6, 10].contains(&index) {
                65_536
            } else {
                1024 * 1024 * 1024
            };
            if value > maximum {
                return Err(StoreError::Invalid);
            }
        }
        Ok(())
    }
    fn within(self, limits: Self) -> bool {
        self.values()
            .into_iter()
            .zip(limits.values())
            .all(|(value, limit)| value <= limit)
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TenantQuota {
    pub tenant: TenantId,
    pub limits: TenantUsage,
}
impl TenantQuota {
    pub fn validate(&self) -> Result<(), StoreError> {
        identity(&self.tenant)?;
        self.limits.validate()?;
        if self.limits.metadata_rows == 0
            || self.limits.metadata_bytes < RECORD_BYTES as u64
            || self.limits.recovery_bytes > self.limits.result_bytes
        {
            return Err(StoreError::Invalid);
        }
        Ok(())
    }
    pub fn digest(&self) -> Result<[u8; 32], StoreError> {
        self.validate()?;
        Ok(codec::hash(&codec::quota_bytes(self)))
    }
}

/// Original immutable limits and exact current aggregate generation.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TenantRecord {
    pub quota: TenantQuota,
    pub generation: u64,
    pub usage: TenantUsage,
}
impl TenantRecord {
    pub fn encode(&self) -> Result<Vec<u8>, StoreError> {
        codec::encode_record(self)
    }
    pub fn decode(bytes: &[u8]) -> Result<Self, StoreError> {
        codec::decode_record(bytes)
    }
    fn validate(&self) -> Result<(), StoreError> {
        self.quota.validate()?;
        self.usage.validate()?;
        if self.generation == 0
            || self.usage.metadata_rows == 0
            || !self.usage.within(self.quota.limits)
        {
            return Err(StoreError::Corrupt);
        }
        let charge = row_charge(&quota_key(&self.quota.tenant)?, &vec![0; RECORD_BYTES])?;
        if self.usage.metadata_bytes < charge {
            return Err(StoreError::Corrupt);
        }
        Ok(())
    }
}

#[must_use]
pub fn guard_key() -> RowKey {
    RowKey {
        family: Family::Maintenance,
        key: GUARD_PREFIX.to_vec(),
    }
}
pub fn quota_key(tenant: &TenantId) -> Result<RowKey, StoreError> {
    identity(tenant)?;
    let mut key = QUOTA_PREFIX.to_vec();
    codec::text(&mut key, &tenant.0);
    Ok(RowKey {
        family: Family::Maintenance,
        key,
    })
}
fn identity(tenant: &TenantId) -> Result<(), StoreError> {
    latent_core::transaction_contract::identity(&tenant.0).map_err(|_| StoreError::Invalid)?;
    if tenant.0.chars().any(char::is_control) {
        return Err(StoreError::Invalid);
    }
    Ok(())
}

/// Query/admission read only: never create a counter or refresh its identity.
/// An installed guard requires the exact immutable tenant declaration.
pub fn inspect(view: &ReadView, tenant: &TenantId) -> Result<Option<TenantRecord>, StoreError> {
    Ok(codec::capture(view, tenant)?.map(|captured| captured.record))
}

/// Closed startup decoder. Domain startup additionally compares aggregate
/// totals to actual durable ownership; a valid codec alone is not that proof.
pub fn validate_row(view: &ReadView, key: &RowKey, bytes: &[u8]) -> Result<(), StoreError> {
    if *key == guard_key() {
        codec::Guard::decode(bytes)?;
        return Ok(());
    }
    if key.family != Family::Maintenance || !key.key.starts_with(QUOTA_PREFIX) {
        return Err(StoreError::UnsupportedFormat);
    }
    let record = TenantRecord::decode(bytes)?;
    if *key != quota_key(&record.quota.tenant)? {
        return Err(StoreError::Corrupt);
    }
    let captured = codec::capture(view, &record.quota.tenant)?.ok_or(StoreError::Corrupt)?;
    if captured.bytes != bytes {
        return Err(StoreError::Corrupt);
    }
    Ok(())
}

#[cfg(test)]
mod tests;
