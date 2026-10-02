//! One bounded shared namespace ledger codec for original command and effect
//! producers. This description provides no publication or quota-update grant.

use crate::{
    embedded::{Family, RowKey, StoreError},
    namespace::{namespace_record_key, NamespaceRecord},
};
use latent_core::{StateNamespaceId, TenantId};

const LEGACY_MAGIC: &[u8] = b"LCU\0\x01";
const CLOCK_MAGIC: &[u8] = b"LMP\0\x02";
const CLOCK_BYTES: usize = 103;

/// Exact original encoded bytes, including the independently versioned clock
/// slot. Effect metadata changes only its own byte counter; no clock renewal,
/// command identity change or counter reconstruction occurs here.
pub struct NamespaceLedger {
    bytes: Vec<u8>,
    values: [u64; 7],
    accounted: bool,
}

impl NamespaceLedger {
    pub fn decode(bytes: &[u8]) -> Result<Self, StoreError> {
        let accounted = bytes.starts_with(super::QUOTA_MAGIC);
        if !accounted && !bytes.starts_with(LEGACY_MAGIC) {
            return Err(StoreError::UnsupportedFormat);
        }
        if bytes.len() != if accounted { super::QUOTA_BYTES } else { 61 } {
            return Err(StoreError::Corrupt);
        }
        let mut values = [0; 7];
        for (slot, encoded) in values.iter_mut().zip(bytes[5..61].chunks_exact(8)) {
            *slot = u64::from_le_bytes(encoded.try_into().map_err(|_| StoreError::Corrupt)?);
        }
        if values[0] > 1_000_000
            || values[2] > 1_000_000
            || [values[1], values[3], values[4], values[5], values[6]]
                .into_iter()
                .any(|value| value > 1024 * 1024 * 1024)
            || values[5] > values[1]
            || values[6] > values[5]
        {
            return Err(StoreError::Corrupt);
        }
        if accounted {
            let length = usize::from(u16::from_le_bytes([bytes[61], bytes[62]]));
            if !matches!(length, 0 | CLOCK_BYTES)
                || bytes[63 + length..].iter().any(|byte| *byte != 0)
            {
                return Err(StoreError::Corrupt);
            }
            if length != 0 {
                validate_clock(&bytes[63..63 + length])?;
            }
        }
        Ok(Self {
            bytes: bytes.to_vec(),
            values,
            accounted,
        })
    }

    #[must_use]
    pub const fn is_accounted(&self) -> bool {
        self.accounted
    }

    #[must_use]
    pub const fn durable_format(&self) -> (&'static str, u32) {
        (
            "latent.command-usage.v1",
            if self.accounted { 2 } else { 1 },
        )
    }

    pub fn check(&self, namespace: &NamespaceRecord) -> Result<(), StoreError> {
        let quota = namespace.quota;
        let limits = [
            quota.result_rows,
            quota.result_bytes,
            quota.effect_rows,
            quota.effect_bytes,
            quota.payload_bytes,
            quota.result_bytes,
            quota.recovery_bytes,
        ];
        if self
            .values
            .iter()
            .zip(limits)
            .any(|(value, limit)| *value > limit)
        {
            return Err(StoreError::Capacity);
        }
        Ok(())
    }

    pub fn adjust_effect_bytes(&mut self, removed: u64, added: u64) -> Result<(), StoreError> {
        if !self.accounted {
            return Err(StoreError::UnsupportedFormat);
        }
        let bytes = self.values[3]
            .checked_sub(removed)
            .ok_or(StoreError::Corrupt)?
            .checked_add(added)
            .filter(|bytes| *bytes <= 1024 * 1024 * 1024)
            .ok_or(StoreError::Capacity)?;
        self.values[3] = bytes;
        self.bytes[29..37].copy_from_slice(&bytes.to_le_bytes());
        Ok(())
    }

    #[must_use]
    pub fn encode(&self) -> Vec<u8> {
        self.bytes.clone()
    }
}

pub fn namespace_ledger_key(
    tenant: &TenantId,
    namespace: &StateNamespaceId,
    incarnation: u64,
) -> Result<RowKey, StoreError> {
    if incarnation == 0 {
        return Err(StoreError::Invalid);
    }
    let mut key = super::QUOTA_PREFIX.to_vec();
    key.extend_from_slice(
        &namespace_record_key(tenant, namespace).map_err(|_| StoreError::Invalid)?,
    );
    key.extend_from_slice(&incarnation.to_le_bytes());
    Ok(RowKey {
        family: Family::Maintenance,
        key,
    })
}

fn validate_clock(bytes: &[u8]) -> Result<(), StoreError> {
    if !bytes.starts_with(CLOCK_MAGIC)
        || bytes[5..37].iter().all(|byte| *byte == 0)
        || bytes[101..103] != [0, 0]
    {
        return Err(StoreError::Corrupt);
    }
    let mut values = [0u64; 8];
    for (slot, encoded) in values.iter_mut().zip(bytes[37..101].chunks_exact(8)) {
        *slot = u64::from_le_bytes(encoded.try_into().map_err(|_| StoreError::Corrupt)?);
    }
    if values[0] == 0
        || values[6] > values[5]
        || !matches!((values[1].checked_sub(values[3]), values[2].checked_sub(values[4])),
            (Some(wall), Some(monotonic)) if wall.abs_diff(monotonic) <= 1000)
    {
        return Err(StoreError::Corrupt);
    }
    Ok(())
}

#[cfg(test)]
mod tests;
