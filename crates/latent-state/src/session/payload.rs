//! Descriptive linkage to an actual state cell, not a read or write grant.
use super::{codec, inspect_cell, inspect_cell_in_namespace, ObservedCell, StateScope};
use crate::{
    embedded::{Family, ReadView, RowKey, StoreError},
    namespace::NamespaceRecord,
    payload_references::{
        self, PayloadOwner, PayloadOwnerKind, PayloadReference, StatePayloadLink,
    },
};
use latent_core::transaction_contract::Value;
use sha2::{Digest, Sha256};

/// Derive a reference owner from the exact current cell and its namespace.
/// The caller must retain its original policy and engine fence when publishing.
pub fn describe_state_payload_owner(
    view: &ReadView,
    key: &RowKey,
) -> Result<(PayloadOwner, Value), StoreError> {
    if key.family != Family::State {
        return Err(StoreError::UnsupportedFormat);
    }
    let bytes = view
        .get_bounded(key, codec::CELL_BYTES)?
        .ok_or(StoreError::Corrupt)?;
    owner_from_cell(key, inspect_cell(view, key, &bytes)?)
}

/// Describe an exact staged cell against its already validated namespace row.
pub fn describe_staged_state_payload_owner(
    key: &RowKey,
    bytes: &[u8],
    namespace: &NamespaceRecord,
) -> Result<(PayloadOwner, Value), StoreError> {
    owner_from_cell(key, inspect_cell_in_namespace(key, bytes, namespace)?)
}

/// Descriptive row location only; it never grants access to the state cell.
pub fn state_payload_cell_key(scope: &StateScope, key: &[u8]) -> Result<RowKey, StoreError> {
    super::state_key(scope, key).map_err(|_| StoreError::Invalid)
}

fn owner_from_cell(key: &RowKey, cell: ObservedCell) -> Result<(PayloadOwner, Value), StoreError> {
    let value = cell.value.ok_or(StoreError::Corrupt)?;
    let mut digest = Sha256::new();
    digest.update(b"LSF state payload owner v1\0");
    digest.update((key.key.len() as u64).to_le_bytes());
    digest.update(&key.key);
    let owner = PayloadOwner {
        tenant: cell.scope.tenant.0,
        namespace: cell.scope.namespace.0,
        incarnation: cell.scope.incarnation,
        kind: PayloadOwnerKind::State,
        identity: digest.finalize().into(),
        generation: cell.generation,
        format: cell.scope.state_schema,
    };
    owner.row_key()?;
    Ok((owner, value))
}

/// Check an installed reference against its exact current cell and reciprocal
/// rows. The supplied cell key is descriptive, not authority to read it.
pub fn verify_state_payload_reference(
    view: &ReadView,
    cell_key: &RowKey,
    reference: &PayloadReference,
) -> Result<(), StoreError> {
    let (owner, value) = describe_state_payload_owner(view, cell_key)?;
    let bytes = reference.encode().map_err(|_| StoreError::Corrupt)?;
    payload_references::validate_row(view, &reference.owner_key()?, &bytes)?;
    let digest: [u8; 32] = Sha256::digest(&value.bytes).into();
    if reference.owner != owner
        || reference.payload.size != value.bytes.len() as u64
        || reference.payload.digest != digest
        || reference.payload.media_type != value.media_type
    {
        return Err(StoreError::Corrupt);
    }
    Ok(())
}

/// A writer without reference replacement support must refuse to overwrite a
/// cell that still owns a durable payload. Missing reciprocal rows are corrupt.
pub fn require_no_state_payload_reference(
    view: &ReadView,
    cell_key: &RowKey,
) -> Result<(), StoreError> {
    if retained_state_payload_reference(view, cell_key)?.is_some() {
        Err(StoreError::UnsupportedFormat)
    } else {
        Ok(())
    }
}

/// Capture the exact existing owner and reverse link from one coherent view.
pub fn retained_state_payload_reference(
    view: &ReadView,
    cell_key: &RowKey,
) -> Result<Option<StatePayloadLink>, StoreError> {
    let Some(bytes) = view.get_bounded(cell_key, codec::CELL_BYTES)? else {
        return Ok(None);
    };
    if inspect_cell(view, cell_key, &bytes)?.value.is_none() {
        return Ok(None);
    }
    let (owner, _) = describe_state_payload_owner(view, cell_key)?;
    let primary = owner.row_key()?;
    let link = payload_references::StatePayloadLink::key_for(&owner)?;
    let reference_bytes = view.get_bounded(&primary, payload_references::MAX_REFERENCE_BYTES)?;
    let link_bytes = view.get_bounded(&link, payload_references::MAX_STATE_LINK_BYTES)?;
    match (reference_bytes, link_bytes) {
        (None, None) => Ok(None),
        (Some(reference), Some(link)) => {
            if !payload_references::validate_state_linked_row(view, &primary, &reference)? {
                return Err(StoreError::Corrupt);
            }
            Ok(Some(StatePayloadLink::decode(&link)?))
        }
        _ => Err(StoreError::Corrupt),
    }
}
