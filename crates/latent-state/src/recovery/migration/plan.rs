use super::{
    accounting, recipe, AggregateMigrationProgress, AggregateMigrationRecipe,
    AggregateMigrationRequest, MigrationAction, MigrationError, MigrationPhase,
    NamespaceMigrationView, VerifiedMigrationCheckpoint,
};
use crate::{
    embedded::{AtomicBatch, ExpectedRow, ReadView, RowMutation, StoreError},
    namespace::{compatibility::ReviewedSchema, history::HistoryStatus, NamespaceStatus},
};
use std::time::Instant;

pub struct AggregateMigrationObservation<'a> {
    pub current: &'a NamespaceMigrationView,
    pub checkpoint: &'a VerifiedMigrationCheckpoint,
    pub schema: &'a ReviewedSchema,
    pub original_progress: Option<&'a AggregateMigrationProgress>,
}

/// Affine logical plan. It cannot commit independently; only the protected
/// original snapshot worker consumes its exact batch at the current final fence.
pub struct AggregateMigrationPlan {
    batch: AtomicBatch,
    progress: AggregateMigrationProgress,
    action: MigrationAction,
}

impl AggregateMigrationPlan {
    pub fn prepare(
        view: &ReadView,
        request: &AggregateMigrationRequest,
        checkpoint: &VerifiedMigrationCheckpoint,
        schema: &ReviewedSchema,
        selected: (AggregateMigrationRecipe, MigrationPhase),
        deadline: Instant,
        review: impl FnOnce(
            &ReadView,
            &AggregateMigrationRequest,
            AggregateMigrationObservation<'_>,
        ) -> Result<(), StoreError>,
    ) -> Result<Self, MigrationError> {
        let (recipe, phase) = selected;
        request.validate().map_err(MigrationError::Review)?;
        super::super::snapshot::validate_deadline(deadline).map_err(MigrationError::source)?;
        checkpoint
            .require_request(request, recipe)
            .map_err(MigrationError::Review)?;
        let current =
            NamespaceMigrationView::capture(view, &request.scope.tenant, &request.scope.namespace)
                .map_err(MigrationError::source)?;
        if let Some(guard) = &current.guard {
            guard.require_ready().map_err(MigrationError::Review)?;
        }
        let key = request.progress_key().map_err(MigrationError::Review)?;
        let bytes = view
            .get_bounded(&key, super::PROGRESS_BYTES)
            .map_err(MigrationError::source)?;
        let prior = bytes
            .as_deref()
            .map(|bytes| {
                AggregateMigrationProgress::validate_row(&key, bytes)?;
                AggregateMigrationProgress::decode(bytes)
            })
            .transpose()
            .map_err(MigrationError::source)?;
        if let Some(prior) = &prior {
            prior
                .require_request(request, schema, recipe)
                .map_err(MigrationError::Review)?;
            if !prior.completed() {
                require_staged_view(&current, prior).map_err(MigrationError::source)?;
            }
        } else {
            require_source(&current, request, schema).map_err(MigrationError::Review)?;
        }
        if prior.as_ref().is_none_or(|progress| !progress.completed()) {
            checkpoint
                .require_current(view, prior.as_ref().zip(bytes.as_deref()), &key, deadline)
                .map_err(MigrationError::source)?;
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
        )
        .map_err(MigrationError::Review)?;
        let plan = match prior {
            Some(progress) if progress.completed() || phase == MigrationPhase::Stage => {
                Self::replay(view, &current, key, bytes, progress)
            }
            Some(progress) => Self::complete(view, &current, key, bytes, progress),
            None if phase == MigrationPhase::Stage => {
                Self::stage(view, &current, request, schema, recipe)
            }
            None => return Err(MigrationError::Review(StoreError::Unavailable)),
        }
        .map_err(MigrationError::source)?;
        super::super::snapshot::checkpoint(deadline).map_err(MigrationError::source)?;
        Ok(plan)
    }

    fn stage(
        view: &ReadView,
        current: &NamespaceMigrationView,
        request: &AggregateMigrationRequest,
        schema: &ReviewedSchema,
        recipe: AggregateMigrationRecipe,
    ) -> Result<Self, StoreError> {
        let mut progress = AggregateMigrationProgress::new(view, current, request, schema, recipe)?;
        // Refuse the actual fixed data, final namespace/state quota, schema epoch
        // overflow and aggregate tenant contribution BEFORE publishing a marker.
        dry_complete(view, current, &progress)?;
        let key = request.progress_key()?;
        let placeholder = progress.encode()?;
        let mut batch = stage_batch(current, &key, &progress, &placeholder)?;
        accounting::append(
            view,
            &current.namespace.tenant,
            &key,
            None,
            &placeholder,
            &mut batch,
        )?;
        let quota = accounting::candidate_quota(&batch, &current.namespace.tenant)?;
        progress.set_staged_quota(quota.clone())?;
        let encoded = progress.encode()?;
        if encoded.len() != placeholder.len() {
            return Err(StoreError::Corrupt);
        }
        let mut final_batch = stage_batch(current, &key, &progress, &encoded)?;
        accounting::append(
            view,
            &current.namespace.tenant,
            &key,
            None,
            &encoded,
            &mut final_batch,
        )?;
        if accounting::candidate_quota(&final_batch, &current.namespace.tenant)? != quota {
            return Err(StoreError::Corrupt);
        }
        Ok(Self {
            batch: final_batch,
            progress,
            action: MigrationAction::Stage,
        })
    }

    fn complete(
        view: &ReadView,
        current: &NamespaceMigrationView,
        key: crate::embedded::RowKey,
        bytes: Option<Vec<u8>>,
        mut progress: AggregateMigrationProgress,
    ) -> Result<Self, StoreError> {
        require_staged_view(current, &progress)?;
        let mut batch = crate::session::migration::aggregate_v1_to_v2(
            view,
            &current.namespace,
            progress.recipe()?,
        )?;
        let original = bytes.as_deref().ok_or(StoreError::Corrupt)?;
        batch.expectations.extend([
            current.namespace_expectation.clone(),
            current.history_expectation.clone(),
            current.guard_expectation.clone(),
            ExpectedRow {
                key: key.clone(),
                value: bytes.clone(),
            },
        ]);
        progress.finish()?;
        let encoded = progress.encode()?;
        batch.mutations.extend([
            RowMutation {
                key: current.namespace_expectation.key.clone(),
                value: Some(
                    progress
                        .result_namespace()?
                        .encode()
                        .map_err(|_| StoreError::Corrupt)?,
                ),
            },
            RowMutation {
                key: current.history_expectation.key.clone(),
                value: Some(
                    progress
                        .result_history()?
                        .encode()
                        .map_err(|_| StoreError::Corrupt)?,
                ),
            },
            RowMutation {
                key: key.clone(),
                value: Some(encoded.clone()),
            },
        ]);
        accounting::append(
            view,
            &current.namespace.tenant,
            &key,
            Some(original),
            &encoded,
            &mut batch,
        )?;
        Ok(Self {
            batch,
            progress,
            action: MigrationAction::Complete,
        })
    }

    fn replay(
        view: &ReadView,
        current: &NamespaceMigrationView,
        key: crate::embedded::RowKey,
        bytes: Option<Vec<u8>>,
        progress: AggregateMigrationProgress,
    ) -> Result<Self, StoreError> {
        let mut batch = AtomicBatch {
            expectations: vec![
                current.namespace_expectation.clone(),
                current.history_expectation.clone(),
                current.guard_expectation.clone(),
                ExpectedRow { key, value: bytes },
            ],
            mutations: vec![],
        };
        crate::tenant::prepare_update(
            view,
            &current.namespace.tenant,
            crate::tenant::TenantDelta::default(),
        )?
        .append_read_expectations(&mut batch)?;
        Ok(Self {
            batch,
            progress,
            action: MigrationAction::Replay,
        })
    }

    #[must_use]
    pub const fn action(&self) -> MigrationAction {
        self.action
    }

    #[must_use]
    pub fn progress(&self) -> &AggregateMigrationProgress {
        &self.progress
    }

    pub(crate) fn into_parts(self) -> (AtomicBatch, AggregateMigrationProgress, MigrationAction) {
        (self.batch, self.progress, self.action)
    }
}

fn stage_batch(
    current: &NamespaceMigrationView,
    key: &crate::embedded::RowKey,
    progress: &AggregateMigrationProgress,
    bytes: &[u8],
) -> Result<AtomicBatch, StoreError> {
    Ok(AtomicBatch {
        expectations: vec![
            current.namespace_expectation.clone(),
            current.history_expectation.clone(),
            current.guard_expectation.clone(),
            ExpectedRow {
                key: key.clone(),
                value: None,
            },
        ],
        mutations: vec![
            RowMutation {
                key: current.history_expectation.key.clone(),
                value: Some(progress.staged_history()?),
            },
            RowMutation {
                key: key.clone(),
                value: Some(bytes.to_vec()),
            },
        ],
    })
}

fn dry_complete(
    view: &ReadView,
    current: &NamespaceMigrationView,
    progress: &AggregateMigrationProgress,
) -> Result<(), StoreError> {
    if let Some(bytes) = progress.quota_expectation(false)?.value {
        crate::tenant::TenantRecord::decode(&bytes)?
            .generation
            .checked_add(2)
            .ok_or(StoreError::Capacity)?;
    }
    let mut completed = progress.clone();
    completed.finish()?;
    let key = completed.row_key()?;
    let encoded = completed.encode()?;
    let mut batch = crate::session::migration::aggregate_v1_to_v2(
        view,
        &current.namespace,
        completed.recipe()?,
    )?;
    batch.expectations.extend([
        current.namespace_expectation.clone(),
        current.history_expectation.clone(),
        ExpectedRow {
            key: key.clone(),
            value: None,
        },
    ]);
    batch.mutations.extend([
        RowMutation {
            key: current.namespace_expectation.key.clone(),
            value: Some(
                completed
                    .result_namespace()?
                    .encode()
                    .map_err(|_| StoreError::Corrupt)?,
            ),
        },
        RowMutation {
            key: current.history_expectation.key.clone(),
            value: Some(
                completed
                    .result_history()?
                    .encode()
                    .map_err(|_| StoreError::Corrupt)?,
            ),
        },
        RowMutation {
            key: key.clone(),
            value: Some(encoded.clone()),
        },
    ]);
    accounting::append(
        view,
        &current.namespace.tenant,
        &key,
        None,
        &encoded,
        &mut batch,
    )
}

fn require_source(
    current: &NamespaceMigrationView,
    request: &AggregateMigrationRequest,
    schema: &ReviewedSchema,
) -> Result<(), StoreError> {
    let (v1, v2) = recipe::schema_ids()?;
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

fn require_staged_view(
    current: &NamespaceMigrationView,
    progress: &AggregateMigrationProgress,
) -> Result<(), StoreError> {
    if current.namespace != progress.source_namespace()?
        || current.history.encode().map_err(|_| StoreError::Corrupt)?
            != progress.staged_history()?
        || current.guard_expectation.value != progress.guard_expectation().value
    {
        return Err(StoreError::Conflict);
    }
    Ok(())
}
