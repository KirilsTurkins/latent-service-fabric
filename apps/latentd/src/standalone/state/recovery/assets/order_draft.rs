//! Exact same-format recovery for the maintained order-draft package.
use latent_core::{transaction_contract::Value, PlatformError};
use latent_state::{
    embedded::{ReadView, StoreError},
    session::{inspect_cell, state_payload_cell_key, ObservedCell},
};
use sha2::{Digest, Sha256};

pub(in crate::standalone::state::recovery) const DEFINITION: &[u8] = include_bytes!(concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../examples/stateful-reference/state-schema.json"
));
const MEDIA: &str = "application/vnd.lsf.order-draft-v1";
const CELL_BYTES: usize = 4096;

pub(in crate::standalone::state::recovery) fn draft_id(namespace: &str) -> Option<&str> {
    let id = namespace.strip_prefix("order-drafts-")?;
    let alphanumeric = |byte: u8| byte.is_ascii_lowercase() || byte.is_ascii_digit();
    (id.len() <= 32
        && id.bytes().next().is_some_and(alphanumeric)
        && id.bytes().all(|byte| alphanumeric(byte) || byte == b'-'))
    .then_some(id)
}

fn decode(value: &Value) -> Option<(u64, u32)> {
    if value.media_type != MEDIA || !value.metadata.is_empty() || value.bytes.len() != 12 {
        return None;
    }
    let revision = u64::from_le_bytes(value.bytes[..8].try_into().ok()?);
    let units = u32::from_le_bytes(value.bytes[8..].try_into().ok()?);
    (revision != 0 && units <= 10_000).then_some((revision, units))
}

pub(in crate::standalone::state::recovery) fn proof() -> Result<[u8; 32], PlatformError> {
    let mut digest = Sha256::new();
    digest.update(b"latent.order-draft-recovery.v1\0");
    digest.update(DEFINITION);
    for (revision, units) in [(1_u64, 0_u32), (2, 1), (u64::MAX, 10_000)] {
        let mut value = Value {
            bytes: revision.to_le_bytes().to_vec(),
            media_type: MEDIA.into(),
            metadata: Vec::new(),
        };
        value.bytes.extend_from_slice(&units.to_le_bytes());
        if decode(&value) != Some((revision, units)) {
            return Err(super::super::denied());
        }
        digest.update(value.bytes);
    }
    Ok(digest.finalize().into())
}

pub(in crate::standalone::state::recovery) fn validate_cell(
    view: &ReadView,
    observed: &ObservedCell,
) -> Result<(), StoreError> {
    let id = draft_id(&observed.scope.namespace.0).ok_or(StoreError::UnsupportedFormat)?;
    if observed
        .scope
        .entity
        .as_deref()
        .is_some_and(|entity| entity != id)
    {
        return Err(StoreError::UnsupportedFormat);
    }
    let primary = format!("drafts/{id}/draft");
    let summary = format!("drafts/{id}/summary");
    let partner = if observed.key == primary.as_bytes() {
        summary
    } else if observed.key == summary.as_bytes() {
        primary
    } else {
        return Err(StoreError::UnsupportedFormat);
    };
    let key = state_payload_cell_key(&observed.scope, partner.as_bytes())?;
    let paired = view
        .get_bounded(&key, CELL_BYTES)?
        .map(|bytes| inspect_cell(view, &key, &bytes))
        .transpose()?;
    match (&observed.value, paired.and_then(|cell| cell.value)) {
        (None, None) => Ok(()),
        (Some(value), Some(other)) if decode(value).is_some() && value == &other => Ok(()),
        _ => Err(StoreError::UnsupportedFormat),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn installed_order_draft_codec_checks_exact_namespace_and_full_width_values() {
        for unknown in [
            "",
            "order-drafts-",
            "order-drafts--alice",
            "order-drafts-Alice",
            "order-drafts-a/b",
        ] {
            assert_eq!(draft_id(unknown), None);
        }
        assert_eq!(draft_id("order-drafts-alice-1"), Some("alice-1"));
        assert_ne!(proof().unwrap(), [0; 32]);
        let mut value = Value {
            bytes: u64::MAX.to_le_bytes().to_vec(),
            media_type: MEDIA.into(),
            metadata: Vec::new(),
        };
        value.bytes.extend_from_slice(&10_000_u32.to_le_bytes());
        assert_eq!(decode(&value), Some((u64::MAX, 10_000)));
        value.bytes[8..].copy_from_slice(&10_001_u32.to_le_bytes());
        assert_eq!(decode(&value), None);
        value.bytes[8..].fill(0);
        value.bytes[..8].fill(0);
        assert_eq!(decode(&value), None);
    }
}
