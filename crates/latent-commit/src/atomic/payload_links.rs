//! Reciprocal command/attempt/format closure; descriptors confer no read grant.
use super::{
    incarnation,
    record::{attempt_row_key, result_row_key},
    AtomicError, CommandRecord, DurableResult, Identity, Outcome,
};
use latent_core::transaction_contract::Value;
use latent_state::{
    embedded::{Family, ReadView, RowKey},
    payload_references::{
        self as catalogue, PayloadLinks, PayloadOwner, PayloadOwnerKind, PayloadReference,
        LINKS_PREFIX, MAX_LINK_BYTES, MAX_REFERENCE_BYTES,
    },
};
use sha2::{Digest, Sha256};

pub(super) fn anchor(record: &CommandRecord) -> Result<PayloadOwner, AtomicError> {
    Ok(PayloadOwner {
        tenant: record.key.tenant.clone(),
        namespace: record.key.namespace.clone(),
        incarnation: incarnation(&record.key)?,
        kind: PayloadOwnerKind::Result,
        identity: record.id.0,
        generation: record.attempt,
        format: record.source.result_format.clone(),
    })
}
pub(super) fn read(
    view: &ReadView,
    record: &CommandRecord,
) -> Result<Option<PayloadLinks>, AtomicError> {
    let expected = anchor(record)?;
    let key = PayloadLinks::key_for(&expected)?;
    let bytes = view.get_bounded(&key, MAX_LINK_BYTES)?;
    let links = bytes.as_deref().map(PayloadLinks::decode).transpose()?;
    if links.as_ref().is_some_and(|links| links.anchor != expected) {
        return Err(AtomicError::Corrupt);
    }
    Ok(links)
}
pub(super) fn verify_value(reference: &PayloadReference, value: &Value) -> Result<(), AtomicError> {
    value.validate().map_err(|_| AtomicError::Corrupt)?;
    let digest: [u8; 32] = Sha256::digest(&value.bytes).into();
    if reference.payload.size != value.bytes.len() as u64
        || reference.payload.digest != digest
        || reference.payload.media_type != value.media_type
    {
        return Err(AtomicError::Corrupt);
    }
    Ok(())
}
fn required(view: &ReadView, key: &RowKey, maximum: usize) -> Result<Vec<u8>, AtomicError> {
    view.get_bounded(key, maximum)?.ok_or(AtomicError::Corrupt)
}
pub(super) fn verify(
    view: &ReadView,
    record: &CommandRecord,
    links: &PayloadLinks,
) -> Result<(), AtomicError> {
    if links.anchor != anchor(record)?
        || !matches!(record.outcome, Outcome::Committed | Outcome::Rejected)
    {
        return Err(AtomicError::Corrupt);
    }
    links.verify_rows(view)?;
    for reference in &links.references {
        match reference.owner.kind {
            PayloadOwnerKind::Result => {
                let result = DurableResult::decode(&required(
                    view,
                    &result_row_key(record.id, record.attempt),
                    super::codec::RESULT_BYTES,
                )?)?;
                result.verify(record)?;
                verify_value(reference, result.value().ok_or(AtomicError::Corrupt)?)?;
            }
            PayloadOwnerKind::Effect => {
                let effect = Identity(reference.owner.identity);
                if !record.effects.contains(&effect) {
                    return Err(AtomicError::Corrupt);
                }
                let stored = latent_effects::dispatch::EffectRecord::decode(&required(
                    view,
                    &latent_effects::dispatch_store::effect_row_key(&effect.hex())?,
                    super::codec::METADATA_BYTES,
                )?)?;
                let authority = stored.authority()?;
                if authority.link().command != record.id.hex()
                    || authority.link().attempt != record.attempt
                    || authority.link().commit != record.disposition_id().hex()
                    || authority.link().effect != effect.hex()
                    || authority.link().caller_scope != record.key.recovery_scope
                    || authority.scope().tenant != record.key.tenant
                    || authority.scope().namespace != record.key.namespace
                    || authority.scope().incarnation != incarnation(&record.key)?
                    || authority.scope().publication != record.source.publication
                    || authority.profile().payload_format != reference.owner.format
                {
                    return Err(AtomicError::Corrupt);
                }
                let payload = latent_effects::payload::PayloadRecord::decode(&required(
                    view,
                    &latent_effects::dispatch_store::effect_payload_key(&effect.hex())?,
                    super::codec::RESULT_BYTES,
                )?)?;
                payload.verify(&authority)?;
                verify_value(reference, payload.value())?;
            }
            _ => return Err(AtomicError::Corrupt),
        }
    }
    Ok(())
}
pub(super) fn validate_linked(
    view: &ReadView,
    key: &RowKey,
    bytes: &[u8],
) -> Result<(), AtomicError> {
    catalogue::validate_row(view, key, bytes)?;
    if key.family == Family::PayloadReference && key.key.starts_with(LINKS_PREFIX) {
        let links = PayloadLinks::decode(bytes)?;
        let record = CommandRecord::decode(&required(
            view,
            &attempt_row_key(Identity(links.anchor.identity), links.anchor.generation),
            super::codec::METADATA_BYTES,
        )?)?;
        return verify(view, &record, &links);
    }
    let Some(reference) = catalogue::owner_reference(key, bytes)? else {
        return Ok(());
    };
    let command = match reference.owner.kind {
        PayloadOwnerKind::Result => Identity(reference.owner.identity),
        PayloadOwnerKind::Effect => {
            let effect = Identity(reference.owner.identity);
            let stored = latent_effects::dispatch::EffectRecord::decode(&required(
                view,
                &latent_effects::dispatch_store::effect_row_key(&effect.hex())?,
                super::codec::METADATA_BYTES,
            )?)?;
            super::validation::parse_identity(&stored.authority()?.link().command)?
        }
        _ => return Err(AtomicError::UnsupportedFormat),
    };
    let record = CommandRecord::decode(&required(
        view,
        &attempt_row_key(command, reference.owner.generation),
        super::codec::METADATA_BYTES,
    )?)?;
    let links = read(view, &record)?.ok_or(AtomicError::Corrupt)?;
    if !links.references.contains(&reference)
        || view
            .get_bounded(&reference.owner_key()?, MAX_REFERENCE_BYTES)?
            .as_deref()
            != Some(bytes)
    {
        return Err(AtomicError::Corrupt);
    }
    verify(view, &record, &links)
}
