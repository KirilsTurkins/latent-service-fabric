//! Bounded reverse linkage from one state owner to its exact cell row.
use super::{key, PayloadOwner, PayloadOwnerKind, PayloadReference, MAX_REFERENCE_BYTES};
use crate::embedded::{Family, ReadView, RowKey, StoreError};

pub(super) const PREFIX: &[u8] = b"immutable-payload-state-link-v1\0";
const MAGIC: &[u8] = b"LPS\0\x01";
pub const MAX_STATE_LINK_BYTES: usize = 8192;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct StatePayloadLink {
    pub reference: PayloadReference,
    pub cell_key: RowKey,
}
impl StatePayloadLink {
    pub fn key_for(owner: &PayloadOwner) -> Result<RowKey, StoreError> {
        if owner.kind != PayloadOwnerKind::State {
            return Err(StoreError::Invalid);
        }
        let owner_key = owner.row_key()?;
        Ok(key(PREFIX, &owner_key.key[super::OWNER_PREFIX.len()..]))
    }
    pub fn row_key(&self) -> Result<RowKey, StoreError> {
        if self.cell_key.family != Family::State
            || self.cell_key.key.is_empty()
            || self.cell_key.key.len() > 4096
        {
            return Err(StoreError::Invalid);
        }
        self.reference.validate()?;
        Self::key_for(&self.reference.owner)
    }
    pub fn encode(&self) -> Result<Vec<u8>, StoreError> {
        self.row_key()?;
        let reference = self.reference.encode()?;
        let mut bytes = MAGIC.to_vec();
        bytes.extend_from_slice(
            &u16::try_from(self.cell_key.key.len())
                .map_err(|_| StoreError::Capacity)?
                .to_le_bytes(),
        );
        bytes.extend_from_slice(&self.cell_key.key);
        bytes.extend_from_slice(
            &u16::try_from(reference.len())
                .map_err(|_| StoreError::Capacity)?
                .to_le_bytes(),
        );
        bytes.extend_from_slice(&reference);
        if bytes.len() > MAX_STATE_LINK_BYTES {
            return Err(StoreError::Capacity);
        }
        Ok(bytes)
    }
    pub fn decode(bytes: &[u8]) -> Result<Self, StoreError> {
        if bytes.len() > MAX_STATE_LINK_BYTES || !bytes.starts_with(b"LPS\0") {
            return Err(StoreError::Corrupt);
        }
        if !bytes.starts_with(MAGIC) {
            return Err(StoreError::UnsupportedFormat);
        }
        let mut input = &bytes[MAGIC.len()..];
        let cell_key = RowKey {
            family: Family::State,
            key: field(&mut input, 4096)?.to_vec(),
        };
        let reference = PayloadReference::decode(field(&mut input, MAX_REFERENCE_BYTES)?)?;
        if !input.is_empty() {
            return Err(StoreError::Corrupt);
        }
        let link = Self {
            reference,
            cell_key,
        };
        link.row_key().map_err(|_| StoreError::Corrupt)?;
        Ok(link)
    }
}
fn field<'a>(input: &mut &'a [u8], maximum: usize) -> Result<&'a [u8], StoreError> {
    let (length, rest) = input.split_at_checked(2).ok_or(StoreError::Corrupt)?;
    let length = usize::from(u16::from_le_bytes([length[0], length[1]]));
    if length == 0 || length > maximum {
        return Err(StoreError::Corrupt);
    }
    let (value, rest) = rest.split_at_checked(length).ok_or(StoreError::Corrupt)?;
    *input = rest;
    Ok(value)
}
pub(super) fn is_link(key: &RowKey) -> bool {
    key.family == Family::PayloadReference && key.key.starts_with(PREFIX)
}
pub(super) fn validate_link(view: &ReadView, key: &RowKey, bytes: &[u8]) -> Result<(), StoreError> {
    let link = StatePayloadLink::decode(bytes)?;
    if link.row_key()? != *key
        || view.get_bounded(key, MAX_STATE_LINK_BYTES)?.as_deref() != Some(bytes)
    {
        return Err(StoreError::Corrupt);
    }
    crate::session::verify_state_payload_reference(view, &link.cell_key, &link.reference)
}
/// Returns false for a row owned by another catalogue format.
pub fn validate_state_linked_row(
    view: &ReadView,
    key: &RowKey,
    bytes: &[u8],
) -> Result<bool, StoreError> {
    if is_link(key) {
        validate_link(view, key, bytes)?;
        return Ok(true);
    }
    let Some(reference) = super::owner_reference(key, bytes)? else {
        return Ok(false);
    };
    if reference.owner.kind != PayloadOwnerKind::State {
        return Ok(false);
    }
    let link_key = StatePayloadLink::key_for(&reference.owner)?;
    let encoded = view
        .get_bounded(&link_key, MAX_STATE_LINK_BYTES)?
        .ok_or(StoreError::Corrupt)?;
    let link = StatePayloadLink::decode(&encoded)?;
    if link.reference != reference {
        return Err(StoreError::Corrupt);
    }
    validate_link(view, &link_key, &encoded)?;
    Ok(true)
}
