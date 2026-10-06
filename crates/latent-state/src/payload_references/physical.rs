//! Count/generation changes share the original envelope transaction. A missing
//! index with a positive head cannot become an affirmative reclamation grant.
use super::{
    append, checked_text, key, physical_prefix, AtomicBatch, Family, LocalPayloadIdentity,
    PayloadReference, ReadView, RowKey, StoreError, MAX_REFERENCE_BYTES,
};
use std::collections::BTreeMap;
const PREFIX: &[u8] = b"immutable-payload-retention-head-v1\0";
const FORMAT: &[u8] = b"LPH\0\x01";
struct Head {
    payload: LocalPayloadIdentity,
    generation: u64,
    owners: u64,
}
fn head_key(payload: &LocalPayloadIdentity) -> Result<RowKey, StoreError> {
    let prefix = physical_prefix(payload)?;
    Ok(key(PREFIX, &prefix[super::PHYSICAL_PREFIX.len()..]))
}
pub(super) fn is_head(key: &RowKey) -> bool {
    key.family == Family::PayloadReference && key.key.starts_with(PREFIX)
}
pub(super) fn validate_head(key: &RowKey, bytes: &[u8]) -> Result<(), StoreError> {
    let head = decode(bytes)?;
    if head_key(&head.payload)? != *key {
        return Err(StoreError::Corrupt);
    }
    Ok(())
}
pub fn physical_owner_count(
    view: &ReadView,
    payload: &LocalPayloadIdentity,
) -> Result<Option<u64>, StoreError> {
    let key = head_key(payload)?;
    let bytes = view.get_bounded(&key, MAX_REFERENCE_BYTES)?;
    bytes
        .as_deref()
        .map(|bytes| {
            validate_head(&key, bytes)?;
            Ok(decode(bytes)?.owners)
        })
        .transpose()
}
pub(super) fn append_heads(
    view: &ReadView,
    updates: &[(Option<PayloadReference>, Option<PayloadReference>)],
    batch: &mut AtomicBatch,
) -> Result<(), StoreError> {
    let mut changes: BTreeMap<Vec<u8>, (LocalPayloadIdentity, i64, bool)> = BTreeMap::new();
    for (before, after) in updates {
        for (reference, delta, existed) in [(before, -1_i64, true), (after, 1_i64, false)] {
            if let Some(reference) = reference {
                let entry = changes.entry(head_key(&reference.payload)?.key).or_insert((
                    reference.payload.clone(),
                    0,
                    false,
                ));
                entry.1 = entry.1.checked_add(delta).ok_or(StoreError::Capacity)?;
                entry.2 |= existed;
            }
        }
    }
    for (bytes, (payload, delta, existed)) in changes {
        let key = RowKey {
            family: Family::PayloadReference,
            key: bytes,
        };
        let old = view.get_bounded(&key, MAX_REFERENCE_BYTES)?;
        let previous = if let Some(bytes) = &old {
            validate_head(&key, bytes)?;
            decode(bytes)?
        } else {
            if existed
                || !view
                    .scan_after(
                        Family::PayloadReference,
                        &physical_prefix(&payload)?,
                        None,
                        1,
                        4096,
                    )?
                    .rows
                    .is_empty()
            {
                return Err(StoreError::Corrupt);
            }
            Head {
                payload: payload.clone(),
                generation: 0,
                owners: 0,
            }
        };
        let owners = previous
            .owners
            .checked_add_signed(delta)
            .filter(|n| *n <= 65_536)
            .ok_or(StoreError::Corrupt)?;
        let generation = previous
            .generation
            .checked_add(1)
            .ok_or(StoreError::Capacity)?;
        append(
            batch,
            key,
            old,
            Some(encode(&Head {
                payload,
                generation,
                owners,
            })?),
        )?;
    }
    Ok(())
}
fn encode(head: &Head) -> Result<Vec<u8>, StoreError> {
    physical_prefix(&head.payload)?;
    checked_text(&head.payload.provider)?;
    if head.generation == 0 || head.owners > 65_536 || head.payload.provider_epoch == 0 {
        return Err(StoreError::Invalid);
    }
    let mut bytes = Vec::with_capacity(MAX_REFERENCE_BYTES);
    bytes.extend_from_slice(FORMAT);
    for number in [
        head.generation,
        head.owners,
        head.payload.provider_epoch,
        head.payload.size,
    ] {
        bytes.extend_from_slice(&number.to_le_bytes());
    }
    bytes.extend_from_slice(&head.payload.provider_configuration);
    bytes.extend_from_slice(&head.payload.digest);
    for text in [
        &head.payload.tenant,
        &head.payload.provider,
        &head.payload.blob_namespace,
        &head.payload.media_type,
    ] {
        checked_text(text)?;
        bytes.extend_from_slice(
            &u16::try_from(text.len())
                .map_err(|_| StoreError::Capacity)?
                .to_le_bytes(),
        );
        bytes.extend_from_slice(text.as_bytes());
    }
    if bytes.len() > MAX_REFERENCE_BYTES {
        return Err(StoreError::Capacity);
    }
    Ok(bytes)
}
fn decode(bytes: &[u8]) -> Result<Head, StoreError> {
    if bytes.len() > MAX_REFERENCE_BYTES || !bytes.starts_with(b"LPH\0") {
        return Err(StoreError::Corrupt);
    }
    if !bytes.starts_with(FORMAT) {
        return Err(StoreError::UnsupportedFormat);
    }
    let mut input = &bytes[FORMAT.len()..];
    let generation = number(&mut input)?;
    let owners = number(&mut input)?;
    let provider_epoch = number(&mut input)?;
    let size = number(&mut input)?;
    let provider_configuration = take(&mut input, 32)?
        .try_into()
        .map_err(|_| StoreError::Corrupt)?;
    let digest = take(&mut input, 32)?
        .try_into()
        .map_err(|_| StoreError::Corrupt)?;
    let payload = LocalPayloadIdentity {
        tenant: text(&mut input)?,
        provider: text(&mut input)?,
        blob_namespace: text(&mut input)?,
        media_type: text(&mut input)?,
        provider_epoch,
        provider_configuration,
        digest,
        size,
    };
    if !input.is_empty() || generation == 0 || owners > 65_536 || provider_epoch == 0 {
        return Err(StoreError::Corrupt);
    }
    physical_prefix(&payload).map_err(|_| StoreError::Corrupt)?;
    Ok(Head {
        payload,
        generation,
        owners,
    })
}
fn take<'a>(input: &mut &'a [u8], length: usize) -> Result<&'a [u8], StoreError> {
    let (value, rest) = input.split_at_checked(length).ok_or(StoreError::Corrupt)?;
    *input = rest;
    Ok(value)
}
fn number(input: &mut &[u8]) -> Result<u64, StoreError> {
    Ok(u64::from_le_bytes(
        take(input, 8)?
            .try_into()
            .map_err(|_| StoreError::Corrupt)?,
    ))
}
fn text(input: &mut &[u8]) -> Result<String, StoreError> {
    let length = usize::from(u16::from_le_bytes(
        take(input, 2)?
            .try_into()
            .map_err(|_| StoreError::Corrupt)?,
    ));
    if length == 0 || length > 128 {
        return Err(StoreError::Corrupt);
    }
    let value = std::str::from_utf8(take(input, length)?).map_err(|_| StoreError::Corrupt)?;
    checked_text(value).map_err(|_| StoreError::Corrupt)?;
    Ok(value.into())
}
