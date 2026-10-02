use latent_state::embedded::{Family, RowKey, StoreError};
use latent_state::reservation::{
    reservation_key, LogicalReservation, KEY_PREFIX as RESERVATION_PREFIX,
};
use serde::{Deserialize, Serialize};

use crate::authority::{AuthorityError, EffectTime};
use crate::dispatch::{AttemptIdentity, AttemptReceipt};

use super::effect_identity;

pub(super) const OWNER_KEY: &[u8] = b"dispatch-owner-v1\0";
pub(super) const HISTORY_PREFIX: &[u8] = b"dispatch-history-v1\0";
const OWNER_FORMAT: &[u8; 5] = b"LDO\0\x01";
const HISTORY_FORMAT: &[u8; 5] = b"LDH\0\x01";
const PENDING_HISTORY_FORMAT: &[u8; 5] = b"LHP\0\x01";
const ATTEMPT_RESERVATION_PREFIX: &[u8] = b"dispatch-attempt-v1\0";
pub(super) const DISPOSITION_RESERVED_BYTES: u64 = 70 * 1024;
pub(super) const MAXIMUM_HISTORY_BYTES: usize = 4096;

pub(super) fn attempt_reservation_key(effect: &str) -> Result<RowKey, StoreError> {
    let mut owner = ATTEMPT_RESERVATION_PREFIX.to_vec();
    owner.extend_from_slice(&effect_identity::parse(effect).map_err(|_| StoreError::Invalid)?);
    reservation_key(&owner)
}

pub(super) fn history_key(effect: &str, sequence: u64) -> Result<RowKey, StoreError> {
    let identity = effect_identity::parse(effect).map_err(|_| StoreError::Invalid)?;
    if sequence == 0 || sequence > 128 {
        return Err(StoreError::Invalid);
    }
    let mut key = Vec::with_capacity(HISTORY_PREFIX.len() + 40);
    key.extend_from_slice(HISTORY_PREFIX);
    key.extend_from_slice(&identity);
    key.extend_from_slice(&sequence.to_be_bytes());
    Ok(RowKey {
        family: Family::Attempt,
        key,
    })
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(super) struct HistoryReservation {
    pub owner_epoch: u64,
    pub claim_generation: u64,
    pub attempt: u32,
}

impl HistoryReservation {
    pub fn encode(self) -> Result<Vec<u8>, StoreError> {
        if self.owner_epoch == 0 || self.claim_generation == 0 || !(1..=128).contains(&self.attempt)
        {
            return Err(StoreError::Invalid);
        }
        let mut bytes = Vec::with_capacity(25);
        bytes.extend_from_slice(PENDING_HISTORY_FORMAT);
        bytes.extend_from_slice(&self.owner_epoch.to_be_bytes());
        bytes.extend_from_slice(&self.claim_generation.to_be_bytes());
        bytes.extend_from_slice(&self.attempt.to_be_bytes());
        Ok(bytes)
    }

    pub fn decode(bytes: &[u8]) -> Result<Self, StoreError> {
        if !bytes.starts_with(PENDING_HISTORY_FORMAT) {
            return Err(StoreError::UnsupportedFormat);
        }
        if bytes.len() != 25 {
            return Err(StoreError::Corrupt);
        }
        let reservation = Self {
            owner_epoch: u64::from_be_bytes(
                bytes[5..13].try_into().map_err(|_| StoreError::Corrupt)?,
            ),
            claim_generation: u64::from_be_bytes(
                bytes[13..21].try_into().map_err(|_| StoreError::Corrupt)?,
            ),
            attempt: u32::from_be_bytes(bytes[21..25].try_into().map_err(|_| StoreError::Corrupt)?),
        };
        reservation.encode().map_err(|_| StoreError::Corrupt)?;
        Ok(reservation)
    }

    pub fn present(bytes: &[u8]) -> bool {
        bytes.starts_with(PENDING_HISTORY_FORMAT)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DispatchStoreError {
    Storage(StoreError),
    Authority(AuthorityError),
    StaleEpoch,
}

impl From<StoreError> for DispatchStoreError {
    fn from(error: StoreError) -> Self {
        Self::Storage(error)
    }
}

impl From<AuthorityError> for DispatchStoreError {
    fn from(error: AuthorityError) -> Self {
        Self::Authority(error)
    }
}

#[derive(Debug, Clone, Copy)]
pub(super) struct OwnerRecord {
    pub epoch: u64,
    pub clock_floor: u64,
}

impl OwnerRecord {
    pub fn key() -> RowKey {
        RowKey {
            family: Family::Maintenance,
            key: OWNER_KEY.to_vec(),
        }
    }

    pub fn encode(self) -> Result<Vec<u8>, StoreError> {
        if self.epoch == 0 {
            return Err(StoreError::Invalid);
        }
        let mut bytes = Vec::with_capacity(21);
        bytes.extend_from_slice(OWNER_FORMAT);
        bytes.extend_from_slice(&self.epoch.to_be_bytes());
        bytes.extend_from_slice(&self.clock_floor.to_be_bytes());
        Ok(bytes)
    }

    pub fn decode(bytes: &[u8]) -> Result<Self, StoreError> {
        if !bytes.starts_with(OWNER_FORMAT) {
            return Err(StoreError::UnsupportedFormat);
        }
        if bytes.len() != 21 {
            return Err(StoreError::Corrupt);
        }
        let epoch = u64::from_be_bytes(bytes[5..13].try_into().map_err(|_| StoreError::Corrupt)?);
        if epoch == 0 {
            return Err(StoreError::Corrupt);
        }
        Ok(Self {
            epoch,
            clock_floor: u64::from_be_bytes(
                bytes[13..21].try_into().map_err(|_| StoreError::Corrupt)?,
            ),
        })
    }

    pub fn observe(&mut self, time: EffectTime) -> Result<(), AuthorityError> {
        if !time.continuity_proven || time.unix_millis < self.clock_floor {
            return Err(AuthorityError::ClockDiscontinuity);
        }
        self.clock_floor = time.unix_millis;
        Ok(())
    }
}

/// One bounded receipt, never an inline growing history vector. Provider
/// acknowledgement denotes the adapter boundary, not consumer commitment.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct HistoryRecord {
    pub sequence: u64,
    pub effect: String,
    pub attempt: Option<AttemptIdentity>,
    pub receipt: AttemptReceipt,
}

impl HistoryRecord {
    pub fn key(&self) -> Result<RowKey, StoreError> {
        history_key(&self.effect, self.sequence)
    }

    pub fn encode(&self) -> Result<Vec<u8>, StoreError> {
        self.validate()?;
        let body = serde_json::to_vec(self).map_err(|_| StoreError::Invalid)?;
        if body.len() > MAXIMUM_HISTORY_BYTES - 5 {
            return Err(StoreError::Capacity);
        }
        let mut bytes = Vec::with_capacity(body.len() + 5);
        bytes.extend_from_slice(HISTORY_FORMAT);
        bytes.extend_from_slice(&body);
        Ok(bytes)
    }

    pub fn decode(key: &RowKey, bytes: &[u8]) -> Result<Self, StoreError> {
        if key.family != Family::Attempt
            || !key.key.starts_with(HISTORY_PREFIX)
            || !bytes.starts_with(HISTORY_FORMAT)
        {
            return Err(StoreError::UnsupportedFormat);
        }
        if key.key.len() != HISTORY_PREFIX.len() + 40 {
            return Err(StoreError::Corrupt);
        }
        if bytes.len() > MAXIMUM_HISTORY_BYTES {
            return Err(StoreError::Capacity);
        }
        let record: Self = serde_json::from_slice(&bytes[5..]).map_err(|_| StoreError::Corrupt)?;
        record.validate().map_err(|_| StoreError::Corrupt)?;
        if record.key()? != *key {
            return Err(StoreError::Corrupt);
        }
        Ok(record)
    }

    fn validate(&self) -> Result<(), StoreError> {
        self.key()?;
        if !self.receipt.valid()
            || self.attempt.as_ref().is_some_and(|attempt| {
                attempt.effect() != self.effect
                    || attempt.attempt() == 0
                    || attempt.attempt() > 128
                    || attempt.owner_epoch() == 0
                    || attempt.claim_generation() == 0
            })
        {
            return Err(StoreError::Invalid);
        }
        Ok(())
    }
}

pub(super) fn validate_row(key: &RowKey, bytes: &[u8]) -> Result<(), StoreError> {
    if key.family == Family::Maintenance && key.key == OWNER_KEY {
        OwnerRecord::decode(bytes)?;
        Ok(())
    } else if key.family == Family::Attempt && key.key.starts_with(HISTORY_PREFIX) {
        if HistoryReservation::present(bytes) {
            if key.key.len() != HISTORY_PREFIX.len() + 40 {
                return Err(StoreError::Corrupt);
            }
            let sequence = u64::from_be_bytes(
                key.key[HISTORY_PREFIX.len() + 32..]
                    .try_into()
                    .map_err(|_| StoreError::Corrupt)?,
            );
            if sequence == 0 || sequence > 128 {
                return Err(StoreError::Corrupt);
            }
            HistoryReservation::decode(bytes)?;
        } else {
            HistoryRecord::decode(key, bytes)?;
        }
        Ok(())
    } else if key.family == Family::Maintenance && key.key.starts_with(RESERVATION_PREFIX) {
        let owner = &key.key[RESERVATION_PREFIX.len()..];
        if !owner.starts_with(ATTEMPT_RESERVATION_PREFIX) {
            return Err(StoreError::UnsupportedFormat);
        }
        if owner.len() != ATTEMPT_RESERVATION_PREFIX.len() + 32 {
            return Err(StoreError::Corrupt);
        }
        let reservation = LogicalReservation::decode(bytes)?;
        if reservation.bytes != DISPOSITION_RESERVED_BYTES {
            return Err(StoreError::Corrupt);
        }
        Ok(())
    } else {
        Err(StoreError::UnsupportedFormat)
    }
}
