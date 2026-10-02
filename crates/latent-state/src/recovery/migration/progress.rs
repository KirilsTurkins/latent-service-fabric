use super::{
    operation_key, recipe, AggregateMigrationRecipe, AggregateMigrationRequest,
    NamespaceMigrationView,
};
use crate::{
    embedded::{ExpectedRow, ReadView, RowKey, StoreError},
    namespace::{
        compatibility::ReviewedSchema,
        history::{history_key, HistoryStatus, NamespaceHistory},
        namespace_record_key, NamespaceRecord, NamespaceStatus,
    },
    session::{version::ViewIdentity, StateMode, StateScope},
    tenant::TenantRecord,
};

mod codec;

/// Durable exact operation history. Its private constructor captures original
/// rows; decoding provides descriptive evidence, never current permission.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AggregateMigrationProgress {
    operation_id: String,
    operator_id: String,
    fingerprint: [u8; 32],
    checkpoint_digest: [u8; 32],
    checkpoint_manifest_digest: [u8; 32],
    package_digest: [u8; 32],
    review_digest: [u8; 32],
    declaration_digest: [u8; 32],
    schema_proof_digest: [u8; 32],
    recipe_digest: [u8; 32],
    namespace_row: Vec<u8>,
    history_row: Option<Vec<u8>>,
    guard_row: Option<Vec<u8>>,
    source_quota: Option<Vec<u8>>,
    staged_quota: Option<Vec<u8>>,
    completed: bool,
}

impl AggregateMigrationProgress {
    pub(super) fn new(
        view: &ReadView,
        current: &NamespaceMigrationView,
        request: &AggregateMigrationRequest,
        schema: &ReviewedSchema,
        recipe: AggregateMigrationRecipe,
    ) -> Result<Self, StoreError> {
        // Capture through the original guard/quota codec before retaining bytes.
        let quota = crate::tenant::inspect(view, &current.namespace.tenant)?;
        let source_quota = view.get_bounded(
            &crate::tenant::quota_key(&current.namespace.tenant)?,
            crate::tenant::RECORD_BYTES,
        )?;
        // The canonical quota codec is fixed-size. A valid sizing placeholder
        // lets the SAME accounting owner calculate its exact final Stage row
        // without a circular byte charge or independent counter arithmetic.
        let staged_quota = quota
            .map(|mut quota| {
                quota.generation = quota
                    .generation
                    .checked_add(1)
                    .ok_or(StoreError::Capacity)?;
                quota.encode()
            })
            .transpose()?;
        let progress = Self {
            operation_id: request.operation_id.clone(),
            operator_id: request.operator_id.clone(),
            fingerprint: request.fingerprint(recipe)?,
            checkpoint_digest: request.checkpoint_digest,
            checkpoint_manifest_digest: request.checkpoint_manifest_digest,
            package_digest: request.package_digest,
            review_digest: request.review_digest,
            declaration_digest: schema.declaration_digest(),
            schema_proof_digest: schema.proof_digest(),
            recipe_digest: recipe.digest(),
            namespace_row: current
                .namespace_expectation
                .value
                .clone()
                .ok_or(StoreError::Corrupt)?,
            history_row: current.history_expectation.value.clone(),
            guard_row: current.guard_expectation.value.clone(),
            source_quota,
            staged_quota,
            completed: false,
        };
        progress.validate()?;
        Ok(progress)
    }

    #[must_use]
    pub const fn completed(&self) -> bool {
        self.completed
    }

    #[must_use]
    pub fn operation_id(&self) -> &str {
        &self.operation_id
    }

    #[must_use]
    pub fn operator_id(&self) -> &str {
        &self.operator_id
    }

    #[must_use]
    pub const fn checkpoint_digest(&self) -> [u8; 32] {
        self.checkpoint_digest
    }

    #[must_use]
    pub const fn checkpoint_manifest_digest(&self) -> [u8; 32] {
        self.checkpoint_manifest_digest
    }

    #[must_use]
    pub const fn package_digest(&self) -> [u8; 32] {
        self.package_digest
    }

    /// Every original schema/recipe/package association remains required by a
    /// backup or upgrade even after the business cell has changed to v2.
    pub fn required_artifacts(
        &self,
    ) -> Result<Vec<crate::recovery::snapshot::RequiredArtifact>, StoreError> {
        use crate::recovery::snapshot::RequiredArtifact;
        let (v1, v2) = recipe::schema_ids()?;
        let selected = self.recipe()?;
        Ok(vec![
            RequiredArtifact {
                identity: v1.as_str().into(),
                digest: recipe::schema_definitions()[0].1,
            },
            RequiredArtifact {
                identity: v2.as_str().into(),
                digest: recipe::schema_definitions()[1].1,
            },
            RequiredArtifact {
                identity: selected.identity().into(),
                digest: selected.digest(),
            },
            RequiredArtifact {
                identity: super::checkpoint::package_identity(&self.package_digest),
                digest: self.package_digest,
            },
        ])
    }

    pub fn recipe(&self) -> Result<AggregateMigrationRecipe, StoreError> {
        AggregateMigrationRecipe::from_digest(self.recipe_digest)
    }

    pub fn source_namespace(&self) -> Result<NamespaceRecord, StoreError> {
        NamespaceRecord::decode(&self.namespace_row).map_err(|_| StoreError::Corrupt)
    }

    pub(super) fn source_history(&self) -> Result<NamespaceHistory, StoreError> {
        let namespace = self.source_namespace()?;
        let history = self
            .history_row
            .as_deref()
            .map(NamespaceHistory::decode)
            .transpose()
            .map_err(|_| StoreError::Corrupt)?
            .unwrap_or_else(|| NamespaceHistory::initial(&namespace));
        history
            .check_namespace(&namespace)
            .map_err(|_| StoreError::Corrupt)?;
        Ok(history)
    }

    pub fn result_namespace(&self) -> Result<NamespaceRecord, StoreError> {
        if !self.completed {
            return Err(StoreError::Unavailable);
        }
        let mut namespace = self.source_namespace()?;
        namespace.version.generation = namespace
            .version
            .generation
            .checked_add(1)
            .ok_or(StoreError::Capacity)?;
        namespace.state_schema = recipe::schema_ids()?.1.as_str().into();
        Ok(namespace)
    }

    pub fn result_history(&self) -> Result<NamespaceHistory, StoreError> {
        if !self.completed {
            return Err(StoreError::Unavailable);
        }
        let mut history = self.source_history()?;
        history.state_schema = recipe::schema_ids()?.1.as_str().into();
        history.epochs.schema = history
            .epochs
            .schema
            .checked_add(1)
            .ok_or(StoreError::Capacity)?;
        history.status = HistoryStatus::ReconciliationRequired;
        Ok(history)
    }

    pub fn result_view_token(&self) -> Result<Vec<u8>, StoreError> {
        let namespace = self.result_namespace()?;
        ViewIdentity {
            namespace: namespace.version,
            epochs: self.result_history()?.epochs,
        }
        .token(&scope(&namespace))
        .map_err(|_| StoreError::Corrupt)
    }

    pub fn encode(&self) -> Result<Vec<u8>, StoreError> {
        self.validate()?;
        codec::encode(self)
    }

    pub fn decode(bytes: &[u8]) -> Result<Self, StoreError> {
        let progress = codec::decode(bytes)?;
        progress.validate()?;
        if progress.encode()? != bytes {
            return Err(StoreError::Corrupt);
        }
        Ok(progress)
    }

    pub fn validate_row(key: &RowKey, bytes: &[u8]) -> Result<(), StoreError> {
        if key.family != crate::embedded::Family::Maintenance
            || !key.key.starts_with(super::PROGRESS_PREFIX)
        {
            return Err(StoreError::UnsupportedFormat);
        }
        let progress = Self::decode(bytes)?;
        if progress.row_key()? != *key {
            return Err(StoreError::Corrupt);
        }
        Ok(())
    }

    pub(super) fn row_key(&self) -> Result<RowKey, StoreError> {
        operation_key(
            &scope(&self.source_namespace()?),
            &self.operator_id,
            &self.operation_id,
        )
    }

    pub(super) fn namespace_expectation(&self) -> Result<ExpectedRow, StoreError> {
        let namespace = self.source_namespace()?;
        Ok(ExpectedRow {
            key: RowKey {
                family: crate::embedded::Family::Namespace,
                key: namespace_record_key(&namespace.tenant, &namespace.id)
                    .map_err(|_| StoreError::Corrupt)?,
            },
            value: Some(self.namespace_row.clone()),
        })
    }

    pub(super) fn history_expectation(&self) -> Result<ExpectedRow, StoreError> {
        let namespace = self.source_namespace()?;
        Ok(ExpectedRow {
            key: history_key(
                &namespace.tenant,
                &namespace.id,
                namespace.version.incarnation,
            )
            .map_err(|_| StoreError::Corrupt)?,
            value: self.history_row.clone(),
        })
    }

    pub(super) fn guard_expectation(&self) -> ExpectedRow {
        ExpectedRow {
            key: super::super::guard_key(),
            value: self.guard_row.clone(),
        }
    }

    pub(super) fn quota_expectation(&self, staged: bool) -> Result<ExpectedRow, StoreError> {
        Ok(ExpectedRow {
            key: crate::tenant::quota_key(&self.source_namespace()?.tenant)?,
            value: if staged {
                self.staged_quota.clone()
            } else {
                self.source_quota.clone()
            },
        })
    }

    pub(super) fn staged_history(&self) -> Result<Vec<u8>, StoreError> {
        let mut history = self.source_history()?;
        history.status = HistoryStatus::ReconciliationRequired;
        history.encode().map_err(|_| StoreError::Corrupt)
    }

    pub(super) fn set_staged_quota(&mut self, bytes: Option<Vec<u8>>) -> Result<(), StoreError> {
        self.staged_quota = bytes;
        self.validate()
    }

    pub(super) fn finish(&mut self) -> Result<(), StoreError> {
        if self.completed {
            return Err(StoreError::Conflict);
        }
        self.completed = true;
        self.validate()
    }

    pub(crate) fn require_request(
        &self,
        request: &AggregateMigrationRequest,
        schema: &ReviewedSchema,
        recipe: AggregateMigrationRecipe,
    ) -> Result<(), StoreError> {
        self.require_input(request)?;
        if self.recipe()? != recipe
            || self.package_digest != schema.declaration().package_digest
            || self.declaration_digest != schema.declaration_digest()
            || self.schema_proof_digest != schema.proof_digest()
        {
            return Err(StoreError::Conflict);
        }
        Ok(())
    }

    /// Original descriptive input equality for linked recovery receipt codecs.
    /// This supplies no schema review, current permission or execution grant.
    pub(crate) fn require_input(
        &self,
        request: &AggregateMigrationRequest,
    ) -> Result<(), StoreError> {
        self.validate()?;
        if self.fingerprint != request.fingerprint(self.recipe()?)? {
            return Err(StoreError::Conflict);
        }
        Ok(())
    }

    fn original_request(&self) -> Result<AggregateMigrationRequest, StoreError> {
        let namespace = self.source_namespace()?;
        Ok(AggregateMigrationRequest {
            scope: scope(&namespace),
            operation_id: self.operation_id.clone(),
            operator_id: self.operator_id.clone(),
            expected_view: ViewIdentity {
                namespace: namespace.version,
                epochs: self.source_history()?.epochs,
            }
            .token(&scope(&namespace))
            .map_err(|_| StoreError::Corrupt)?,
            checkpoint_digest: self.checkpoint_digest,
            checkpoint_manifest_digest: self.checkpoint_manifest_digest,
            package_digest: self.package_digest,
            review_digest: self.review_digest,
        })
    }

    fn validate(&self) -> Result<(), StoreError> {
        let request = self.original_request()?;
        if self.fingerprint != request.fingerprint(self.recipe()?)?
            || [self.declaration_digest, self.schema_proof_digest].contains(&[0; 32])
        {
            return Err(StoreError::Corrupt);
        }
        let namespace = self.source_namespace()?;
        if namespace.status != NamespaceStatus::Quiescing
            || namespace.state_schema != recipe::schema_ids()?.0.as_str()
            || self.source_history()?.status != HistoryStatus::Ready
        {
            return Err(StoreError::Corrupt);
        }
        if let Some(bytes) = &self.guard_row {
            super::super::RecoveryGuard::decode(bytes)?.require_ready()?;
        }
        match (&self.source_quota, &self.staged_quota) {
            (Some(source), Some(staged)) => {
                let source = TenantRecord::decode(source)?;
                let staged = TenantRecord::decode(staged)?;
                if source.quota.tenant != namespace.tenant
                    || staged.quota != source.quota
                    || Some(staged.generation) != source.generation.checked_add(1)
                {
                    return Err(StoreError::Corrupt);
                }
            }
            (None, None) => {}
            _ => return Err(StoreError::Corrupt),
        }
        if self.completed {
            self.result_history()?
                .check_namespace(&self.result_namespace()?)
                .map_err(|_| StoreError::Corrupt)?;
        }
        Ok(())
    }
}

fn scope(namespace: &NamespaceRecord) -> StateScope {
    StateScope {
        tenant: namespace.tenant.clone(),
        namespace: namespace.id.clone(),
        incarnation: namespace.version.incarnation,
        state_schema: namespace.state_schema.clone(),
        entity: None,
        mode: StateMode::Command,
    }
}
