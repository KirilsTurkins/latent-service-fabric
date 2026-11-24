//! Descriptive linkage to an actual state cell, not a read or write grant.
use super::{
    codec, inspect_cell, inspect_cell_in_namespace, ObservedCell, StateError, StateScope,
    StateSession,
};
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
        .get_typed_bounded(key, codec::CELL_BYTES)?
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
    let owner = state_owner(key, &cell.scope, cell.generation)?;
    Ok((owner, value))
}

fn state_owner(
    key: &RowKey,
    scope: &StateScope,
    generation: u64,
) -> Result<PayloadOwner, StoreError> {
    let mut digest = Sha256::new();
    digest.update(b"LSF state payload owner v1\0");
    digest.update((key.key.len() as u64).to_le_bytes());
    digest.update(&key.key);
    let owner = PayloadOwner {
        tenant: scope.tenant.0.clone(),
        namespace: scope.namespace.0.clone(),
        incarnation: scope.incarnation,
        kind: PayloadOwnerKind::State,
        identity: digest.finalize().into(),
        generation,
        format: scope.state_schema.clone(),
    };
    owner.row_key()?;
    Ok(owner)
}

impl StateSession {
    /// Check the committed cell underlying a value already read by this session.
    /// A staged replacement uses its own inline bytes and has no committed link.
    pub fn verify_read_payload(
        &mut self,
        view: &ReadView,
        key: &[u8],
        verify: impl FnOnce(&ReadView, &RowKey, &[u8]) -> Result<(), StoreError>,
    ) -> Result<(), StateError> {
        if self.closed {
            return Err(StateError::Closed);
        }
        if view.identity() != self.view {
            return Err(StateError::Invalid);
        }
        if self.staged.contains_key(key) {
            return Ok(());
        }
        let cell = self
            .observations
            .get(key)
            .and_then(|observation| observation.cell.as_ref())
            .filter(|cell| cell.value.is_some())
            .ok_or(StateError::Corrupt)?;
        let cell_key = state_payload_cell_key(&self.scope, key)?;
        let owner = state_owner(&cell_key, &self.scope, cell.generation)?;
        if let Some((row, bytes, link)) = read_state_payload_link(view, &owner)? {
            let payload_bytes =
                usize::try_from(link.reference.payload.size).map_err(|_| StateError::Limit)?;
            self.charge_read(
                payload_bytes
                    .checked_add(bytes.len())
                    .ok_or(StateError::Limit)?,
            )?;
            verify(view, &row, &bytes)?;
        }
        Ok(())
    }
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
    let Some(bytes) = view.get_typed_bounded(cell_key, codec::CELL_BYTES)? else {
        return Ok(None);
    };
    let cell = inspect_cell(view, cell_key, &bytes)?;
    if cell.value.is_none() {
        return Ok(None);
    }
    let owner = state_owner(cell_key, &cell.scope, cell.generation)?;
    Ok(read_state_payload_link(view, &owner)?.map(|(_, _, link)| link))
}

fn read_state_payload_link(
    view: &ReadView,
    owner: &PayloadOwner,
) -> Result<Option<(RowKey, Vec<u8>, StatePayloadLink)>, StoreError> {
    let primary = owner.row_key()?;
    let link = StatePayloadLink::key_for(owner)?;
    let reference_bytes = view.get_bounded(&primary, payload_references::MAX_REFERENCE_BYTES)?;
    let link_bytes = view.get_bounded(&link, payload_references::MAX_STATE_LINK_BYTES)?;
    match (reference_bytes, link_bytes) {
        (None, None) => Ok(None),
        (Some(reference), Some(link)) => {
            if !payload_references::validate_state_linked_row(view, &primary, &reference)? {
                return Err(StoreError::Corrupt);
            }
            Ok(Some((primary, reference, StatePayloadLink::decode(&link)?)))
        }
        _ => Err(StoreError::Corrupt),
    }
}
