use super::{MigrationResumeAction, MigrationResumeReceipt, MigrationResumeRequest, RECEIPT_BYTES};
use crate::{
    embedded::{AtomicBatch, ExpectedRow, ReadView, RowMutation, StoreError},
    namespace::{
        compatibility::{require_composition, ReviewedSchema},
        history::{history_key, HistoryStatus},
        namespace_record_key, NamespaceStatus,
    },
    recovery::{
        guard_key,
        migration::{AggregateMigrationProgress, MigrationError, NamespaceMigrationView},
    },
    tenant::{TenantDelta, TenantUsage},
};
use sha2::{Digest, Sha256};
use std::time::Instant;

pub struct MigrationResumeObservation<'a> {
    pub current: &'a NamespaceMigrationView,
    pub progress: &'a AggregateMigrationProgress,
    pub schema: &'a ReviewedSchema,
    pub original_receipt: Option<&'a MigrationResumeReceipt>,
}

/// Affine exact logical batch. Production cannot extract it: only the original
/// protected snapshot worker consumes its bytes at the actual final fence.
pub struct MigrationResumePlan {
    batch: AtomicBatch,
    receipt: MigrationResumeReceipt,
    action: MigrationResumeAction,
}

struct ResumeKeys {
    namespace: crate::embedded::RowKey,
    history: crate::embedded::RowKey,
    receipt: crate::embedded::RowKey,
}

impl MigrationResumePlan {
    pub fn prepare(
        view: &ReadView,
        request: &MigrationResumeRequest,
        schema: &ReviewedSchema,
        deadline: Instant,
        review: impl FnOnce(
            &ReadView,
            &MigrationResumeRequest,
            MigrationResumeObservation<'_>,
        ) -> Result<(), StoreError>,
    ) -> Result<Self, MigrationError> {
        request.validate().map_err(MigrationError::Review)?;
        super::super::snapshot::validate_deadline(deadline).map_err(MigrationError::source)?;
        let current =
            NamespaceMigrationView::capture(view, &request.scope.tenant, &request.scope.namespace)
                .map_err(MigrationError::source)?;
        let key = request.receipt_key().map_err(MigrationError::Review)?;
        let original = view
            .get_bounded(&key, RECEIPT_BYTES)
            .map_err(MigrationError::source)?;
        let progress_key = request
            .migration
            .progress_key()
            .map_err(MigrationError::Review)?;
        let progress_bytes = view
            .get_bounded(&progress_key, super::super::migration::PROGRESS_BYTES)
            .map_err(MigrationError::source)?
            .ok_or_else(|| {
                if original.is_some() {
                    MigrationError::Source(StoreError::Corrupt)
                } else {
                    MigrationError::Review(StoreError::Conflict)
                }
            })?;
        AggregateMigrationProgress::validate_row(&progress_key, &progress_bytes)
            .map_err(MigrationError::source)?;
        let progress =
            AggregateMigrationProgress::decode(&progress_bytes).map_err(MigrationError::source)?;
        progress
            .require_input(&request.migration)
            .map_err(MigrationError::Review)?;
        let prior = original
            .as_deref()
            .map(|bytes| {
                MigrationResumeReceipt::validate_row(&key, bytes)?;
                super::census_contribution(view, &key, bytes)?;
                MigrationResumeReceipt::decode(bytes)
            })
            .transpose()
            .map_err(MigrationError::source)?;
        require_observation(view, request, schema, &current, &progress, prior.as_ref())?;
        review(
            view,
            request,
            MigrationResumeObservation {
                current: &current,
                progress: &progress,
                schema,
                original_receipt: prior.as_ref(),
            },
        )
        .map_err(MigrationError::Review)?;
        super::super::snapshot::validate_deadline(deadline).map_err(MigrationError::source)?;
        let (namespace_key, history_key) = row_keys(&current, request)?;
        let batch = AtomicBatch {
            expectations: vec![
                ExpectedRow {
                    value: view.get(&namespace_key).map_err(MigrationError::source)?,
                    key: namespace_key.clone(),
                },
                ExpectedRow {
                    value: view.get(&history_key).map_err(MigrationError::source)?,
                    key: history_key.clone(),
                },
                ExpectedRow {
                    key: guard_key(),
                    value: view.get(&guard_key()).map_err(MigrationError::source)?,
                },
                ExpectedRow {
                    key: progress_key,
                    value: Some(progress_bytes.clone()),
                },
                ExpectedRow {
                    key: key.clone(),
                    value: original,
                },
            ],
            mutations: vec![],
        };
        Self::finish(
            view,
            request,
            current,
            &progress_bytes,
            prior,
            ResumeKeys {
                namespace: namespace_key,
                history: history_key,
                receipt: key,
            },
            batch,
        )
    }

    fn finish(
        view: &ReadView,
        request: &MigrationResumeRequest,
        current: NamespaceMigrationView,
        progress_bytes: &[u8],
        prior: Option<MigrationResumeReceipt>,
        keys: ResumeKeys,
        mut batch: AtomicBatch,
    ) -> Result<Self, MigrationError> {
        let (receipt, action) = if let Some(receipt) = prior {
            crate::tenant::prepare_update(view, &request.scope.tenant, TenantDelta::default())
                .and_then(|accounting| accounting.append_read_expectations(&mut batch))
                .map_err(MigrationError::source)?;
            (receipt, MigrationResumeAction::Replay)
        } else {
            let receipt = MigrationResumeReceipt {
                request: request.clone(),
                progress_digest: Sha256::digest(progress_bytes).into(),
                before: current.namespace,
                history_before: current.history,
            };
            let encoded = receipt.encode().map_err(MigrationError::source)?;
            batch.mutations = vec![
                RowMutation {
                    key: keys.namespace,
                    value: Some(
                        receipt
                            .namespace()
                            .and_then(|namespace| {
                                namespace.encode().map_err(|_| StoreError::Corrupt)
                            })
                            .map_err(MigrationError::source)?,
                    ),
                },
                RowMutation {
                    key: keys.history,
                    value: Some(
                        receipt
                            .history()
                            .and_then(|history| history.encode().map_err(|_| StoreError::Corrupt))
                            .map_err(MigrationError::source)?,
                    ),
                },
                RowMutation {
                    key: keys.receipt.clone(),
                    value: Some(encoded.clone()),
                },
            ];
            crate::tenant::prepare_update(
                view,
                &request.scope.tenant,
                TenantDelta {
                    added: TenantUsage {
                        metadata_rows: 1,
                        metadata_bytes: crate::tenant::row_charge(&keys.receipt, &encoded)
                            .map_err(MigrationError::source)?,
                        ..TenantUsage::default()
                    },
                    ..TenantDelta::default()
                },
            )
            .and_then(|accounting| accounting.rebuild_batch(&mut batch))
            .map_err(MigrationError::source)?;
            (receipt, MigrationResumeAction::Activate)
        };
        Ok(Self {
            batch,
            receipt,
            action,
        })
    }

    #[must_use]
    pub const fn action(&self) -> MigrationResumeAction {
        self.action
    }

    #[must_use]
    pub fn receipt(&self) -> &MigrationResumeReceipt {
        &self.receipt
    }

    pub(crate) fn into_parts(self) -> (AtomicBatch, MigrationResumeReceipt, MigrationResumeAction) {
        (self.batch, self.receipt, self.action)
    }
}

fn row_keys(
    current: &NamespaceMigrationView,
    request: &MigrationResumeRequest,
) -> Result<(crate::embedded::RowKey, crate::embedded::RowKey), MigrationError> {
    let namespace_key = crate::embedded::RowKey {
        family: crate::embedded::Family::Namespace,
        key: namespace_record_key(&request.scope.tenant, &request.scope.namespace)
            .map_err(|_| MigrationError::Review(StoreError::Invalid))?,
    };
    let history_key = history_key(
        &current.namespace.tenant,
        &current.namespace.id,
        current.namespace.version.incarnation,
    )
    .map_err(|_| MigrationError::Source(StoreError::Corrupt))?;
    Ok((namespace_key, history_key))
}

fn require_observation(
    view: &ReadView,
    request: &MigrationResumeRequest,
    schema: &ReviewedSchema,
    current: &NamespaceMigrationView,
    progress: &AggregateMigrationProgress,
    prior: Option<&MigrationResumeReceipt>,
) -> Result<(), MigrationError> {
    if let Some(prior) = prior {
        if prior
            .request
            .fingerprint()
            .map_err(MigrationError::source)?
            != request.fingerprint().map_err(MigrationError::Review)?
        {
            return Err(MigrationError::Review(StoreError::Conflict));
        }
    } else {
        super::super::require_ready(view).map_err(MigrationError::Review)?;
        super::super::migration::require_no_incomplete(view, &current.namespace)
            .map_err(MigrationError::Review)?;
        progress
            .require_request(
                &request.migration,
                schema,
                progress.recipe().map_err(MigrationError::source)?,
            )
            .map_err(MigrationError::Review)?;
        if !progress.completed()
            || current.namespace
                != progress
                    .result_namespace()
                    .map_err(MigrationError::source)?
            || current.history != progress.result_history().map_err(MigrationError::source)?
            || current.scope() != request.scope
            || current.namespace.status != NamespaceStatus::Quiescing
            || current.history.status != HistoryStatus::ReconciliationRequired
            || current.view_token().map_err(MigrationError::source)? != request.expected_view
        {
            return Err(MigrationError::Review(StoreError::Conflict));
        }
        require_composition(&current.namespace, std::slice::from_ref(schema))
            .map_err(|_| MigrationError::Review(StoreError::UnsupportedFormat))?;
    }
    Ok(())
}
