use latent_state::embedded::{Family, RowKey, StoreError};
use latent_state::reservation::reservation_key;
use serde::{de::DeserializeOwned, Serialize};
use sha2::{Digest, Sha256};

use super::{EffectManagementError, EffectManagementRequest, RESERVATION_OWNER_PREFIX};

pub(super) fn encode<T: Serialize>(
    magic: &[u8],
    value: &T,
    maximum: usize,
) -> Result<Vec<u8>, EffectManagementError> {
    let mut bytes = magic.to_vec();
    bytes.extend(serde_json::to_vec(value).map_err(|_| EffectManagementError::Invalid)?);
    if bytes.len() > maximum {
        return Err(EffectManagementError::Capacity);
    }
    Ok(bytes)
}
pub(super) fn decode<T: DeserializeOwned>(
    magic: &[u8],
    bytes: &[u8],
    maximum: usize,
) -> Result<T, EffectManagementError> {
    if bytes.len() > maximum {
        return Err(EffectManagementError::Capacity);
    }
    if !bytes.starts_with(magic) {
        return Err(StoreError::UnsupportedFormat.into());
    }
    serde_json::from_slice(&bytes[magic.len()..]).map_err(|_| StoreError::Corrupt.into())
}
pub(super) fn digest(domain: &[u8], bytes: &[u8]) -> [u8; 32] {
    let mut hash = Sha256::new();
    hash.update(domain);
    hash.update(bytes);
    hash.finalize().into()
}
pub(super) fn operation(request: &EffectManagementRequest) -> [u8; 32] {
    let input = request.input();
    operation_actor(
        &input.actor_tenant,
        &input.actor_subject,
        &input.operation_id,
    )
}
pub(super) fn operation_actor(tenant: &str, subject: &str, operation: &str) -> [u8; 32] {
    let mut hash = Sha256::new();
    hash.update(b"lsf-effect-management-operation-v1\0");
    for text in [tenant, subject, operation] {
        hash.update((text.len() as u64).to_be_bytes());
        hash.update(text.as_bytes());
    }
    hash.finalize().into()
}
pub(super) fn row(prefix: &[u8], identity: &[u8; 32]) -> RowKey {
    let mut key = prefix.to_vec();
    key.extend_from_slice(identity);
    RowKey {
        family: Family::Maintenance,
        key,
    }
}
pub(super) fn slot(effect: &[u8; 32], sequence: u32) -> RowKey {
    let mut key = row(super::SLOT_PREFIX, effect);
    key.key.extend_from_slice(&sequence.to_be_bytes());
    key
}
pub(super) fn reservation(operation: &[u8; 32]) -> Result<RowKey, StoreError> {
    let mut owner = RESERVATION_OWNER_PREFIX.to_vec();
    owner.extend_from_slice(operation);
    reservation_key(&owner)
}

pub(super) fn storage(error: EffectManagementError) -> StoreError {
    match error {
        EffectManagementError::Store(error) => error,
        EffectManagementError::Capacity
        | EffectManagementError::Authority(crate::authority::AuthorityError::Capacity) => {
            StoreError::Capacity
        }
        EffectManagementError::Authority(crate::authority::AuthorityError::UnsupportedFormat) => {
            StoreError::UnsupportedFormat
        }
        _ => StoreError::Corrupt,
    }
}
