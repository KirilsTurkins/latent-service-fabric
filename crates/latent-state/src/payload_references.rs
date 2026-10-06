//! A digest describes content; these records describe independent durable owners.
//! They grant no provider or tenant authority. The complete envelope must retain
//! verified physical payload ownership before appending this atomic plan.

use crate::embedded::{
    AtomicBatch, ExpectedRow, Family, ReadView, RowKey, RowMutation, StoreError,
};
use sha2::{Digest, Sha256};

mod codec;
mod physical;
pub use physical::physical_owner_count;
#[cfg(test)]
mod tests;

pub const MAX_REFERENCE_BYTES: usize = 1024;
pub const MAX_REFERENCE_UPDATES: usize = 32;
const OWNER_PREFIX: &[u8] = b"immutable-payload-owner-v1\0";
const OBJECT_PREFIX: &[u8] = b"immutable-payload-object-v1\0";
const PHYSICAL_PREFIX: &[u8] = b"immutable-payload-physical-v1\0";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PayloadOwnerKind {
    State,
    Result,
    Effect,
    Snapshot,
}

/// Data-only identity of a qualified local immutable object. Remote object
/// retention is intentionally absent; an S3 version string is not a local pin.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LocalPayloadIdentity {
    pub tenant: String,
    pub provider: String,
    pub provider_epoch: u64,
    pub provider_configuration: [u8; 32],
    pub blob_namespace: String,
    pub digest: [u8; 32],
    pub size: u64,
    pub media_type: String,
}

/// The host derives owner identity from the actual state version, command
/// attempt, effect or snapshot. Neither counts nor reference authority come
/// from guest metadata. Each kind keeps its own row when another kind expires.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PayloadOwner {
    pub tenant: String,
    pub namespace: String,
    pub incarnation: u64,
    pub kind: PayloadOwnerKind,
    pub identity: [u8; 32],
    pub generation: u64,
    pub format: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PayloadReference {
    pub owner: PayloadOwner,
    pub payload: LocalPayloadIdentity,
}

impl PayloadReference {
    pub fn validate(&self) -> Result<(), StoreError> {
        for text in [
            &self.owner.tenant,
            &self.owner.namespace,
            &self.owner.format,
            &self.payload.tenant,
            &self.payload.provider,
            &self.payload.blob_namespace,
            &self.payload.media_type,
        ] {
            checked_text(text)?;
        }
        if self.owner.tenant != self.payload.tenant
            || self.owner.incarnation == 0
            || self.owner.generation == 0
            || self.payload.provider_epoch == 0
            || self.payload.size > 1024 * 1024 * 1024
        {
            return Err(StoreError::Invalid);
        }
        Ok(())
    }
    pub fn encode(&self) -> Result<Vec<u8>, StoreError> {
        self.validate()?;
        codec::encode(self)
    }
    pub fn decode(bytes: &[u8]) -> Result<Self, StoreError> {
        codec::decode(bytes)
    }
    pub fn owner_key(&self) -> Result<RowKey, StoreError> {
        self.validate()?;
        let mut hash = Sha256::new();
        hash.update(b"LSF immutable payload owner v1\0");
        for text in [&self.owner.tenant, &self.owner.namespace] {
            hash.update((text.len() as u64).to_le_bytes());
            hash.update(text.as_bytes());
        }
        hash.update(self.owner.incarnation.to_le_bytes());
        hash.update([codec::kind(self.owner.kind)]);
        hash.update(self.owner.identity);
        hash.update(self.owner.generation.to_le_bytes());
        Ok(key(OWNER_PREFIX, &hash.finalize()))
    }
    pub fn object_key(&self) -> Result<RowKey, StoreError> {
        self.validate()?;
        let mut result = object_prefix(&self.payload)?;
        result.extend_from_slice(&self.owner_key()?.key[OWNER_PREFIX.len()..]);
        Ok(RowKey {
            family: Family::PayloadReference,
            key: result,
        })
    }
    pub fn physical_key(&self) -> Result<RowKey, StoreError> {
        self.validate()?;
        let mut result = physical_prefix(&self.payload)?;
        result.extend_from_slice(&self.owner_key()?.key[OWNER_PREFIX.len()..]);
        Ok(RowKey {
            family: Family::PayloadReference,
            key: result,
        })
    }
}

/// Both primary ownership and the object index change in the SAME state-engine
/// transaction as the business envelope. A prepared plan never performs I/O or
/// publishes a processed marker, and cannot be used as a provider grant.
pub struct PreparedPayloadReferences {
    batch: AtomicBatch,
    live_payload_bytes: i128,
    encoded_bytes: usize,
}
impl PreparedPayloadReferences {
    pub fn prepare(
        view: &ReadView,
        updates: &[(Option<PayloadReference>, Option<PayloadReference>)],
    ) -> Result<Self, StoreError> {
        if updates.is_empty() || updates.len() > MAX_REFERENCE_UPDATES {
            return Err(StoreError::Capacity);
        }
        let mut batch = AtomicBatch::default();
        let mut live_payload_bytes = 0_i128;
        let mut encoded_bytes = 0_usize;
        for (before, after) in updates {
            if before.is_none() && after.is_none() {
                return Err(StoreError::Invalid);
            }
            if let (Some(old), Some(new)) = (before, after) {
                if old.owner != new.owner {
                    return Err(StoreError::Conflict);
                }
            }
            let reference = after
                .as_ref()
                .or(before.as_ref())
                .ok_or(StoreError::Invalid)?;
            let owner_key = reference.owner_key()?;
            let expected = before.as_ref().map(PayloadReference::encode).transpose()?;
            if view.get_bounded(&owner_key, MAX_REFERENCE_BYTES)? != expected {
                return Err(StoreError::Conflict);
            }
            let new = after.as_ref().map(PayloadReference::encode).transpose()?;
            append(&mut batch, owner_key, expected.clone(), new.clone())?;
            if let Some(old) = before {
                let object_key = old.object_key()?;
                if view.get_bounded(&object_key, MAX_REFERENCE_BYTES)? != expected {
                    return Err(StoreError::Corrupt);
                }
                if after.as_ref().is_none_or(|new| new.payload != old.payload) {
                    append(&mut batch, object_key, expected.clone(), None)?;
                }
                let physical_key = old.physical_key()?;
                if view.get_bounded(&physical_key, MAX_REFERENCE_BYTES)? != expected {
                    return Err(StoreError::Corrupt);
                }
                if after
                    .as_ref()
                    .map(PayloadReference::physical_key)
                    .transpose()?
                    .as_ref()
                    != Some(&physical_key)
                {
                    append(&mut batch, physical_key, expected.clone(), None)?;
                }
                live_payload_bytes = live_payload_bytes
                    .checked_sub(i128::from(old.payload.size))
                    .ok_or(StoreError::Capacity)?;
            }
            if let Some(new_reference) = after {
                let object_key = new_reference.object_key()?;
                let old_index = if before
                    .as_ref()
                    .is_some_and(|old| old.payload == new_reference.payload)
                {
                    expected.clone()
                } else {
                    None
                };
                if view.get_bounded(&object_key, MAX_REFERENCE_BYTES)? != old_index {
                    return Err(StoreError::Conflict);
                }
                append(&mut batch, object_key, old_index, new.clone())?;
                let physical_key = new_reference.physical_key()?;
                let old_physical = if before
                    .as_ref()
                    .map(PayloadReference::physical_key)
                    .transpose()?
                    .as_ref()
                    == Some(&physical_key)
                {
                    expected.clone()
                } else {
                    None
                };
                if view.get_bounded(&physical_key, MAX_REFERENCE_BYTES)? != old_physical {
                    return Err(StoreError::Conflict);
                }
                append(&mut batch, physical_key, old_physical, new.clone())?;
                live_payload_bytes = live_payload_bytes
                    .checked_add(i128::from(new_reference.payload.size))
                    .ok_or(StoreError::Capacity)?;
            }
            for bytes in [&expected, &new].into_iter().flatten() {
                encoded_bytes = encoded_bytes
                    .checked_add(bytes.len())
                    .ok_or(StoreError::Capacity)?;
            }
        }
        physical::append_heads(view, updates, &mut batch)?;
        // Retained expectations and mutations include every owner/index byte.
        // This finite charge includes replacement keys as well as encoded data.
        encoded_bytes = batch
            .expectations
            .iter()
            .try_fold(encoded_bytes, |total, row| {
                total
                    .checked_add(row.key.key.len())
                    .and_then(|n| n.checked_add(row.value.as_ref().map_or(0, Vec::len)))
                    .ok_or(StoreError::Capacity)
            })?;
        encoded_bytes = batch
            .mutations
            .iter()
            .try_fold(encoded_bytes, |total, row| {
                total
                    .checked_add(row.key.key.len())
                    .and_then(|n| n.checked_add(row.value.as_ref().map_or(0, Vec::len)))
                    .ok_or(StoreError::Capacity)
            })?;
        Ok(Self {
            batch,
            live_payload_bytes,
            encoded_bytes,
        })
    }
    /// Full referenced bytes are part of the existing durable payload quota;
    /// charging only the small pointer would let large values evade admission.
    #[must_use]
    pub fn live_payload_bytes_delta(&self) -> i128 {
        self.live_payload_bytes
    }
    #[must_use]
    pub fn encoded_metadata_bytes(&self) -> usize {
        self.encoded_bytes
    }
    /// Move this plan into the complete envelope, retaining its provider pin
    /// separately until the actual physical commit and any uncertainty retire.
    pub fn append_to(self, batch: &mut AtomicBatch) -> Result<(), StoreError> {
        for row in &self.batch.expectations {
            if batch
                .expectations
                .iter()
                .any(|existing| existing.key == row.key)
                || batch
                    .mutations
                    .iter()
                    .any(|existing| existing.key == row.key)
            {
                return Err(StoreError::Conflict);
            }
        }
        batch.expectations.extend(self.batch.expectations);
        batch.mutations.extend(self.batch.mutations);
        Ok(())
    }
}

/// Bounded reference/format closure for GC, migration and snapshot owners.
/// Every object-index row is checked against its exact primary from this same
/// view. A missing primary is corruption, never permission to delete bytes.
pub fn required_page(
    view: &ReadView,
    payload: &LocalPayloadIdentity,
    after: Option<&[u8]>,
    maximum_rows: usize,
    maximum_bytes: usize,
) -> Result<PayloadReferencePage, StoreError> {
    if maximum_rows == 0
        || maximum_rows > MAX_REFERENCE_UPDATES
        || maximum_bytes == 0
        || maximum_bytes > MAX_REFERENCE_UPDATES * MAX_REFERENCE_BYTES
    {
        return Err(StoreError::Capacity);
    }
    let page = view.scan_after(
        Family::PayloadReference,
        &object_prefix(payload)?,
        after,
        maximum_rows,
        maximum_bytes,
    )?;
    let mut references = Vec::with_capacity(page.rows.len());
    for (key, bytes) in page.rows {
        let reference = PayloadReference::decode(&bytes)?;
        if reference.payload != *payload
            || reference.object_key()? != key
            || view
                .get_bounded(&reference.owner_key()?, MAX_REFERENCE_BYTES)?
                .as_deref()
                != Some(bytes.as_slice())
            || view
                .get_bounded(&reference.physical_key()?, MAX_REFERENCE_BYTES)?
                .as_deref()
                != Some(bytes.as_slice())
        {
            return Err(StoreError::Corrupt);
        }
        references.push(reference);
    }
    Ok(PayloadReferencePage {
        references,
        resume: page.resume,
    })
}
pub struct PayloadReferencePage {
    pub references: Vec<PayloadReference>,
    pub resume: Option<Vec<u8>>,
}
/// Physical retention spans installed provider aliases and epochs naming the
/// same protected local object. This inventory grants no provider read access.
pub fn required_physical_page(
    view: &ReadView,
    payload: &LocalPayloadIdentity,
    after: Option<&[u8]>,
    maximum_rows: usize,
    maximum_bytes: usize,
) -> Result<PayloadReferencePage, StoreError> {
    if maximum_rows == 0
        || maximum_rows > MAX_REFERENCE_UPDATES
        || maximum_bytes == 0
        || maximum_bytes > MAX_REFERENCE_UPDATES * MAX_REFERENCE_BYTES
    {
        return Err(StoreError::Capacity);
    }
    let prefix = physical_prefix(payload)?;
    let page = view.scan_after(
        Family::PayloadReference,
        &prefix,
        after,
        maximum_rows,
        maximum_bytes,
    )?;
    let mut references = Vec::with_capacity(page.rows.len());
    for (key, bytes) in page.rows {
        let reference = PayloadReference::decode(&bytes)?;
        if physical_prefix(&reference.payload)? != prefix || reference.physical_key()? != key {
            return Err(StoreError::Corrupt);
        }
        validate_row(view, &key, &bytes)?;
        references.push(reference);
    }
    Ok(PayloadReferencePage {
        references,
        resume: page.resume,
    })
}
pub fn validate_row(view: &ReadView, key: &RowKey, bytes: &[u8]) -> Result<(), StoreError> {
    if physical::is_head(key) {
        return physical::validate_head(key, bytes);
    }
    let reference = PayloadReference::decode(bytes)?;
    if key.family != Family::PayloadReference {
        return Err(StoreError::Invalid);
    }
    let keys = [
        reference.owner_key()?,
        reference.object_key()?,
        reference.physical_key()?,
    ];
    if !keys.contains(key) {
        return Err(StoreError::Corrupt);
    }
    for other in keys {
        if view.get_bounded(&other, MAX_REFERENCE_BYTES)?.as_deref() != Some(bytes) {
            return Err(StoreError::Corrupt);
        }
    }
    Ok(())
}
fn checked_text(value: &str) -> Result<(), StoreError> {
    if value.is_empty() || value.len() > 128 || value.chars().any(char::is_control) {
        return Err(StoreError::Invalid);
    }
    Ok(())
}
fn key(prefix: &[u8], identity: &[u8]) -> RowKey {
    let mut bytes = Vec::with_capacity(prefix.len() + identity.len());
    bytes.extend_from_slice(prefix);
    bytes.extend_from_slice(identity);
    RowKey {
        family: Family::PayloadReference,
        key: bytes,
    }
}
fn object_prefix(payload: &LocalPayloadIdentity) -> Result<Vec<u8>, StoreError> {
    let mut hash = Sha256::new();
    hash.update(b"LSF immutable local payload v1\0");
    for text in [
        &payload.tenant,
        &payload.provider,
        &payload.blob_namespace,
        &payload.media_type,
    ] {
        checked_text(text)?;
        hash.update((text.len() as u64).to_le_bytes());
        hash.update(text.as_bytes());
    }
    if payload.provider_epoch == 0 || payload.size > 1024 * 1024 * 1024 {
        return Err(StoreError::Invalid);
    }
    hash.update(payload.provider_epoch.to_le_bytes());
    hash.update(payload.provider_configuration);
    hash.update(payload.digest);
    hash.update(payload.size.to_le_bytes());
    Ok(key(OBJECT_PREFIX, &hash.finalize()).key)
}
fn physical_prefix(payload: &LocalPayloadIdentity) -> Result<Vec<u8>, StoreError> {
    let mut hash = Sha256::new();
    hash.update(b"LSF protected local payload physical retention v1\0");
    for text in [
        &payload.tenant,
        &payload.blob_namespace,
        &payload.media_type,
    ] {
        checked_text(text)?;
        hash.update((text.len() as u64).to_le_bytes());
        hash.update(text.as_bytes());
    }
    if payload.size > 1024 * 1024 * 1024 {
        return Err(StoreError::Invalid);
    }
    hash.update(payload.provider_configuration);
    hash.update(payload.digest);
    hash.update(payload.size.to_le_bytes());
    Ok(key(PHYSICAL_PREFIX, &hash.finalize()).key)
}
fn append(
    batch: &mut AtomicBatch,
    key: RowKey,
    old: Option<Vec<u8>>,
    new: Option<Vec<u8>>,
) -> Result<(), StoreError> {
    if batch.expectations.iter().any(|row| row.key == key) {
        return Err(StoreError::Conflict);
    }
    batch.expectations.push(ExpectedRow {
        key: key.clone(),
        value: old,
    });
    batch.mutations.push(RowMutation { key, value: new });
    Ok(())
}
