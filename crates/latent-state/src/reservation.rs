//! Checked logical capacity reservations in the same physical engine. Pending
//! command disposition space is counted alongside stored bytes at every writer
//! fence. This is neither a disk-free guarantee nor a second journal. Only the
//! trusted host coordinator installs/releases a reservation with its command CAS.

use crate::embedded::{Family, RowKey, StoreError};

pub const KEY_PREFIX: &[u8] = b"logical-reservation-v1\0";
const MAGIC: &[u8] = b"LSR\x01";
const ACCOUNTED_MAGIC: &[u8] = b"LSR\x02";
pub const QUOTA_PREFIX: &[u8] = b"command-usage-v1\0";
pub const QUOTA_MAGIC: &[u8] = b"LCU\0\x02";
pub const QUOTA_BYTES: usize = 256;
const MAXIMUM_BYTES: u64 = 128 * 1024 * 1024;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct LogicalReservation {
    pub generation: u64,
    pub bytes: u64,
}

impl LogicalReservation {
    pub fn encode_for(self, accounted: bool) -> Result<Vec<u8>, StoreError> {
        if accounted {
            self.encode_accounted()
        } else {
            self.encode()
        }
    }
    /// The same bytes are already charged by the aggregate quota row in this
    /// physical transaction. Keep the command ownership marker without counting
    /// the same reservation twice at the engine high-water fence.
    pub fn encode_accounted(self) -> Result<Vec<u8>, StoreError> {
        let mut bytes = self.encode()?;
        bytes[..4].copy_from_slice(ACCOUNTED_MAGIC);
        Ok(bytes)
    }

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
        if &bytes[..4] != MAGIC && &bytes[..4] != ACCOUNTED_MAGIC {
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
    if physical_key.first() != Some(&(Family::Maintenance as u8)) {
        return Ok(0);
    }
    let key = &physical_key[1..];
    if key.starts_with(QUOTA_PREFIX) && value.starts_with(QUOTA_MAGIC) {
        if value.len() != QUOTA_BYTES {
            return Err(StoreError::Corrupt);
        }
        let amount = u64::from_le_bytes(value[45..53].try_into().map_err(|_| StoreError::Corrupt)?);
        if amount > MAXIMUM_BYTES {
            return Err(StoreError::Capacity);
        }
        return usize::try_from(amount).map_err(|_| StoreError::Capacity);
    }
    if !key.starts_with(KEY_PREFIX) {
        return Ok(0);
    }
    let owner_length = physical_key.len() - 1 - KEY_PREFIX.len();
    if owner_length == 0 || owner_length > 128 {
        return Err(StoreError::Corrupt);
    }
    let reservation = LogicalReservation::decode(value)?;
    if value.starts_with(ACCOUNTED_MAGIC) {
        return Ok(0);
    }
    usize::try_from(reservation.bytes).map_err(|_| StoreError::Capacity)
}

/// Single-pass physical coverage check. An accounted ownership marker is valid
/// only when the same writer's aggregate rows cover every promised byte. Domain
/// startup additionally validates each command's exact namespace and marker.
#[derive(Default)]
pub(crate) struct ReservationCoverage {
    promised: usize,
    covered: usize,
}
impl ReservationCoverage {
    pub(crate) fn observe(
        &mut self,
        physical_key: &[u8],
        value: &[u8],
        reserved: usize,
    ) -> Result<(), StoreError> {
        if physical_key.first() != Some(&(Family::Maintenance as u8)) {
            return Ok(());
        }
        let key = &physical_key[1..];
        if key.starts_with(KEY_PREFIX) && value.starts_with(ACCOUNTED_MAGIC) {
            let bytes = usize::try_from(LogicalReservation::decode(value)?.bytes)
                .map_err(|_| StoreError::Capacity)?;
            self.promised = self
                .promised
                .checked_add(bytes)
                .ok_or(StoreError::Capacity)?;
        } else if key.starts_with(QUOTA_PREFIX) && value.starts_with(QUOTA_MAGIC) {
            self.covered = self
                .covered
                .checked_add(reserved)
                .ok_or(StoreError::Capacity)?;
        }
        Ok(())
    }
    pub(crate) fn verify(&self) -> Result<(), StoreError> {
        if self.promised > self.covered {
            return Err(StoreError::UnsupportedFormat);
        }
        Ok(())
    }
}
