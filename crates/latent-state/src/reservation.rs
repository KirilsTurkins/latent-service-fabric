//! Checked logical capacity reservations in the same physical engine. Pending
//! command disposition space is counted alongside stored bytes at every writer
//! fence. This is neither a disk-free guarantee nor a second journal. Only the
//! trusted host coordinator installs/releases a reservation with its command CAS.

use crate::embedded::{Family, RowKey, StoreError};

pub const KEY_PREFIX: &[u8] = b"logical-reservation-v1\0";
const MAGIC: &[u8] = b"LSR\x01";
const MAXIMUM_BYTES: u64 = 128 * 1024 * 1024;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct LogicalReservation {
    pub generation: u64,
    pub bytes: u64,
}

impl LogicalReservation {
    pub fn encode(self) -> Result<Vec<u8>, StoreError> {
        if self.generation == 0 || self.bytes == 0 || self.bytes > MAXIMUM_BYTES {
            return Err(StoreError::Invalid);
        }
        let mut out = Vec::with_capacity(20);
        out.extend_from_slice(MAGIC);
        out.extend_from_slice(&self.generation.to_le_bytes());
        out.extend_from_slice(&self.bytes.to_le_bytes());
        Ok(out)
    }

    pub fn decode(bytes: &[u8]) -> Result<Self, StoreError> {
        if bytes.len() != 20 {
            return Err(StoreError::Corrupt);
        }
        if &bytes[..4] != MAGIC {
            return Err(StoreError::UnsupportedFormat);
        }
        let generation =
            u64::from_le_bytes(bytes[4..12].try_into().map_err(|_| StoreError::Corrupt)?);
        let amount = u64::from_le_bytes(bytes[12..20].try_into().map_err(|_| StoreError::Corrupt)?);
        if generation == 0 || amount == 0 || amount > MAXIMUM_BYTES {
            return Err(StoreError::Corrupt);
        }
        Ok(Self {
            generation,
            bytes: amount,
        })
    }
}

pub fn reservation_key(owner: &[u8]) -> Result<RowKey, StoreError> {
    if owner.is_empty() || owner.len() > 128 {
        return Err(StoreError::Invalid);
    }
    let mut key = KEY_PREFIX.to_vec();
    key.extend_from_slice(owner);
    Ok(RowKey {
        family: Family::Maintenance,
        key,
    })
}

/// Physical key includes the closed family byte. No allocations are needed to
/// charge a reservation while scanning the bounded writer table.
pub(crate) fn reserved_bytes(physical_key: &[u8], value: &[u8]) -> Result<usize, StoreError> {
    if physical_key.first() != Some(&(Family::Maintenance as u8))
        || !physical_key[1..].starts_with(KEY_PREFIX)
    {
        return Ok(0);
    }
    let owner_length = physical_key.len() - 1 - KEY_PREFIX.len();
    if owner_length == 0 || owner_length > 128 {
        return Err(StoreError::Corrupt);
    }
    usize::try_from(LogicalReservation::decode(value)?.bytes).map_err(|_| StoreError::Capacity)
}
