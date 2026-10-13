use super::{NamespaceResumeReceipt, RestoredMigrationResumeReceipt, StoreError, RECEIPT_BYTES};
const MAGIC: &[u8] = b"RMA\x01";

impl RestoredMigrationResumeReceipt {
    pub fn encode(&self) -> Result<Vec<u8>, StoreError> {
        self.outcome
            .require_attribution(self.key_digest, self.fingerprint)?;
        let key = super::receipt_key(
            &self.namespace().tenant.0,
            &self.namespace().id.0,
            &self.operator_id,
            &self.operation_id,
        )?;
        if key.key[super::RECEIPT_PREFIX.len()..] != self.key_digest {
            return Err(StoreError::Corrupt);
        }
        let mut bytes = MAGIC.to_vec();
        for digest in [
            self.key_digest,
            self.fingerprint,
            self.snapshot_digest,
            self.manifest_digest,
            self.restore_operation_digest,
            self.window_digest,
            self.review_digest,
            self.progress_digest,
        ] {
            if digest == [0; 32] {
                return Err(StoreError::Corrupt);
            }
            bytes.extend_from_slice(&digest);
        }
        for field in [
            &self.operator_id,
            &self.operation_id,
            &self.migration_operation_id,
        ] {
            crate::namespace::identity(field).map_err(|_| StoreError::Corrupt)?;
            row(&mut bytes, field.as_bytes())?;
        }
        row(&mut bytes, &self.outcome.encode()?)?;
        if bytes.len() > RECEIPT_BYTES {
            return Err(StoreError::Capacity);
        }
        Ok(bytes)
    }
    pub fn decode(bytes: &[u8]) -> Result<Self, StoreError> {
        if bytes.len() < 268 || bytes.len() > RECEIPT_BYTES || !bytes.starts_with(MAGIC) {
            return Err(StoreError::Corrupt);
        }
        let digest = |index: usize| {
            bytes[4 + index * 32..4 + (index + 1) * 32]
                .try_into()
                .map_err(|_| StoreError::Corrupt)
        };
        let mut offset = 260;
        let mut take = || -> Result<&[u8], StoreError> {
            let length = u16::from_le_bytes(
                bytes
                    .get(offset..offset + 2)
                    .ok_or(StoreError::Corrupt)?
                    .try_into()
                    .map_err(|_| StoreError::Corrupt)?,
            ) as usize;
            offset += 2;
            let field = bytes
                .get(offset..offset + length)
                .ok_or(StoreError::Corrupt)?;
            offset += length;
            Ok(field)
        };
        let text = |bytes: &[u8]| -> Result<String, StoreError> {
            let value = std::str::from_utf8(bytes).map_err(|_| StoreError::Corrupt)?;
            crate::namespace::identity(value).map_err(|_| StoreError::Corrupt)?;
            Ok(value.into())
        };
        let receipt = Self {
            key_digest: digest(0)?,
            fingerprint: digest(1)?,
            snapshot_digest: digest(2)?,
            manifest_digest: digest(3)?,
            restore_operation_digest: digest(4)?,
            window_digest: digest(5)?,
            review_digest: digest(6)?,
            progress_digest: digest(7)?,
            operator_id: text(take()?)?,
            operation_id: text(take()?)?,
            migration_operation_id: text(take()?)?,
            outcome: NamespaceResumeReceipt::decode(take()?)?,
        };
        if offset != bytes.len() || receipt.encode()? != bytes {
            return Err(StoreError::Corrupt);
        }
        Ok(receipt)
    }
}
fn row(output: &mut Vec<u8>, bytes: &[u8]) -> Result<(), StoreError> {
    output.extend_from_slice(
        &u16::try_from(bytes.len())
            .map_err(|_| StoreError::Capacity)?
            .to_le_bytes(),
    );
    output.extend_from_slice(bytes);
    Ok(())
}
