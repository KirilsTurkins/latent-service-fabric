use latent_state::embedded::{Family, RowKey, StoreError};
use serde::{Deserialize, Serialize};

use crate::authority::{AuthorityError, EffectTime};
use crate::dispatch::{AttemptIdentity, AttemptReceipt};

use super::{effect_identity, storage_error};

pub(super) const OWNER_KEY: &[u8] = b"dispatch-owner-v1\0";
pub(super) const HISTORY_PREFIX: &[u8] = b"dispatch-history-v1\0";
const OWNER_FORMAT: &[u8; 5] = b"LDO\0\x01";
const HISTORY_FORMAT: &[u8; 5] = b"LDH\0\x01";
pub(super) const MAXIMUM_HISTORY_BYTES: usize = 4096;

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
        let identity = effect_identity::parse(&self.effect).map_err(storage_error)?;
        if self.sequence == 0 || self.sequence > 128 {
            return Err(StoreError::Invalid);
        }
        let mut key = Vec::with_capacity(HISTORY_PREFIX.len() + 40);
        key.extend_from_slice(HISTORY_PREFIX);
        key.extend_from_slice(&identity);
        key.extend_from_slice(&self.sequence.to_be_bytes());
        Ok(RowKey {
            family: Family::Attempt,
            key,
        })
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
        HistoryRecord::decode(key, bytes)?;
        Ok(())
    } else {
        Err(StoreError::UnsupportedFormat)
    }
}
