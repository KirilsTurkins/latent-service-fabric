use super::{StateError, StateScope};
use latent_core::transaction_contract::{self as contract, Value};
use sha2::{Digest, Sha256};

const MAGIC: &[u8] = b"LSV\x01";
pub(super) const CELL_BYTES: usize = contract::VALUE_BYTES + contract::METADATA_BYTES + 1024;

#[derive(Debug, Clone, PartialEq, Eq)]
pub(super) struct Cell {
    pub generation: u64,
    pub value: Option<Value>,
}

impl Cell {
    pub fn encode(&self) -> Result<Vec<u8>, StateError> {
        if self.generation == 0 {
            return Err(StateError::Invalid);
        }
        let mut bytes = Vec::with_capacity(64);
        bytes.extend_from_slice(MAGIC);
        bytes.extend_from_slice(&self.generation.to_le_bytes());
        bytes.push(u8::from(self.value.is_some()));
        if let Some(value) = &self.value {
            value.validate().map_err(|_| StateError::Limit)?;
            bytes.extend_from_slice(
                &u32::try_from(value.bytes.len())
                    .map_err(|_| StateError::Limit)?
                    .to_le_bytes(),
            );
            bytes.extend_from_slice(&value.bytes);
            text(&mut bytes, &value.media_type)?;
            bytes.push(u8::try_from(value.metadata.len()).map_err(|_| StateError::Limit)?);
            for (key, value) in &value.metadata {
                text(&mut bytes, key)?;
                text(&mut bytes, value)?;
            }
        }
        if bytes.len() > CELL_BYTES {
            return Err(StateError::Limit);
        }
        Ok(bytes)
    }

    pub fn decode(bytes: &[u8], maximum_generation: u64) -> Result<Self, StateError> {
        if bytes.len() > CELL_BYTES {
            return Err(StateError::Corrupt);
        }
        let mut input = Input { bytes, offset: 0 };
        if input.take(MAGIC.len())? != MAGIC {
            return Err(StateError::UnsupportedFormat);
        }
        let generation = input.u64()?;
        if generation == 0 || generation > maximum_generation {
            return Err(StateError::Corrupt);
        }
        let value = match input.take(1)?[0] {
            0 => None,
            1 => {
                let length = input.u32()? as usize;
                if length > contract::VALUE_BYTES {
                    return Err(StateError::Corrupt);
                }
                let data = input.take(length)?.to_vec();
                let media_type = input.text(contract::MEDIA_TYPE_BYTES)?;
                let count = usize::from(input.take(1)?[0]);
                if count > contract::METADATA_PAIRS {
                    return Err(StateError::Corrupt);
                }
                let mut metadata = Vec::with_capacity(count);
                let mut metadata_bytes = 0usize;
                for _ in 0..count {
                    let key = input.text(contract::IDENTITY_BYTES)?;
                    let value = input.text(1024)?;
                    metadata_bytes = metadata_bytes
                        .checked_add(key.len() + value.len())
                        .ok_or(StateError::Corrupt)?;
                    if metadata_bytes > contract::METADATA_BYTES {
                        return Err(StateError::Corrupt);
                    }
                    metadata.push((key, value));
                }
                let value = Value {
                    bytes: data,
                    media_type,
                    metadata,
                };
                value.validate().map_err(|_| StateError::Corrupt)?;
                Some(value)
            }
            _ => return Err(StateError::Corrupt),
        };
        if input.offset != bytes.len() {
            return Err(StateError::Corrupt);
        }
        Ok(Self { generation, value })
    }
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub(super) struct Usage {
    pub keys: u64,
    pub bytes: u64,
    pub tombstones: u64,
    pub tombstone_bytes: u64,
}

impl Usage {
    pub fn encode(self) -> Vec<u8> {
        let mut bytes = b"LSU\x01".to_vec();
        for value in [self.keys, self.bytes, self.tombstones, self.tombstone_bytes] {
            bytes.extend_from_slice(&value.to_le_bytes());
        }
        bytes
    }

    pub fn decode(bytes: &[u8]) -> Result<Self, StateError> {
        if bytes.len() != 36 || &bytes[..4] != b"LSU\x01" {
            return Err(StateError::Corrupt);
        }
        let mut input = Input { bytes, offset: 4 };
        Ok(Self {
            keys: input.u64()?,
            bytes: input.u64()?,
            tombstones: input.u64()?,
            tombstone_bytes: input.u64()?,
        })
    }
}

pub(super) fn key_prefix(scope: &StateScope) -> Result<Vec<u8>, StateError> {
    let mut prefix = b"state-v1\0".to_vec();
    text(&mut prefix, &scope.tenant.0)?;
    text(&mut prefix, &scope.namespace.0)?;
    prefix.extend_from_slice(&scope.incarnation.to_le_bytes());
    prefix.push(u8::from(scope.entity.is_some()));
    if let Some(entity) = &scope.entity {
        text(&mut prefix, entity)?;
    }
    Ok(prefix)
}

pub(super) fn version(
    scope: &StateScope,
    key: &[u8],
    generation: u64,
) -> Result<Vec<u8>, StateError> {
    let mut hash = Sha256::new();
    hash.update(b"lsf-state-version-v1\0");
    hash.update(key_prefix(scope)?);
    hash.update((key.len() as u64).to_le_bytes());
    hash.update(key);
    let mut token = b"SV\x01".to_vec();
    token.extend_from_slice(&hash.finalize());
    token.extend_from_slice(&scope.incarnation.to_le_bytes());
    token.extend_from_slice(&generation.to_le_bytes());
    Ok(token)
}

fn text(bytes: &mut Vec<u8>, value: &str) -> Result<(), StateError> {
    let length = u16::try_from(value.len()).map_err(|_| StateError::Limit)?;
    bytes.extend_from_slice(&length.to_le_bytes());
    bytes.extend_from_slice(value.as_bytes());
    Ok(())
}

struct Input<'a> {
    bytes: &'a [u8],
    offset: usize,
}

impl Input<'_> {
    fn take(&mut self, length: usize) -> Result<&[u8], StateError> {
        let end = self.offset.checked_add(length).ok_or(StateError::Corrupt)?;
        let value = self
            .bytes
            .get(self.offset..end)
            .ok_or(StateError::Corrupt)?;
        self.offset = end;
        Ok(value)
    }
    fn u32(&mut self) -> Result<u32, StateError> {
        Ok(u32::from_le_bytes(
            self.take(4)?.try_into().map_err(|_| StateError::Corrupt)?,
        ))
    }
    fn u64(&mut self) -> Result<u64, StateError> {
        Ok(u64::from_le_bytes(
            self.take(8)?.try_into().map_err(|_| StateError::Corrupt)?,
        ))
    }
    fn text(&mut self, maximum: usize) -> Result<String, StateError> {
        let length = usize::from(u16::from_le_bytes(
            self.take(2)?.try_into().map_err(|_| StateError::Corrupt)?,
        ));
        if length > maximum {
            return Err(StateError::Corrupt);
        }
        String::from_utf8(self.take(length)?.to_vec()).map_err(|_| StateError::Corrupt)
    }
}
