use super::{MigrationResumeReceipt, MigrationResumeRequest, RECEIPT_BYTES};
use crate::{
    embedded::StoreError,
    namespace::{history::NamespaceHistory, NamespaceRecord},
    recovery::migration::AggregateMigrationRequest,
    session::{StateMode, StateScope},
};
use latent_core::{StateNamespaceId, TenantId};

const MAGIC: &[u8] = b"LMR\0\x01";
const REQUEST_BYTES: usize = 4096;

pub(super) fn request(request: &MigrationResumeRequest) -> Result<Vec<u8>, StoreError> {
    request.validate()?;
    let migration = &request.migration;
    let mut bytes = Vec::with_capacity(2048);
    for value in [
        request.scope.tenant.0.as_bytes(),
        request.scope.namespace.0.as_bytes(),
        request.scope.state_schema.as_bytes(),
        request.operation_id.as_bytes(),
        request.operator_id.as_bytes(),
        request.expected_view.as_slice(),
        migration.scope.state_schema.as_bytes(),
        migration.operation_id.as_bytes(),
        migration.operator_id.as_bytes(),
        migration.expected_view.as_slice(),
    ] {
        frame(&mut bytes, value)?;
    }
    bytes.extend_from_slice(&request.scope.incarnation.to_le_bytes());
    for digest in [
        migration.checkpoint_digest,
        migration.checkpoint_manifest_digest,
        migration.package_digest,
        migration.review_digest,
        request.review_digest,
    ] {
        bytes.extend_from_slice(&digest);
    }
    if bytes.len() > REQUEST_BYTES {
        return Err(StoreError::Capacity);
    }
    Ok(bytes)
}

pub(super) fn encode(receipt: &MigrationResumeReceipt) -> Result<Vec<u8>, StoreError> {
    let mut bytes = MAGIC.to_vec();
    frame(&mut bytes, &request(&receipt.request)?)?;
    bytes.extend_from_slice(&receipt.progress_digest);
    frame(
        &mut bytes,
        &receipt.before.encode().map_err(|_| StoreError::Corrupt)?,
    )?;
    frame(
        &mut bytes,
        &receipt
            .history_before
            .encode()
            .map_err(|_| StoreError::Corrupt)?,
    )?;
    if bytes.len() > RECEIPT_BYTES {
        return Err(StoreError::Capacity);
    }
    Ok(bytes)
}

pub(super) fn decode(bytes: &[u8]) -> Result<MigrationResumeReceipt, StoreError> {
    if bytes.len() > RECEIPT_BYTES || bytes.len() < MAGIC.len() {
        return Err(StoreError::Corrupt);
    }
    if !bytes.starts_with(MAGIC) {
        return Err(StoreError::UnsupportedFormat);
    }
    let mut cursor = Cursor {
        bytes,
        offset: MAGIC.len(),
    };
    let request = decode_request(cursor.frame(REQUEST_BYTES)?)?;
    let progress_digest = cursor.digest()?;
    let before = NamespaceRecord::decode(cursor.frame(crate::namespace::RECORD_BYTES)?)
        .map_err(|_| StoreError::Corrupt)?;
    let history_before =
        NamespaceHistory::decode(cursor.frame(crate::namespace::history::HISTORY_BYTES)?)
            .map_err(|_| StoreError::Corrupt)?;
    cursor.finish()?;
    Ok(MigrationResumeReceipt {
        request,
        progress_digest,
        before,
        history_before,
    })
}

fn decode_request(bytes: &[u8]) -> Result<MigrationResumeRequest, StoreError> {
    let mut cursor = Cursor { bytes, offset: 0 };
    let tenant = TenantId(cursor.text()?);
    let namespace = StateNamespaceId(cursor.text()?);
    let state_schema = cursor.text()?;
    let operation_id = cursor.text()?;
    let operator_id = cursor.text()?;
    let expected_view = cursor.frame(256)?.to_vec();
    let source_schema = cursor.text()?;
    let migration_operation = cursor.text()?;
    let migration_operator = cursor.text()?;
    let migration_view = cursor.frame(256)?.to_vec();
    let incarnation = u64::from_le_bytes(
        cursor
            .take(8)?
            .try_into()
            .map_err(|_| StoreError::Corrupt)?,
    );
    let migration = AggregateMigrationRequest {
        scope: StateScope {
            tenant: tenant.clone(),
            namespace: namespace.clone(),
            incarnation,
            state_schema: source_schema,
            entity: None,
            mode: StateMode::Command,
        },
        operation_id: migration_operation,
        operator_id: migration_operator,
        expected_view: migration_view,
        checkpoint_digest: cursor.digest()?,
        checkpoint_manifest_digest: cursor.digest()?,
        package_digest: cursor.digest()?,
        review_digest: cursor.digest()?,
    };
    let request = MigrationResumeRequest {
        scope: StateScope {
            tenant,
            namespace,
            incarnation,
            state_schema,
            entity: None,
            mode: StateMode::Command,
        },
        operation_id,
        operator_id,
        expected_view,
        migration,
        review_digest: cursor.digest()?,
    };
    cursor.finish()?;
    request.validate().map_err(|_| StoreError::Corrupt)?;
    Ok(request)
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

struct Cursor<'a> {
    bytes: &'a [u8],
    offset: usize,
}
impl<'a> Cursor<'a> {
    fn take(&mut self, length: usize) -> Result<&'a [u8], StoreError> {
        let end = self.offset.checked_add(length).ok_or(StoreError::Corrupt)?;
        let result = self
            .bytes
            .get(self.offset..end)
            .ok_or(StoreError::Corrupt)?;
        self.offset = end;
        Ok(result)
    }
    fn frame(&mut self, maximum: usize) -> Result<&'a [u8], StoreError> {
        let length = usize::from(u16::from_le_bytes(
            self.take(2)?.try_into().map_err(|_| StoreError::Corrupt)?,
        ));
        if length > maximum {
            return Err(StoreError::Corrupt);
        }
        self.take(length)
    }
    fn text(&mut self) -> Result<String, StoreError> {
        String::from_utf8(self.frame(crate::namespace::IDENTITY_BYTES)?.to_vec())
            .map_err(|_| StoreError::Corrupt)
    }
    fn digest(&mut self) -> Result<[u8; 32], StoreError> {
        self.take(32)?.try_into().map_err(|_| StoreError::Corrupt)
    }
    fn finish(&self) -> Result<(), StoreError> {
        if self.offset != self.bytes.len() {
            return Err(StoreError::Corrupt);
        }
        Ok(())
    }
}
