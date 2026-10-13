use super::{
    RestoredMigrationResumeReceipt, RestoredMigrationResumeRequest, StoreError, RECEIPT_BYTES,
};
use crate::{
    embedded::{AtomicBatch, ExpectedRow, Family, ReadView, RowKey, RowMutation},
    namespace::{
        compatibility::ReviewedSchema,
        history::{history_key, HistoryStatus},
        namespace_record_key, NamespaceStatus,
    },
    recovery::{
        guard_key,
        migration::{AggregateMigrationProgress, AggregateMigrationRecipe},
        namespace_resume::{NamespaceRecoveryView, NamespaceResumeReceipt},
        snapshot::SnapshotReceipt,
    },
};
use sha2::{Digest, Sha256};

pub struct RestoredMigrationResumeObservation<'a> {
    pub current: &'a NamespaceRecoveryView,
    pub snapshot: &'a SnapshotReceipt,
    pub progress: &'a AggregateMigrationProgress,
    pub schema: &'a ReviewedSchema,
    pub original_receipt: Option<&'a RestoredMigrationResumeReceipt>,
}
pub struct RestoredMigrationResumePlan {
    batch: AtomicBatch,
    receipt: RestoredMigrationResumeReceipt,
    replayed: bool,
}
impl RestoredMigrationResumePlan {
    /// `snapshot` and its exact progress digest must come from the same fully
    /// verified protected input. Neither argument is an activation grant.
    #[expect(
        clippy::too_many_lines,
        reason = "Exact original guard/source/progress/review and the single CAS accounting batch remain one visible plan"
    )]
    pub fn prepare(
        view: &ReadView,
        request: &RestoredMigrationResumeRequest,
        snapshot: &SnapshotReceipt,
        source_progress_digest: [u8; 32],
        schema: &ReviewedSchema,
        review: impl FnOnce(
            &ReadView,
            &RestoredMigrationResumeRequest,
            RestoredMigrationResumeObservation<'_>,
        ) -> Result<(), StoreError>,
    ) -> Result<Self, StoreError> {
        request.validate()?;
        super::validate_snapshot(request, snapshot)?;
        let current =
            NamespaceRecoveryView::capture(view, &request.scope.tenant, &request.scope.namespace)?;
        let guard = current.guard.as_ref().ok_or(StoreError::Unavailable)?;
        guard.require_ready()?;
        if guard.snapshot_digest() != request.snapshot_digest
            || guard.operation_digest() != request.restore_operation_digest
            || guard.window_digest() != request.window_digest
            || guard.review_digest() != request.review_digest
            || current.scope() != request.scope
        {
            return Err(StoreError::Conflict);
        }
        let (original_namespace, original_history) = snapshot.manifest.namespaces[0].decode()?;
        if original_namespace.tenant != request.scope.tenant
            || original_namespace.id != request.scope.namespace
            || original_namespace.version.incarnation != request.scope.incarnation
            || original_namespace.state_schema != request.scope.state_schema
            || original_namespace.status != NamespaceStatus::Quiescing
            || current.history.state_schema != original_history.state_schema
            || current.history.epochs.schema != original_history.epochs.schema
            || current.history.epochs.recovery <= original_history.epochs.recovery
        {
            return Err(StoreError::Conflict);
        }
        schema
            .require_namespace(&original_namespace)
            .map_err(|_| StoreError::UnsupportedFormat)?;
        let mut prefix = crate::recovery::migration::PROGRESS_PREFIX.to_vec();
        prefix.extend_from_slice(
            &namespace_record_key(&request.scope.tenant, &request.scope.namespace)
                .map_err(|_| StoreError::Invalid)?,
        );
        prefix.extend_from_slice(&request.scope.incarnation.to_le_bytes());
        let rows = view.scan(
            Family::Maintenance,
            &prefix,
            2,
            2 * crate::recovery::migration::PROGRESS_BYTES,
        )?;
        if rows.len() != 1 {
            return Err(StoreError::UnsupportedFormat);
        }
        let (progress_key, progress_bytes) = &rows[0];
        AggregateMigrationProgress::validate_row(progress_key, progress_bytes)?;
        let progress = AggregateMigrationProgress::decode(progress_bytes)?;
        let progress_digest: [u8; 32] = Sha256::digest(progress_bytes).into();
        if progress_digest != source_progress_digest
            || source_progress_digest == [0; 32]
            || !progress.completed()
            || progress.operation_id() != request.migration_operation_id
            || progress.operator_id() != request.operator_id
            || progress.package_digest() != schema.declaration().package_digest
            || progress.recipe()? != AggregateMigrationRecipe::JavaAggregate
        {
            return Err(StoreError::UnsupportedFormat);
        }
        let migrated = progress.result_namespace()?;
        let migrated_history = progress.result_history()?;
        if migrated.tenant != original_namespace.tenant
            || migrated.id != original_namespace.id
            || migrated.version.incarnation != original_namespace.version.incarnation
            || migrated.version.generation > original_namespace.version.generation
            || migrated.state_schema != original_namespace.state_schema
            || migrated_history.epochs.schema != original_history.epochs.schema
        {
            return Err(StoreError::UnsupportedFormat);
        }
        let receipt_key = request.receipt_key()?;
        let prior_bytes = view.get_bounded(&receipt_key, RECEIPT_BYTES)?;
        let prior = prior_bytes
            .as_deref()
            .map(RestoredMigrationResumeReceipt::decode)
            .transpose()?;
        if let Some(bytes) = &prior_bytes {
            RestoredMigrationResumeReceipt::validate_row(&receipt_key, bytes)?;
        }
        let fingerprint = request.fingerprint(progress_digest)?;
        if let Some(prior) = &prior {
            if prior.fingerprint != fingerprint {
                return Err(StoreError::Conflict);
            }
        } else if current.namespace != original_namespace
            || current.namespace.status != NamespaceStatus::Quiescing
            || current.history.status != HistoryStatus::ReconciliationRequired
            || current.view_token() != Ok(request.expected_view.clone())
        {
            return Err(StoreError::Conflict);
        }
        review(
            view,
            request,
            RestoredMigrationResumeObservation {
                current: &current,
                snapshot,
                progress: &progress,
                schema,
                original_receipt: prior.as_ref(),
            },
        )?;
        let namespace_key = RowKey {
            family: Family::Namespace,
            key: namespace_record_key(&request.scope.tenant, &request.scope.namespace)
                .map_err(|_| StoreError::Invalid)?,
        };
        let history_key = history_key(
            &request.scope.tenant,
            &request.scope.namespace,
            request.scope.incarnation,
        )
        .map_err(|_| StoreError::Corrupt)?;
        let mut batch = AtomicBatch {
            expectations: vec![
                ExpectedRow {
                    value: view.get(&namespace_key)?,
                    key: namespace_key.clone(),
                },
                ExpectedRow {
                    value: view.get(&history_key)?,
                    key: history_key.clone(),
                },
                ExpectedRow {
                    value: view.get(&guard_key())?,
                    key: guard_key(),
                },
                ExpectedRow {
                    value: Some(progress_bytes.clone()),
                    key: progress_key.clone(),
                },
                ExpectedRow {
                    value: prior_bytes,
                    key: receipt_key.clone(),
                },
            ],
            mutations: vec![],
        };
        let replayed = prior.is_some();
        let receipt = if let Some(prior) = prior {
            prior
        } else {
            let key_digest = receipt_key.key[super::RECEIPT_PREFIX.len()..]
                .try_into()
                .map_err(|_| StoreError::Corrupt)?;
            let outcome = NamespaceResumeReceipt::activated(
                current.namespace,
                current.history,
                key_digest,
                fingerprint,
            )?;
            RestoredMigrationResumeReceipt {
                key_digest,
                fingerprint,
                operator_id: request.operator_id.clone(),
                operation_id: request.operation_id.clone(),
                migration_operation_id: request.migration_operation_id.clone(),
                snapshot_digest: request.snapshot_digest,
                manifest_digest: request.manifest_digest,
                restore_operation_digest: request.restore_operation_digest,
                window_digest: request.window_digest,
                review_digest: request.review_digest,
                progress_digest,
                outcome,
            }
        };
        if replayed {
            crate::tenant::prepare_update(
                view,
                &request.scope.tenant,
                crate::tenant::TenantDelta::default(),
            )?
            .append_read_expectations(&mut batch)?;
        } else {
            batch.mutations = vec![
                RowMutation {
                    key: namespace_key,
                    value: Some(
                        receipt
                            .namespace()
                            .encode()
                            .map_err(|_| StoreError::Corrupt)?,
                    ),
                },
                RowMutation {
                    key: history_key,
                    value: Some(
                        receipt
                            .history()
                            .encode()
                            .map_err(|_| StoreError::Corrupt)?,
                    ),
                },
                RowMutation {
                    key: receipt_key,
                    value: Some(receipt.encode()?),
                },
            ];
            let mut delta = crate::tenant::TenantDelta::default();
            for row in &batch.mutations {
                if let Some(old) = view.get(&row.key)? {
                    delta.removed.metadata_rows += 1;
                    delta.removed.metadata_bytes += crate::tenant::row_charge(&row.key, &old)?;
                }
                if let Some(bytes) = &row.value {
                    delta.added.metadata_rows += 1;
                    delta.added.metadata_bytes += crate::tenant::row_charge(&row.key, bytes)?;
                }
            }
            crate::tenant::prepare_update(view, &request.scope.tenant, delta)?
                .append_to(&mut batch)?;
        }
        Ok(Self {
            batch,
            receipt,
            replayed,
        })
    }
    #[must_use]
    pub fn receipt(&self) -> &RestoredMigrationResumeReceipt {
        &self.receipt
    }
    #[must_use]
    pub fn replayed(&self) -> bool {
        self.replayed
    }
    #[must_use]
    pub fn into_batch(self) -> AtomicBatch {
        self.batch
    }
}
