//! A physically referenced effect must keep its original local bytes pinned
//! until the provider operation and its durable receipt finish.
use latent_state::embedded::{ExpectedRow, ReadView, RowKey, StoreError};
use latent_state::payload_references::{
    owner_reference, PayloadOwner, PayloadOwnerKind, MAX_REFERENCE_BYTES,
};
use sha2::{Digest, Sha256};

use crate::authority::{AuthorityError, DurableEffectAuthority};
use crate::dispatch_store::DispatchStoreError;
use crate::payload::PayloadRecord;

/// The installed immutable provider supplies the physical reader. The dispatcher
/// continues to use the exact inline envelope that the original command sealed.
pub type DispatchPayloadVerifier = dyn Fn(
        &ReadView,
        &RowKey,
        &[u8],
        &dyn Fn() -> Result<(), AuthorityError>,
    ) -> Result<DispatchPayloadPin, DispatchStoreError>
    + Send
    + Sync;
pub type DispatchPayloadPin = Box<dyn Send>;

pub(super) fn pin(
    view: &ReadView,
    authority: &DurableEffectAuthority,
    payload: &PayloadRecord,
    verifier: Option<&DispatchPayloadVerifier>,
    checkpoint: &dyn Fn() -> Result<(), AuthorityError>,
) -> Result<(Option<DispatchPayloadPin>, ExpectedRow), DispatchStoreError> {
    let scope = authority.scope();
    let link = authority.link();
    let owner = PayloadOwner {
        tenant: scope.tenant.clone(),
        namespace: scope.namespace.clone(),
        incarnation: scope.incarnation,
        kind: PayloadOwnerKind::Effect,
        identity: crate::effect_identity::parse(&link.effect).map_err(|_| StoreError::Corrupt)?,
        generation: link.attempt,
        format: authority.profile().payload_format.clone(),
    };
    let key = owner.row_key()?;
    let value = view.get_bounded(&key, MAX_REFERENCE_BYTES)?;
    let pin = if let Some(bytes) = value.as_deref() {
        let reference = owner_reference(&key, bytes)?.ok_or(StoreError::Corrupt)?;
        let inline = payload.value();
        if reference.owner != owner
            || reference.payload.size != inline.bytes.len() as u64
            || reference.payload.media_type != inline.media_type
            || reference.payload.digest != <[u8; 32]>::from(Sha256::digest(&inline.bytes))
        {
            return Err(StoreError::Corrupt.into());
        }
        let verify = verifier.ok_or(StoreError::UnsupportedFormat)?;
        checkpoint()?;
        Some(verify(view, &key, bytes, checkpoint)?)
    } else {
        None
    };
    Ok((pin, ExpectedRow { key, value }))
}
