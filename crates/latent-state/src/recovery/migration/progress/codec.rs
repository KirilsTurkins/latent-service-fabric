//! Canonical checksum and nested length checks precede every retained allocation.
use super::AggregateMigrationProgress;
use crate::embedded::StoreError;
use sha2::{Digest, Sha256};

const MAGIC: &[u8] = b"LMG\0\x02";

pub(super) fn encode(progress: &AggregateMigrationProgress) -> Result<Vec<u8>, StoreError> {
    let mut bytes = MAGIC.to_vec();
    bytes.push(u8::from(progress.completed));
    frame(&mut bytes, progress.operation_id.as_bytes())?;
    frame(&mut bytes, progress.operator_id.as_bytes())?;
    for digest in [
        progress.fingerprint,
        progress.checkpoint_digest,
        progress.checkpoint_manifest_digest,
        progress.package_digest,
        progress.review_digest,
        progress.declaration_digest,
        progress.schema_proof_digest,
        progress.recipe_digest,
    ] {
        bytes.extend_from_slice(&digest);
    }
    frame(&mut bytes, &progress.namespace_row)?;
    for optional in [
        &progress.history_row,
        &progress.guard_row,
        &progress.source_quota,
        &progress.staged_quota,
    ] {
        bytes.push(u8::from(optional.is_some()));
        if let Some(value) = optional {
            frame(&mut bytes, value)?;
        }
    }
    if bytes.len() + 32 > super::super::PROGRESS_BYTES {
        return Err(StoreError::Capacity);
    }
    bytes.extend_from_slice(&Sha256::digest(&bytes));
    Ok(bytes)
}

pub(super) fn decode(bytes: &[u8]) -> Result<AggregateMigrationProgress, StoreError> {
    if bytes.len() < MAGIC.len() + 32 || bytes.len() > super::super::PROGRESS_BYTES {
        return Err(StoreError::Capacity);
    }
    let (data, checksum) = bytes.split_at(bytes.len() - 32);
    if Sha256::digest(data).as_slice() != checksum {
        return Err(StoreError::Corrupt);
    }
    let mut input = Input {
        bytes: data
            .strip_prefix(MAGIC)
            .ok_or(StoreError::UnsupportedFormat)?,
    };
    let completed = input.flag()?;
    let progress = AggregateMigrationProgress {
        completed,
        operation_id: input.text()?,
        operator_id: input.text()?,
        fingerprint: input.digest()?,
        checkpoint_digest: input.digest()?,
        checkpoint_manifest_digest: input.digest()?,
        package_digest: input.digest()?,
        review_digest: input.digest()?,
        declaration_digest: input.digest()?,
        schema_proof_digest: input.digest()?,
        recipe_digest: input.digest()?,
        namespace_row: input.record(crate::namespace::RECORD_BYTES)?,
        history_row: input.optional(crate::namespace::history::HISTORY_BYTES)?,
        guard_row: input.optional(crate::recovery::GUARD_BYTES)?,
        source_quota: input.optional(crate::tenant::RECORD_BYTES)?,
        staged_quota: input.optional(crate::tenant::RECORD_BYTES)?,
    };
    if !input.bytes.is_empty() {
        return Err(StoreError::Corrupt);
    }
    Ok(progress)
}

fn frame(bytes: &mut Vec<u8>, value: &[u8]) -> Result<(), StoreError> {
    bytes.extend_from_slice(
        &u16::try_from(value.len())
            .map_err(|_| StoreError::Capacity)?
            .to_le_bytes(),
    );
    bytes.extend_from_slice(value);
    Ok(())
}

struct Input<'a> {
    bytes: &'a [u8],
}
impl<'a> Input<'a> {
    fn take(&mut self, length: usize) -> Result<&'a [u8], StoreError> {
        let value = self.bytes.get(..length).ok_or(StoreError::Corrupt)?;
        self.bytes = &self.bytes[length..];
        Ok(value)
    }
    fn flag(&mut self) -> Result<bool, StoreError> {
        match self.take(1)?[0] {
            0 => Ok(false),
            1 => Ok(true),
            _ => Err(StoreError::Corrupt),
        }
    }
    fn digest(&mut self) -> Result<[u8; 32], StoreError> {
        self.take(32)?.try_into().map_err(|_| StoreError::Corrupt)
    }
    fn record(&mut self, maximum: usize) -> Result<Vec<u8>, StoreError> {
        let length = usize::from(u16::from_le_bytes(
            self.take(2)?.try_into().map_err(|_| StoreError::Corrupt)?,
        ));
        if length == 0 || length > maximum {
            return Err(StoreError::Corrupt);
        }
        Ok(self.take(length)?.to_vec())
    }
    fn optional(&mut self, maximum: usize) -> Result<Option<Vec<u8>>, StoreError> {
        if self.flag()? {
            Ok(Some(self.record(maximum)?))
        } else {
            Ok(None)
        }
    }
    fn text(&mut self) -> Result<String, StoreError> {
        let text = String::from_utf8(self.record(crate::namespace::IDENTITY_BYTES)?)
            .map_err(|_| StoreError::Corrupt)?;
        crate::namespace::identity(&text).map_err(|_| StoreError::Corrupt)?;
        Ok(text)
    }
}
