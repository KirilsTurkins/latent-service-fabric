//! Explicit activation of one completed fixed migration. Plans and historical
//! receipts carry exact originals, never publication, clock or provider grants.
//! The protected snapshot owner supplies physical custody and current approval.

mod codec;
mod plan;

pub use plan::{MigrationResumeObservation, MigrationResumePlan};

use super::migration::{AggregateMigrationProgress, AggregateMigrationRequest};
use crate::{
    embedded::{Family, ReadView, RowKey, StoreError},
    namespace::{
        compatibility::{RetainedFormat, RetainedKind, SchemaId},
        history::{HistoryStatus, NamespaceHistory},
        NamespaceRecord, NamespaceStatus,
    },
    session::{version::ViewIdentity, StateMode, StateScope},
    tenant::{TenantCensusContribution, TenantUsage},
};
use sha2::{Digest, Sha256};

pub const RECEIPT_PREFIX: &[u8] = b"migration-resume-v1\0";
pub const RECEIPT_BYTES: usize = 8192;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MigrationResumeAction {
    Activate,
    Replay,
}

/// Attributed original operation data. The host derives the actor/scope and
/// seals current access separately. A changed expected view is a new request,
/// never a permitted way to recover this operation's lost response.
#[derive(Debug, Clone)]
pub struct MigrationResumeRequest {
    pub scope: StateScope,
    pub operation_id: String,
    pub operator_id: String,
    pub expected_view: Vec<u8>,
    pub migration: AggregateMigrationRequest,
    pub review_digest: [u8; 32],
}

impl MigrationResumeRequest {
    pub fn validate(&self) -> Result<(), StoreError> {
        self.migration.validate()?;
        for identity in [
            &self.scope.tenant.0,
            &self.scope.namespace.0,
            &self.scope.state_schema,
            &self.operation_id,
            &self.operator_id,
        ] {
            crate::namespace::identity(identity).map_err(|_| StoreError::Invalid)?;
            if identity.capacity() > crate::namespace::IDENTITY_BYTES {
                return Err(StoreError::Capacity);
            }
        }
        SchemaId::parse(&self.scope.state_schema).map_err(|_| StoreError::Invalid)?;
        if self.scope.entity.is_some()
            || self.scope.mode != StateMode::Command
            || self.scope.tenant != self.migration.scope.tenant
            || self.scope.namespace != self.migration.scope.namespace
            || self.scope.incarnation != self.migration.scope.incarnation
            || self.review_digest == [0; 32]
            || self.expected_view.capacity() > 256
        {
            return Err(StoreError::Invalid);
        }
        ViewIdentity::from_token(&self.scope, &self.expected_view)
            .map_err(|_| StoreError::Invalid)?;
        Ok(())
    }

    pub fn receipt_key(&self) -> Result<RowKey, StoreError> {
        self.validate()?;
        let mut hash = Sha256::new();
        hash.update(RECEIPT_PREFIX);
        for identity in [
            &self.scope.tenant.0,
            &self.scope.namespace.0,
            &self.operator_id,
            &self.operation_id,
        ] {
            hash.update((identity.len() as u64).to_le_bytes());
            hash.update(identity.as_bytes());
        }
        let mut key = RECEIPT_PREFIX.to_vec();
        key.extend_from_slice(&hash.finalize());
        Ok(RowKey {
            family: Family::Maintenance,
            key,
        })
    }

    fn fingerprint(&self) -> Result<[u8; 32], StoreError> {
        let mut hash = Sha256::new();
        hash.update(b"latent-migration-resume-input-v1\0");
        hash.update(codec::request(self)?);
        Ok(hash.finalize().into())
    }
}

/// Exact durable outcome over the original request, migration row and paused
/// namespace/history. Decoding is data access; it cannot reactivate that scope.
#[derive(Debug, Clone)]
pub struct MigrationResumeReceipt {
    request: MigrationResumeRequest,
    progress_digest: [u8; 32],
    before: NamespaceRecord,
    history_before: NamespaceHistory,
}

impl MigrationResumeReceipt {
    #[must_use]
    pub fn request(&self) -> &MigrationResumeRequest {
        &self.request
    }

    #[must_use]
    pub const fn progress_digest(&self) -> [u8; 32] {
        self.progress_digest
    }

    /// Immutable historical activation result, separate from the current row.
    pub fn namespace(&self) -> Result<NamespaceRecord, StoreError> {
        let mut namespace = self.before.clone();
        namespace.version.generation = namespace
            .version
            .generation
            .checked_add(1)
            .ok_or(StoreError::Capacity)?;
        namespace.status = NamespaceStatus::Active;
        namespace.validate().map_err(|_| StoreError::Corrupt)?;
        Ok(namespace)
    }

    pub fn history(&self) -> Result<NamespaceHistory, StoreError> {
        let mut history = self.history_before.clone();
        history.status = HistoryStatus::Ready;
        history
            .check_namespace(&self.namespace()?)
            .map_err(|_| StoreError::Corrupt)?;
        Ok(history)
    }

    pub fn view_token(&self) -> Result<Vec<u8>, StoreError> {
        ViewIdentity {
            namespace: self.namespace()?.version,
            epochs: self.history()?.epochs,
        }
        .token(&self.request.scope)
        .map_err(|_| StoreError::Corrupt)
    }

    pub fn encode(&self) -> Result<Vec<u8>, StoreError> {
        self.validate()?;
        codec::encode(self)
    }

    pub fn decode(bytes: &[u8]) -> Result<Self, StoreError> {
        let receipt = codec::decode(bytes)?;
        receipt.validate().map_err(|_| StoreError::Corrupt)?;
        if receipt.encode()? != bytes {
            return Err(StoreError::Corrupt);
        }
        Ok(receipt)
    }

    pub fn validate_row(key: &RowKey, bytes: &[u8]) -> Result<(), StoreError> {
        if key.family != Family::Maintenance || !key.key.starts_with(RECEIPT_PREFIX) {
            return Err(StoreError::UnsupportedFormat);
        }
        if Self::decode(bytes)?.request.receipt_key()? != *key {
            return Err(StoreError::Corrupt);
        }
        Ok(())
    }

    fn validate(&self) -> Result<(), StoreError> {
        self.request.validate()?;
        self.before.validate().map_err(|_| StoreError::Corrupt)?;
        self.history_before
            .check_namespace(&self.before)
            .map_err(|_| StoreError::Corrupt)?;
        if self.progress_digest == [0; 32]
            || self.before.tenant != self.request.scope.tenant
            || self.before.id != self.request.scope.namespace
            || self.before.version.incarnation != self.request.scope.incarnation
            || self.before.state_schema != self.request.scope.state_schema
            || self.before.status != NamespaceStatus::Quiescing
            || self.history_before.status != HistoryStatus::ReconciliationRequired
            || (ViewIdentity {
                namespace: self.before.version,
                epochs: self.history_before.epochs,
            })
            .token(&self.request.scope)
            .map_err(|_| StoreError::Corrupt)?
                != self.request.expected_view
        {
            return Err(StoreError::Corrupt);
        }
        self.namespace()?;
        self.history()?;
        Ok(())
    }

    fn require_progress(&self, progress: &AggregateMigrationProgress) -> Result<(), StoreError> {
        progress
            .require_input(&self.request.migration)
            .map_err(|_| StoreError::Corrupt)?;
        if !progress.completed()
            || <[u8; 32]>::from(Sha256::digest(progress.encode()?)) != self.progress_digest
            || progress.result_namespace()? != self.before
            || progress.result_history()? != self.history_before
        {
            return Err(StoreError::Corrupt);
        }
        Ok(())
    }
}

#[must_use]
pub fn retained_format() -> RetainedFormat {
    RetainedFormat {
        kind: RetainedKind::MigrationCheckpoint,
        identity: "latent.migration-resume.v1".into(),
    }
}

/// Descriptive receipt lookup remains available while a later restore is
/// paused. The caller retains its real current read/audit/response owners.
pub fn inspect_receipt(
    view: &ReadView,
    request: &MigrationResumeRequest,
) -> Result<Option<MigrationResumeReceipt>, StoreError> {
    let key = request.receipt_key()?;
    view.get_bounded(&key, RECEIPT_BYTES)?
        .map(|bytes| {
            census_contribution(view, &key, &bytes)?;
            let receipt = MigrationResumeReceipt::decode(&bytes)?;
            if receipt.request.fingerprint()? != request.fingerprint()? {
                return Err(StoreError::Conflict);
            }
            Ok(receipt)
        })
        .transpose()
}

/// The supported producer supplies its exact receipt/progress/namespace link
/// to the original tenant census. No row can borrow another tenant's allowance.
pub fn census_contribution(
    view: &ReadView,
    key: &RowKey,
    bytes: &[u8],
) -> Result<TenantCensusContribution, StoreError> {
    MigrationResumeReceipt::validate_row(key, bytes)?;
    let receipt = MigrationResumeReceipt::decode(bytes)?;
    let migration = &receipt.request.migration;
    let progress_key = migration.progress_key()?;
    let progress_bytes = view
        .get_bounded(&progress_key, super::migration::PROGRESS_BYTES)?
        .ok_or(StoreError::Corrupt)?;
    AggregateMigrationProgress::validate_row(&progress_key, &progress_bytes)?;
    receipt.require_progress(&AggregateMigrationProgress::decode(&progress_bytes)?)?;
    let current = super::migration::NamespaceMigrationView::capture(
        view,
        &receipt.before.tenant,
        &receipt.before.id,
    )?;
    if current.namespace.version.incarnation < receipt.before.version.incarnation {
        return Err(StoreError::Corrupt);
    }
    Ok(TenantCensusContribution::Usage {
        tenant: receipt.before.tenant,
        usage: TenantUsage {
            metadata_rows: 1,
            metadata_bytes: crate::tenant::row_charge(key, bytes)?,
            ..TenantUsage::default()
        },
    })
}

#[cfg(test)]
mod tests;
