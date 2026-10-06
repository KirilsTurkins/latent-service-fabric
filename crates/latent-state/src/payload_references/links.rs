//! Bounded durable closure for one actual command attempt's attachments.
use super::{
    PayloadOwner, PayloadOwnerKind, PayloadReference, StoreError, MAX_REFERENCE_BYTES,
    MAX_REFERENCE_UPDATES,
};
use crate::embedded::{Family, ReadView, RowKey};

pub const LINKS_PREFIX: &[u8] = b"immutable-payload-links-v1\0";
pub const MAX_LINK_BYTES: usize = 40 * 1024;
const MAGIC: &[u8] = b"LBL\0\x01";

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PayloadLinks {
    pub anchor: PayloadOwner,
    pub references: Vec<PayloadReference>,
}
impl PayloadLinks {
    pub fn validate(&self) -> Result<(), StoreError> {
        self.anchor.row_key()?;
        if self.anchor.kind != PayloadOwnerKind::Result
            || self.references.is_empty()
            || self.references.len() > MAX_REFERENCE_UPDATES
        {
            return Err(StoreError::Invalid);
        }
        for (index, reference) in self.references.iter().enumerate() {
            reference.validate()?;
            let owner = &reference.owner;
            if owner.tenant != self.anchor.tenant
                || owner.namespace != self.anchor.namespace
                || owner.incarnation != self.anchor.incarnation
                || owner.generation != self.anchor.generation
                || !matches!(
                    owner.kind,
                    PayloadOwnerKind::Result | PayloadOwnerKind::Effect
                )
                || owner.kind == PayloadOwnerKind::Result && *owner != self.anchor
                || self.references[..index]
                    .iter()
                    .any(|old| old.owner == *owner)
            {
                return Err(StoreError::Invalid);
            }
        }
        Ok(())
    }
    pub fn row_key(&self) -> Result<RowKey, StoreError> {
        self.validate()?;
        let original = self.anchor.row_key()?;
        let mut key = LINKS_PREFIX.to_vec();
        key.extend_from_slice(&original.key[super::OWNER_PREFIX.len()..]);
        Ok(RowKey {
            family: Family::PayloadReference,
            key,
        })
    }
    pub fn key_for(anchor: &PayloadOwner) -> Result<RowKey, StoreError> {
        if anchor.kind != PayloadOwnerKind::Result {
            return Err(StoreError::Invalid);
        }
        let original = anchor.row_key()?;
        let mut key = LINKS_PREFIX.to_vec();
        key.extend_from_slice(&original.key[super::OWNER_PREFIX.len()..]);
        Ok(RowKey {
            family: Family::PayloadReference,
            key,
        })
    }
    pub fn encode(&self) -> Result<Vec<u8>, StoreError> {
        self.validate()?;
        let mut bytes = MAGIC.to_vec();
        bytes.extend_from_slice(&self.anchor.incarnation.to_le_bytes());
        bytes.extend_from_slice(&self.anchor.identity);
        bytes.extend_from_slice(&self.anchor.generation.to_le_bytes());
        for value in [
            &self.anchor.tenant,
            &self.anchor.namespace,
            &self.anchor.format,
        ] {
            bytes.extend_from_slice(
                &u16::try_from(value.len())
                    .map_err(|_| StoreError::Capacity)?
                    .to_le_bytes(),
            );
            bytes.extend_from_slice(value.as_bytes());
        }
        bytes.push(u8::try_from(self.references.len()).map_err(|_| StoreError::Capacity)?);
        for reference in &self.references {
            let raw = reference.encode()?;
            bytes.extend_from_slice(
                &u16::try_from(raw.len())
                    .map_err(|_| StoreError::Capacity)?
                    .to_le_bytes(),
            );
            bytes.extend_from_slice(&raw);
        }
        if bytes.len() > MAX_LINK_BYTES {
            return Err(StoreError::Capacity);
        }
        Ok(bytes)
    }
    pub fn decode(bytes: &[u8]) -> Result<Self, StoreError> {
        if bytes.len() > MAX_LINK_BYTES || !bytes.starts_with(b"LBL\0") {
            return Err(StoreError::Corrupt);
        }
        if !bytes.starts_with(MAGIC) {
            return Err(StoreError::UnsupportedFormat);
        }
        let mut input = Input {
            bytes,
            offset: MAGIC.len(),
        };
        let incarnation = input.number()?;
        let identity = input
            .take(32)?
            .try_into()
            .map_err(|_| StoreError::Corrupt)?;
        let generation = input.number()?;
        let anchor = PayloadOwner {
            tenant: input.text()?,
            namespace: input.text()?,
            incarnation,
            kind: PayloadOwnerKind::Result,
            identity,
            generation,
            format: input.text()?,
        };
        let count = usize::from(input.take(1)?[0]);
        if count == 0 || count > MAX_REFERENCE_UPDATES {
            return Err(StoreError::Corrupt);
        }
        let mut references = Vec::with_capacity(count);
        for _ in 0..count {
            let length = input.length()?;
            if length > MAX_REFERENCE_BYTES {
                return Err(StoreError::Corrupt);
            }
            references.push(PayloadReference::decode(input.take(length)?)?);
        }
        if input.offset != bytes.len() {
            return Err(StoreError::Corrupt);
        }
        let links = Self { anchor, references };
        links.validate().map_err(|_| StoreError::Corrupt)?;
        Ok(links)
    }
    pub fn verify_rows(&self, view: &ReadView) -> Result<(), StoreError> {
        for reference in &self.references {
            let raw = reference.encode()?;
            if view
                .get_bounded(&reference.owner_key()?, MAX_REFERENCE_BYTES)?
                .as_deref()
                != Some(&raw)
            {
                return Err(StoreError::Corrupt);
            }
            super::validate_row(view, &reference.owner_key()?, &raw)?;
        }
        Ok(())
    }
}
struct Input<'a> {
    bytes: &'a [u8],
    offset: usize,
}
impl<'a> Input<'a> {
    fn take(&mut self, size: usize) -> Result<&'a [u8], StoreError> {
        let end = self.offset.checked_add(size).ok_or(StoreError::Corrupt)?;
        let value = self
            .bytes
            .get(self.offset..end)
            .ok_or(StoreError::Corrupt)?;
        self.offset = end;
        Ok(value)
    }
    fn number(&mut self) -> Result<u64, StoreError> {
        Ok(u64::from_le_bytes(
            self.take(8)?.try_into().map_err(|_| StoreError::Corrupt)?,
        ))
    }
    fn length(&mut self) -> Result<usize, StoreError> {
        Ok(usize::from(u16::from_le_bytes(
            self.take(2)?.try_into().map_err(|_| StoreError::Corrupt)?,
        )))
    }
    fn text(&mut self) -> Result<String, StoreError> {
        let length = self.length()?;
        if length == 0 || length > 128 {
            return Err(StoreError::Corrupt);
        }
        Ok(std::str::from_utf8(self.take(length)?)
            .map_err(|_| StoreError::Corrupt)?
            .into())
    }
}
