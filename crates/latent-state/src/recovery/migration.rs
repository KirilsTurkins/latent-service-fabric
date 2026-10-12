//! Fixed, explicitly paused application migration. Logical plans own exact row
//! originals; production applies them only through the SAME protected snapshot
//! custody, original Recovery reservation and short current writer fence.
//! Retained receipts and compatibility descriptions are never access grants.

mod accounting;
mod checkpoint;
mod plan;
mod progress;
mod recipe;
mod view;

pub use checkpoint::VerifiedMigrationCheckpoint;
pub use plan::{AggregateMigrationObservation, AggregateMigrationPlan};
pub use progress::AggregateMigrationProgress;
pub use recipe::AggregateMigrationRecipe;
pub use view::NamespaceMigrationView;

use crate::{
    embedded::{Family, ReadView, RowKey, StoreError},
    namespace::{
        compatibility::{RetainedFormat, RetainedKind},
        namespace_record_key, NamespaceRecord,
    },
    session::{version::ViewIdentity, StateMode, StateScope},
    tenant::{TenantCensusContribution, TenantUsage},
};
use sha2::{Digest, Sha256};

pub const PROGRESS_PREFIX: &[u8] = b"aggregate-migration-v2\0";
pub const PROGRESS_BYTES: usize = 8192;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MigrationPhase {
    Stage,
    Complete,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MigrationAction {
    Stage,
    Complete,
    Replay,
}

/// Healthy review/format/currentness refusal is separate from actual source
/// corruption or uncertain persistence. Neither category proves native cleanup.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MigrationError {
    Source(StoreError),
    Review(StoreError),
    Deadline,
    Capacity,
}

impl MigrationError {
    pub(crate) fn source(error: StoreError) -> Self {
        match error {
            StoreError::SnapshotExpired => Self::Deadline,
            StoreError::Capacity => Self::Capacity,
            StoreError::Invalid | StoreError::Conflict | StoreError::UnsupportedFormat => {
                Self::Review(error)
            }
            _ => Self::Source(error),
        }
    }
}

/// Original attributable operation data. A current host reviewer supplies the
/// exact package/schema evidence; callers cannot choose a transformer or key.
#[derive(Debug, Clone)]
pub struct AggregateMigrationRequest {
    pub scope: StateScope,
    pub operation_id: String,
    pub operator_id: String,
    pub expected_view: Vec<u8>,
    pub checkpoint_digest: [u8; 32],
    pub checkpoint_manifest_digest: [u8; 32],
    pub package_digest: [u8; 32],
    pub review_digest: [u8; 32],
}

impl AggregateMigrationRequest {
    pub fn validate(&self) -> Result<(), StoreError> {
        for identity in [
            &self.operation_id,
            &self.operator_id,
            &self.scope.tenant.0,
            &self.scope.namespace.0,
            &self.scope.state_schema,
        ] {
            crate::namespace::identity(identity).map_err(|_| StoreError::Invalid)?;
            if identity.capacity() > crate::namespace::IDENTITY_BYTES {
                return Err(StoreError::Capacity);
            }
        }
        if self.scope.entity.is_some()
            || self.scope.mode != StateMode::Command
            || self.expected_view.capacity() > 256
            || self.scope.state_schema != recipe::schema_ids()?.0.as_str()
            || [
                self.checkpoint_digest,
                self.checkpoint_manifest_digest,
                self.package_digest,
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

    pub fn progress_key(&self) -> Result<RowKey, StoreError> {
        self.validate()?;
        operation_key(&self.scope, &self.operator_id, &self.operation_id)
    }

    fn fingerprint(&self, recipe: AggregateMigrationRecipe) -> Result<[u8; 32], StoreError> {
        self.validate()?;
        let mut hash = Sha256::new();
        hash.update(b"lsf-protected-aggregate-migration-input-v2\0");
        hash.update(self.progress_key()?.key);
        hash.update(&self.expected_view);
        for value in [
            self.checkpoint_digest,
            self.checkpoint_manifest_digest,
            self.package_digest,
            self.review_digest,
            recipe.digest(),
        ] {
            hash.update(value);
        }
        Ok(hash.finalize().into())
    }
}

fn operation_key(scope: &StateScope, actor: &str, operation: &str) -> Result<RowKey, StoreError> {
    if scope.incarnation == 0 {
        return Err(StoreError::Invalid);
    }
    let mut key = PROGRESS_PREFIX.to_vec();
    key.extend_from_slice(
        &namespace_record_key(&scope.tenant, &scope.namespace).map_err(|_| StoreError::Invalid)?,
    );
    key.extend_from_slice(&scope.incarnation.to_le_bytes());
    let mut hash = Sha256::new();
    hash.update(PROGRESS_PREFIX);
    for identity in [scope.tenant.0.as_str(), actor, operation] {
        hash.update((identity.len() as u64).to_le_bytes());
        hash.update(identity.as_bytes());
    }
    key.extend_from_slice(&hash.finalize());
    Ok(RowKey {
        family: Family::Maintenance,
        key,
    })
}

#[must_use]
pub fn retained_format() -> RetainedFormat {
    RetainedFormat {
        kind: RetainedKind::MigrationCheckpoint,
        identity: "latent.aggregate-migration.v2".into(),
    }
}

/// Exact original durable status on one borrowed native view. The host must
/// retain its separately sealed current Recovery read/audit and response owners;
/// this descriptor admits no migration, grants no namespace access, and cannot
/// resume an interrupted operation or renew its original execution decision.
pub fn inspect_progress(
    view: &ReadView,
    scope: &StateScope,
    operator: &str,
    operation: &str,
) -> Result<Option<AggregateMigrationProgress>, StoreError> {
    if scope.entity.is_some() {
        return Err(StoreError::Invalid);
    }
    for identity in [
        scope.tenant.0.as_str(),
        scope.namespace.0.as_str(),
        operator,
        operation,
    ] {
        crate::namespace::identity(identity).map_err(|_| StoreError::Invalid)?;
    }
    let key = operation_key(scope, operator, operation)?;
    view.get_bounded(&key, PROGRESS_BYTES)?
        .map(|bytes| {
            census_contribution(view, &key, &bytes)?;
            AggregateMigrationProgress::decode(&bytes)
        })
        .transpose()
}

/// Original producer ownership for the shared startup/recovery census. Exact
/// local codec/key and namespace association are mandatory; these data supply
/// neither current authority nor permission to normalize an old checkpoint.
pub fn census_contribution(
    view: &ReadView,
    key: &RowKey,
    bytes: &[u8],
) -> Result<TenantCensusContribution, StoreError> {
    AggregateMigrationProgress::validate_row(key, bytes)?;
    let progress = AggregateMigrationProgress::decode(bytes)?;
    let source = progress.source_namespace()?;
    let current = NamespaceMigrationView::capture(view, &source.tenant, &source.id)?;
    if current.namespace.version.incarnation < source.version.incarnation {
        return Err(StoreError::Corrupt);
    }
    Ok(TenantCensusContribution::Usage {
        tenant: source.tenant,
        usage: TenantUsage {
            metadata_rows: 1,
            metadata_bytes: crate::tenant::row_charge(key, bytes)?,
            ..TenantUsage::default()
        },
    })
}

/// A normal namespace transition cannot bypass retained incomplete migration.
/// A receipt replay is still historical data and is checked before this guard.
pub(crate) fn require_no_incomplete(
    view: &ReadView,
    namespace: &NamespaceRecord,
) -> Result<(), StoreError> {
    super::v1::migration::require_resume_ready(view, namespace)?;
    let mut prefix = PROGRESS_PREFIX.to_vec();
    prefix.extend_from_slice(
        &namespace_record_key(&namespace.tenant, &namespace.id).map_err(|_| StoreError::Invalid)?,
    );
    prefix.extend_from_slice(&namespace.version.incarnation.to_le_bytes());
    let page = view.scan_after(Family::Maintenance, &prefix, None, 128, 1024 * 1024)?;
    if page.resume.is_some() {
        return Err(StoreError::Capacity);
    }
    for (key, bytes) in page.rows {
        AggregateMigrationProgress::validate_row(&key, &bytes)?;
        if !AggregateMigrationProgress::decode(&bytes)?.completed() {
            return Err(StoreError::Unavailable);
        }
    }
    Ok(())
}

#[cfg(test)]
pub(crate) mod tests;
