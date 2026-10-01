//! Closed durable dispatcher indexes and atomic envelope ports. No native store
//! handle or provider operation is retained by these finite logical records.

use latent_state::embedded::{Family, RowKey, RowMutation, StoreError};

use crate::authority::{AuthorityError, DurableEffectAuthority};
use crate::dispatch::EffectRecord;
use crate::effect_identity;
use crate::payload::PayloadRecord;

pub const EFFECT_PREFIX: &[u8] = b"effect-v1\0";
pub const PAYLOAD_PREFIX: &[u8] = b"effect-payload-v1\0";
pub const DUE_PREFIX: &[u8] = b"dispatch-due-v1\0";
const DUE_FORMAT: &[u8; 5] = b"LDI\0\x01";

mod catalog;
mod codec;
pub mod control;
pub use catalog::{
    ClaimedEffect, DispatchCatalog, DispatchCounts, DispatchEpoch, DuePage, HistoryPage,
    RetainedEffectRows,
};
pub use codec::{DispatchStoreError, HistoryRecord};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DueRecord {
    pub due_millis: u64,
    pub effect: String,
    pub incarnation: u64,
    pub claim_generation: u64,
}

impl DueRecord {
    pub fn key(&self) -> Result<RowKey, StoreError> {
        if self.incarnation == 0 {
            return Err(StoreError::Invalid);
        }
        let identity = effect_identity::parse(&self.effect).map_err(|_| StoreError::Invalid)?;
        let mut key = Vec::with_capacity(DUE_PREFIX.len() + 40);
        key.extend_from_slice(DUE_PREFIX);
        key.extend_from_slice(&self.due_millis.to_be_bytes());
        key.extend_from_slice(&identity);
        Ok(RowKey {
            family: Family::Maintenance,
            key,
        })
    }

    pub fn encode(&self) -> Result<Vec<u8>, StoreError> {
        self.key()?;
        let mut bytes = Vec::with_capacity(21);
        bytes.extend_from_slice(DUE_FORMAT);
        bytes.extend_from_slice(&self.incarnation.to_be_bytes());
        bytes.extend_from_slice(&self.claim_generation.to_be_bytes());
        Ok(bytes)
    }

    pub fn decode(key: &RowKey, bytes: &[u8]) -> Result<Self, StoreError> {
        if key.family != Family::Maintenance
            || !key.key.starts_with(DUE_PREFIX)
            || !bytes.starts_with(DUE_FORMAT)
        {
            return Err(StoreError::UnsupportedFormat);
        }
        if key.key.len() != DUE_PREFIX.len() + 40 || bytes.len() != 21 {
            return Err(StoreError::Corrupt);
        }
        let due_millis = u64::from_be_bytes(
            key.key[DUE_PREFIX.len()..DUE_PREFIX.len() + 8]
                .try_into()
                .map_err(|_| StoreError::Corrupt)?,
        );
        let identity = key.key[DUE_PREFIX.len() + 8..]
            .try_into()
            .map_err(|_| StoreError::Corrupt)?;
        let incarnation =
            u64::from_be_bytes(bytes[5..13].try_into().map_err(|_| StoreError::Corrupt)?);
        if incarnation == 0 {
            return Err(StoreError::Corrupt);
        }
        Ok(Self {
            due_millis,
            effect: effect_identity::render(&identity),
            incarnation,
            claim_generation: u64::from_be_bytes(
                bytes[13..21].try_into().map_err(|_| StoreError::Corrupt)?,
            ),
        })
    }
}

pub fn effect_row_key(effect: &str) -> Result<RowKey, StoreError> {
    identity_key(Family::Outbox, EFFECT_PREFIX, effect)
}

pub fn effect_payload_key(effect: &str) -> Result<RowKey, StoreError> {
    identity_key(Family::PayloadReference, PAYLOAD_PREFIX, effect)
}

/// Bounded startup row validation. Unknown families/prefixes are delegated to
/// their codec owner; this port never accepts another family's opaque bytes.
pub fn validate_row(key: &RowKey, bytes: &[u8]) -> Result<(), StoreError> {
    match key.family {
        Family::Outbox if key.key.starts_with(EFFECT_PREFIX) => {
            let effect = effect_from_key(key, EFFECT_PREFIX)?;
            let record = EffectRecord::decode(bytes).map_err(storage_error)?;
            if record.authority().map_err(storage_error)?.link().effect != effect {
                return Err(StoreError::Corrupt);
            }
        }
        Family::PayloadReference if key.key.starts_with(PAYLOAD_PREFIX) => {
            let effect = effect_from_key(key, PAYLOAD_PREFIX)?;
            if PayloadRecord::decode(bytes)
                .map_err(storage_error)?
                .effect()
                != effect
            {
                return Err(StoreError::Corrupt);
            }
        }
        Family::Maintenance if key.key.starts_with(DUE_PREFIX) => {
            DueRecord::decode(key, bytes)?;
        }
        Family::Maintenance
            if key.key == control::CONTROL_STATE_KEY
                || key.key.starts_with(control::CONTROL_RECEIPT_PREFIX) =>
        {
            control::ControlCatalog::validate_row(key, bytes)?;
        }
        _ => return codec::validate_row(key, bytes),
    }
    Ok(())
}

pub fn initial_due_mutation(authority: &DurableEffectAuthority) -> Result<RowMutation, StoreError> {
    let record = DueRecord {
        due_millis: authority.committed_at_millis(),
        effect: authority.link().effect.clone(),
        incarnation: authority.scope().incarnation,
        claim_generation: 0,
    };
    Ok(RowMutation {
        key: record.key()?,
        value: Some(record.encode()?),
    })
}

fn identity_key(family: Family, prefix: &[u8], effect: &str) -> Result<RowKey, StoreError> {
    let identity = effect_identity::parse(effect).map_err(|_| StoreError::Invalid)?;
    let mut key = Vec::with_capacity(prefix.len() + 32);
    key.extend_from_slice(prefix);
    key.extend_from_slice(&identity);
    Ok(RowKey { family, key })
}

fn effect_from_key(key: &RowKey, prefix: &[u8]) -> Result<String, StoreError> {
    if key.key.len() != prefix.len() + 32 {
        return Err(StoreError::Corrupt);
    }
    let identity = key.key[prefix.len()..]
        .try_into()
        .map_err(|_| StoreError::Corrupt)?;
    Ok(effect_identity::render(&identity))
}

pub(crate) fn storage_error(error: AuthorityError) -> StoreError {
    match error {
        AuthorityError::Capacity => StoreError::Capacity,
        AuthorityError::UnsupportedFormat => StoreError::UnsupportedFormat,
        AuthorityError::Unavailable => StoreError::Unavailable,
        _ => StoreError::Corrupt,
    }
}

#[cfg(test)]
mod tests;
