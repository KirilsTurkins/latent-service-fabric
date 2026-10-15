//! Explicit activation of reviewed restored migration history. Original
//! migration and generic resume receipts remain separate immutable data.
mod codec;
mod plan;
#[cfg(test)]
mod tests;
pub use plan::{RestoredMigrationResumeObservation, RestoredMigrationResumePlan};

use super::{namespace_resume::NamespaceResumeReceipt, snapshot::SnapshotReceipt};
use crate::{
    embedded::{Family, ReadView, RowKey, StoreError},
    session::{version::ViewIdentity, StateMode, StateScope},
    tenant::{TenantCensusContribution, TenantUsage},
};
use sha2::{Digest, Sha256};

pub const RECEIPT_PREFIX: &[u8] = b"restored-migration-resume-v1\0";
pub const RECEIPT_BYTES: usize = 8192;

#[must_use]
pub fn retained_format() -> crate::namespace::compatibility::RetainedFormat {
    use crate::namespace::compatibility::{RetainedFormat, RetainedKind};
    RetainedFormat {
        kind: RetainedKind::MigrationCheckpoint,
        identity: "latent.restored-migration-resume.v1".into(),
    }
}

/// These exact descriptions are not permission. The installed protected
/// snapshot/current writer and purpose owner still authorize every acceptance.
#[derive(Clone)]
pub struct RestoredMigrationResumeRequest {
    pub scope: StateScope,
    pub operation_id: String,
    pub operator_id: String,
    pub migration_operation_id: String,
    pub expected_view: Vec<u8>,
    pub snapshot_digest: [u8; 32],
    pub manifest_digest: [u8; 32],
    pub restore_operation_digest: [u8; 32],
    pub window_digest: [u8; 32],
    pub review_digest: [u8; 32],
}
impl RestoredMigrationResumeRequest {
    pub(crate) fn validate(&self) -> Result<(), StoreError> {
        for value in [
            &self.scope.tenant.0,
            &self.scope.namespace.0,
            &self.scope.state_schema,
            &self.operation_id,
            &self.operator_id,
            &self.migration_operation_id,
        ] {
            crate::namespace::identity(value).map_err(|_| StoreError::Invalid)?;
            if value.capacity() > crate::namespace::IDENTITY_BYTES {
                return Err(StoreError::Capacity);
            }
        }
        crate::namespace::compatibility::SchemaId::parse(&self.scope.state_schema)
            .map_err(|_| StoreError::Invalid)?;
        if self.scope.mode != StateMode::Command
            || self.scope.entity.is_some()
            || self.expected_view.len() != 67
            || self.expected_view.capacity() > 256
            || [
                self.snapshot_digest,
                self.manifest_digest,
                self.restore_operation_digest,
                self.window_digest,
                self.review_digest,
            ]
            .contains(&[0; 32])
        {
            return Err(StoreError::Invalid);
        }
        ViewIdentity::from_token(&self.scope, &self.expected_view)
            .map_err(|_| StoreError::Invalid)?;
        Ok(())
    }
    pub fn receipt_key(&self) -> Result<RowKey, StoreError> {
        self.validate()?;
        receipt_key(
            &self.scope.tenant.0,
            &self.scope.namespace.0,
            &self.operator_id,
            &self.operation_id,
        )
    }
    fn fingerprint(&self, progress_digest: [u8; 32]) -> Result<[u8; 32], StoreError> {
        self.validate()?;
        let mut hash = Sha256::new();
        hash.update(b"latent-restored-migration-resume-input-v1\0");
        for field in [
            &self.scope.tenant.0,
            &self.scope.namespace.0,
            &self.scope.state_schema,
            &self.operator_id,
            &self.operation_id,
            &self.migration_operation_id,
        ] {
            hash.update((field.len() as u64).to_le_bytes());
            hash.update(field.as_bytes());
        }
        hash.update(self.scope.incarnation.to_le_bytes());
        hash.update(&self.expected_view);
        for digest in [
            self.snapshot_digest,
            self.manifest_digest,
            self.restore_operation_digest,
            self.window_digest,
            self.review_digest,
            progress_digest,
        ] {
            hash.update(digest);
        }
        Ok(hash.finalize().into())
    }
}

fn receipt_key(
    tenant: &str,
    namespace: &str,
    operator: &str,
    operation: &str,
) -> Result<RowKey, StoreError> {
    let mut hash = Sha256::new();
    hash.update(b"latent-restored-migration-resume-key-v1\0");
    for field in [tenant, namespace, operator, operation] {
        crate::namespace::identity(field).map_err(|_| StoreError::Invalid)?;
        hash.update((field.len() as u64).to_le_bytes());
        hash.update(field.as_bytes());
    }
    let mut key = RECEIPT_PREFIX.to_vec();
    key.extend_from_slice(&hash.finalize());
    Ok(RowKey {
        family: Family::Maintenance,
        key,
    })
}

/// Original encoded outcome with explicit restore and migration attribution.
/// Reading or replaying it never makes a later namespace active.
pub struct RestoredMigrationResumeReceipt {
    key_digest: [u8; 32],
    fingerprint: [u8; 32],
    pub(super) operator_id: String,
    pub(super) operation_id: String,
    pub(super) migration_operation_id: String,
    pub(super) snapshot_digest: [u8; 32],
    pub(super) manifest_digest: [u8; 32],
    pub(super) restore_operation_digest: [u8; 32],
    pub(super) window_digest: [u8; 32],
    pub(super) review_digest: [u8; 32],
    pub(super) progress_digest: [u8; 32],
    outcome: NamespaceResumeReceipt,
}
impl RestoredMigrationResumeReceipt {
    #[must_use]
    pub fn namespace(&self) -> &crate::namespace::NamespaceRecord {
        self.outcome.namespace()
    }
    #[must_use]
    pub fn history(&self) -> &crate::namespace::history::NamespaceHistory {
        self.outcome.history()
    }
    pub fn view_token(&self) -> Result<Vec<u8>, StoreError> {
        self.outcome.view_token()
    }
    pub fn validate_row(key: &RowKey, bytes: &[u8]) -> Result<(), StoreError> {
        if key.family != Family::Maintenance || !key.key.starts_with(RECEIPT_PREFIX) {
            return Err(StoreError::UnsupportedFormat);
        }
        let receipt = Self::decode(bytes)?;
        if key.key.len() != RECEIPT_PREFIX.len() + 32
            || key.key[RECEIPT_PREFIX.len()..] != receipt.key_digest
        {
            return Err(StoreError::Corrupt);
        }
        Ok(())
    }
}
pub fn census_contribution(
    view: &ReadView,
    key: &RowKey,
    bytes: &[u8],
) -> Result<TenantCensusContribution, StoreError> {
    RestoredMigrationResumeReceipt::validate_row(key, bytes)?;
    let receipt = RestoredMigrationResumeReceipt::decode(bytes)?;
    let current = super::namespace_resume::NamespaceRecoveryView::capture(
        view,
        &receipt.namespace().tenant,
        &receipt.namespace().id,
    )?;
    if current.namespace.version.incarnation < receipt.namespace().version.incarnation {
        return Err(StoreError::Corrupt);
    }
    Ok(TenantCensusContribution::Usage {
        tenant: receipt.namespace().tenant.clone(),
        usage: TenantUsage {
            metadata_rows: 1,
            metadata_bytes: crate::tenant::row_charge(key, bytes)?,
            ..TenantUsage::default()
        },
    })
}

fn validate_snapshot(
    request: &RestoredMigrationResumeRequest,
    snapshot: &SnapshotReceipt,
) -> Result<(), StoreError> {
    snapshot.manifest.validate()?;
    if snapshot.snapshot_digest != request.snapshot_digest
        || snapshot.manifest_digest != request.manifest_digest
        || snapshot.manifest.metadata.tenant != request.scope.tenant.0
        || snapshot.manifest.namespaces.len() != 1
    {
        return Err(StoreError::Conflict);
    }
    Ok(())
}
