//! Closed retained payload format, independent of application state schemas.
//! All lengths/counts are checked before allocating decoded application bytes.

use latent_core::transaction_contract::{
    ContractError, Value, IDENTITY_BYTES, MEDIA_TYPE_BYTES, METADATA_BYTES, METADATA_PAIRS,
    VALUE_BYTES,
};
use sha2::{Digest, Sha256};

use crate::authority::{AuthorityError, DurableEffectAuthority};
use crate::effect_identity;

mod decode;
#[cfg(test)]
pub(crate) mod tests;

const RECORD_FORMAT: &[u8; 5] = b"LEP\0\x01";
const VALUE_FORMAT: &[u8; 5] = b"LEV\0\x01";
const DIGEST_DOMAIN: &[u8] = b"lsf-effect-payload-v1\0";
pub const MAXIMUM_ENCODED_VALUE_BYTES: usize =
    VALUE_BYTES + MEDIA_TYPE_BYTES + METADATA_BYTES + METADATA_PAIRS * 4 + 13;
pub const MAXIMUM_PAYLOAD_RECORD_BYTES: usize = MAXIMUM_ENCODED_VALUE_BYTES + 41;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PayloadRecord {
    effect: String,
    value: Value,
}

impl PayloadRecord {
    pub fn new(
        authority: &DurableEffectAuthority,
        mut value: Value,
    ) -> Result<Self, AuthorityError> {
        validate(&value)?;
        value
            .metadata
            .sort_by(|left, right| left.0.as_bytes().cmp(right.0.as_bytes()));
        let record = Self {
            effect: authority.link().effect.clone(),
            value,
        };
        record.verify(authority)?;
        Ok(record)
    }

    /// The immutable authority binds exact media/metadata/payload bytes and
    /// stable effect identity; an independently decoded row grants no dispatch.
    pub fn verify(&self, authority: &DurableEffectAuthority) -> Result<(), AuthorityError> {
        effect_identity::parse(&self.effect)?;
        if self.effect != authority.link().effect
            || authority.payload_bytes()
                != u64::try_from(self.value.bytes.len()).map_err(|_| AuthorityError::Capacity)?
            || payload_digest(&self.value)? != authority.payload_digest()
        {
            return Err(AuthorityError::Invalid);
        }
        Ok(())
    }

    #[must_use]
    pub fn value(&self) -> &Value {
        &self.value
    }

    #[must_use]
    pub fn effect(&self) -> &str {
        &self.effect
    }

    pub fn encode(&self) -> Result<Vec<u8>, AuthorityError> {
        let effect = effect_identity::parse(&self.effect)?;
        let value_bytes = encoded_length(&self.value)?;
        let mut bytes = Vec::with_capacity(value_bytes + 41);
        bytes.extend_from_slice(RECORD_FORMAT);
        bytes.extend_from_slice(&effect);
        bytes.extend_from_slice(
            &u32::try_from(value_bytes)
                .map_err(|_| AuthorityError::Capacity)?
                .to_le_bytes(),
        );
        visit_value(&self.value, |part| bytes.extend_from_slice(part))?;
        Ok(bytes)
    }

    pub fn decode(bytes: &[u8]) -> Result<Self, AuthorityError> {
        decode::record(bytes)
    }
}

pub fn payload_digest(value: &Value) -> Result<String, AuthorityError> {
    let mut digest = Sha256::new();
    digest.update(DIGEST_DOMAIN);
    visit_value(value, |part| digest.update(part))?;
    let bytes: [u8; 32] = digest.finalize().into();
    Ok(effect_identity::render(&bytes))
}

fn validate(value: &Value) -> Result<(), AuthorityError> {
    value.validate().map_err(|error| match error {
        ContractError::ByteLimit | ContractError::CountLimit => AuthorityError::Capacity,
        _ => AuthorityError::Invalid,
    })
}

fn encoded_length(value: &Value) -> Result<usize, AuthorityError> {
    validate(value)?;
    let metadata = value
        .metadata
        .iter()
        .try_fold(0_usize, |total, (key, value)| {
            total
                .checked_add(key.len())
                .and_then(|total| total.checked_add(value.len()))
                .and_then(|total| total.checked_add(4))
                .ok_or(AuthorityError::Capacity)
        })?;
    let length = value
        .bytes
        .len()
        .checked_add(value.media_type.len())
        .and_then(|length| length.checked_add(metadata))
        .and_then(|length| length.checked_add(13))
        .ok_or(AuthorityError::Capacity)?;
    if length > MAXIMUM_ENCODED_VALUE_BYTES {
        return Err(AuthorityError::Capacity);
    }
    Ok(length)
}

fn visit_value(value: &Value, mut visit: impl FnMut(&[u8])) -> Result<(), AuthorityError> {
    encoded_length(value)?;
    visit(VALUE_FORMAT);
    visit(
        &u32::try_from(value.bytes.len())
            .map_err(|_| AuthorityError::Capacity)?
            .to_le_bytes(),
    );
    visit(&value.bytes);
    visit(
        &u16::try_from(value.media_type.len())
            .map_err(|_| AuthorityError::Capacity)?
            .to_le_bytes(),
    );
    visit(value.media_type.as_bytes());
    visit(
        &u16::try_from(value.metadata.len())
            .map_err(|_| AuthorityError::Capacity)?
            .to_le_bytes(),
    );
    let mut metadata: Vec<_> = value.metadata.iter().collect();
    metadata.sort_by(|left, right| left.0.as_bytes().cmp(right.0.as_bytes()));
    for (key, value) in metadata {
        visit(
            &u16::try_from(key.len())
                .map_err(|_| AuthorityError::Capacity)?
                .to_le_bytes(),
        );
        visit(key.as_bytes());
        visit(
            &u16::try_from(value.len())
                .map_err(|_| AuthorityError::Capacity)?
                .to_le_bytes(),
        );
        visit(value.as_bytes());
    }
    Ok(())
}
