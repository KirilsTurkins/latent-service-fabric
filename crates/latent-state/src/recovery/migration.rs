//! One fixed, deliberately quiesced application migration. Its installed host
//! owner reviews exact package/checkpoint evidence; no guest, shell or provider
//! transformer runs. Completion does not activate the namespace or redrive work.

mod checkpoint;
mod progress;
pub use checkpoint::package_identity;
pub use checkpoint::VerifiedMigrationCheckpoint;
pub use progress::AggregateMigrationProgress;

use super::{guard_key, require_ready, resume::NamespaceRecoveryView};
use crate::{
    embedded::{AtomicBatch, ExpectedRow, ReadView, RowMutation, StoreError},
    namespace::{
        compatibility::{RetainedFormat, RetainedKind, ReviewedSchema, SchemaId},
        history::{history_key, HistoryStatus},
        namespace_record_key, NamespaceRecord, NamespaceStatus,
    },
    session::version::ViewIdentity,
};
use sha2::{Digest, Sha256};
use std::time::Instant;

pub const PROGRESS_PREFIX: &[u8] = b"aggregate-migration-v1\0";
pub const PROGRESS_BYTES: usize = 16 * 1024;
pub const OPERATION_BYTES: u64 = 64 * 1024;
pub const RECIPE: &[u8] =
    include_bytes!("../../../../contracts/state/aggregate-v1-to-v2-migration.json");
const V1: &[u8] =
    include_bytes!("../../../../contracts/state/application-aggregate-v1.schema.json");
const V2: &[u8] =
    include_bytes!("../../../../contracts/state/application-aggregate-v2.schema.json");

#[must_use]
pub fn retained_format() -> RetainedFormat {
    RetainedFormat {
        kind: RetainedKind::MigrationCheckpoint,
        identity: "lsf.aggregate-migration.v1".into(),
    }
}
pub fn schema_ids() -> Result<(SchemaId, SchemaId), StoreError> {
    Ok((
        SchemaId::from_definition(V1).map_err(|_| StoreError::Corrupt)?,
        SchemaId::from_definition(V2).map_err(|_| StoreError::Corrupt)?,
    ))
}

#[derive(Debug, Clone)]
pub struct AggregateMigrationRequest {
    pub scope: crate::session::StateScope,
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
        }
        if self.scope.entity.is_some()
            || self.scope.mode != crate::session::StateMode::Command
            || self.review_digest == [0; 32]
        {
            return Err(StoreError::Invalid);
        }
        ViewIdentity::from_token(&self.scope, &self.expected_view)
            .map_err(|_| StoreError::Invalid)?;
        if self.scope.state_schema != schema_ids()?.0.as_str()
            || [
                self.checkpoint_digest,
                self.checkpoint_manifest_digest,
                self.package_digest,
            ]
            .contains(&[0; 32])
        {
            return Err(StoreError::Invalid);
        }
        Ok(())
    }
    pub fn progress_key(&self) -> Result<crate::embedded::RowKey, StoreError> {
        self.validate()?;
        let mut hash = Sha256::new();
        hash.update(PROGRESS_PREFIX);
        for identity in [&self.scope.tenant.0, &self.operator_id, &self.operation_id] {
            hash.update((identity.len() as u64).to_le_bytes());
            hash.update(identity.as_bytes());
        }
        let mut key = progress_prefix(
            &self.scope.tenant,
            &self.scope.namespace,
            self.scope.incarnation,
        )?;
        key.extend_from_slice(&hash.finalize());
        Ok(crate::embedded::RowKey {
            family: crate::embedded::Family::Maintenance,
            key,
        })
    }
    fn fingerprint(&self) -> Result<[u8; 32], StoreError> {
        self.validate()?;
        let mut hash = Sha256::new();
        hash.update(b"lsf-aggregate-migration-input-v1\0");
        hash.update(self.progress_key()?.key);
        hash.update(&self.expected_view);
        for value in [
            self.checkpoint_digest,
            self.checkpoint_manifest_digest,
            self.package_digest,
            self.review_digest,
            Sha256::digest(RECIPE).into(),
        ] {
            hash.update(value);
        }
        Ok(hash.finalize().into())
    }
}

fn progress_prefix(
    tenant: &latent_core::TenantId,
    namespace: &latent_core::StateNamespaceId,
    incarnation: u64,
) -> Result<Vec<u8>, StoreError> {
    if incarnation == 0 {
        return Err(StoreError::Invalid);
    }
    let mut prefix = PROGRESS_PREFIX.to_vec();
    prefix.extend_from_slice(
        &namespace_record_key(tenant, namespace).map_err(|_| StoreError::Invalid)?,
    );
    prefix.extend_from_slice(&incarnation.to_le_bytes());
    Ok(prefix)
}

/// An incomplete fixed recipe cannot be bypassed by ordinary namespace resume.
/// Finite per-namespace operation inventory refuses excess rows without trimming.
pub fn require_resume_ready(
    view: &ReadView,
    namespace: &NamespaceRecord,
) -> Result<(), StoreError> {
    let prefix = progress_prefix(
        &namespace.tenant,
        &namespace.id,
        namespace.version.incarnation,
    )?;
    let page = view.scan_after(
        crate::embedded::Family::Maintenance,
        &prefix,
        None,
        128,
        4 * 1024 * 1024,
    )?;
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

/// The installed reviewer sees actual current rows and retained checkpoint
/// evidence. A declaration alone does not prove arbitrary opaque compatibility.
pub struct AggregateMigrationObservation<'a> {
    pub current: &'a NamespaceRecoveryView,
    pub checkpoint: &'a VerifiedMigrationCheckpoint,
    pub schema: &'a ReviewedSchema,
    pub original_progress: Option<&'a AggregateMigrationProgress>,
}
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MigrationAction {
    Stage,
    Complete,
    Replay,
}

pub struct AggregateMigrationPlan {
    batch: AtomicBatch,
    progress: AggregateMigrationProgress,
    action: MigrationAction,
}
impl AggregateMigrationPlan {
    /// Only on the actual exclusively owned, quiesced physical worker. The
    /// facade retains its root/worker/buffers and original deadline to retirement.
    pub fn prepare(
        view: &ReadView,
        request: &AggregateMigrationRequest,
        checkpoint: &VerifiedMigrationCheckpoint,
        schema: &ReviewedSchema,
        phase: MigrationAction,
        deadline: Instant,
        review: impl FnOnce(
            &ReadView,
            &AggregateMigrationRequest,
            AggregateMigrationObservation<'_>,
        ) -> Result<(), StoreError>,
    ) -> Result<Self, StoreError> {
        if phase == MigrationAction::Replay {
            return Err(StoreError::Invalid);
        }
        request.validate()?;
        require_ready(view)?;
        super::snapshot::validate_deadline(deadline)?;
        checkpoint.require_request(request)?;
        let current =
            NamespaceRecoveryView::capture(view, &request.scope.tenant, &request.scope.namespace)?;
        let key = request.progress_key()?;
        let bytes = view.get(&key)?;
        let prior = bytes
            .as_deref()
            .map(AggregateMigrationProgress::decode)
            .transpose()?;
        if let Some(prior) = &prior {
            AggregateMigrationProgress::validate_row(&key, bytes.as_ref().unwrap())?;
            prior.require_request(request, schema)?;
        } else {
            require_source(&current, request, schema)?;
        }
        if prior.as_ref().is_none_or(|p| !p.completed()) {
            checkpoint.require_current(view, prior.as_ref(), &key, deadline)?;
        }
        review(
            view,
            request,
            AggregateMigrationObservation {
                current: &current,
                checkpoint,
                schema,
                original_progress: prior.as_ref(),
            },
        )?;
        match prior {
            Some(progress) if progress.completed() || phase == MigrationAction::Stage => {
                Self::replay(view, &current, key, bytes, progress)
            }
            Some(progress) => Self::complete(view, &current, key, bytes, progress),
            None if phase == MigrationAction::Stage => Self::stage(view, &current, request, schema),
            None => Err(StoreError::Unavailable),
        }
    }

    fn stage(
        view: &ReadView,
        current: &NamespaceRecoveryView,
        request: &AggregateMigrationRequest,
        schema: &ReviewedSchema,
    ) -> Result<Self, StoreError> {
        // Refuse unsupported values and insufficient namespace quota BEFORE
        // publishing even the paused progress marker. No transformed bytes are
        // published by this stage.
        crate::session::offline::aggregate_v1_to_v2(view, &current.namespace)?;
        let progress = AggregateMigrationProgress::new(view, current, request, schema)?;
        let key = request.progress_key()?;
        let history_key = progress.history_key()?;
        let batch = AtomicBatch {
            expectations: vec![
                progress.namespace_expectation()?,
                progress.history_expectation()?,
                progress.guard_expectation(),
                ExpectedRow {
                    key: key.clone(),
                    value: None,
                },
            ],
            mutations: vec![
                RowMutation {
                    key: history_key,
                    value: Some(progress.staged_history()?),
                },
                RowMutation {
                    key,
                    value: Some(progress.encode()?),
                },
            ],
        };
        Ok(Self {
            batch,
            progress,
            action: MigrationAction::Stage,
        })
    }

    fn complete(
        view: &ReadView,
        current: &NamespaceRecoveryView,
        key: crate::embedded::RowKey,
        bytes: Option<Vec<u8>>,
        mut progress: AggregateMigrationProgress,
    ) -> Result<Self, StoreError> {
        if current.namespace != progress.source_namespace()?
            || current.history.encode().map_err(|_| StoreError::Corrupt)?
                != progress.staged_history()?
        {
            return Err(StoreError::Conflict);
        }
        let mut batch = crate::session::offline::aggregate_v1_to_v2(view, &current.namespace)?;
        batch.expectations.extend([
            progress.namespace_expectation()?,
            ExpectedRow {
                key: progress.history_key()?,
                value: Some(progress.staged_history()?),
            },
            progress.guard_expectation(),
            ExpectedRow {
                key: key.clone(),
                value: bytes,
            },
        ]);
        progress.finish()?;
        batch.mutations.extend([
            RowMutation {
                key: progress.namespace_expectation()?.key,
                value: Some(
                    progress
                        .result_namespace()?
                        .encode()
                        .map_err(|_| StoreError::Corrupt)?,
                ),
            },
            RowMutation {
                key: progress.history_key()?,
                value: Some(
                    progress
                        .result_history()?
                        .encode()
                        .map_err(|_| StoreError::Corrupt)?,
                ),
            },
            RowMutation {
                key,
                value: Some(progress.encode()?),
            },
        ]);
        Ok(Self {
            batch,
            progress,
            action: MigrationAction::Complete,
        })
    }

    fn replay(
        view: &ReadView,
        current: &NamespaceRecoveryView,
        key: crate::embedded::RowKey,
        bytes: Option<Vec<u8>>,
        progress: AggregateMigrationProgress,
    ) -> Result<Self, StoreError> {
        let ns_key = crate::embedded::RowKey {
            family: crate::embedded::Family::Namespace,
            key: namespace_record_key(&current.namespace.tenant, &current.namespace.id)
                .map_err(|_| StoreError::Corrupt)?,
        };
        let hist_key = history_key(
            &current.namespace.tenant,
            &current.namespace.id,
            current.namespace.version.incarnation,
        )
        .map_err(|_| StoreError::Corrupt)?;
        Ok(Self {
            batch: AtomicBatch {
                expectations: vec![
                    ExpectedRow {
                        value: view.get(&ns_key)?,
                        key: ns_key,
                    },
                    ExpectedRow {
                        value: view.get(&hist_key)?,
                        key: hist_key,
                    },
                    ExpectedRow {
                        key: guard_key(),
                        value: view.get(&guard_key())?,
                    },
                    ExpectedRow { key, value: bytes },
                ],
                mutations: vec![],
            },
            progress,
            action: MigrationAction::Replay,
        })
    }
    #[must_use]
    pub fn action(&self) -> MigrationAction {
        self.action
    }
    #[must_use]
    pub fn progress(&self) -> &AggregateMigrationProgress {
        &self.progress
    }
    /// Use the actual final no-I/O current authority/clock/lifecycle fence.
    #[must_use]
    pub fn into_batch(self) -> AtomicBatch {
        self.batch
    }
}

fn require_source(
    current: &NamespaceRecoveryView,
    request: &AggregateMigrationRequest,
    schema: &ReviewedSchema,
) -> Result<(), StoreError> {
    let (v1, v2) = schema_ids()?;
    if current.namespace.status != NamespaceStatus::Quiescing
        || current.namespace.version.incarnation != request.scope.incarnation
        || current.namespace.state_schema != v1.as_str()
        || current.history.status != HistoryStatus::Ready
        || current.view_token()? != request.expected_view
        || schema.declaration().package_digest != request.package_digest
        || !schema.declaration().readers.contains(&v1)
        || !schema.declaration().readers.contains(&v2)
        || schema.declaration().writers != [v2]
    {
        return Err(StoreError::UnsupportedFormat);
    }
    schema
        .require_namespace(&current.namespace)
        .map_err(|_| StoreError::UnsupportedFormat)
}

#[cfg(test)]
mod tests;
