use super::{progress_prefix, schema_ids, AggregateMigrationRequest, PROGRESS_BYTES, RECIPE};
use crate::embedded::{Family, RowKey};
use crate::{
    embedded::{ExpectedRow, ReadView, StoreError},
    namespace::{
        compatibility::ReviewedSchema,
        history::{history_key, HistoryStatus, NamespaceHistory},
        namespace_record_key, NamespaceRecord, NamespaceStatus,
    },
    recovery::{guard_key, resume::NamespaceRecoveryView},
    session::version::ViewIdentity,
};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct AggregateMigrationProgress {
    format: u16,
    key_digest: [u8; 32],
    fingerprint: [u8; 32],
    checkpoint_digest: [u8; 32],
    checkpoint_manifest_digest: [u8; 32],
    package_digest: [u8; 32],
    declaration_digest: [u8; 32],
    schema_proof_digest: [u8; 32],
    recipe_digest: [u8; 32],
    namespace_row: Vec<u8>,
    history_row: Option<Vec<u8>>,
    guard_row: Option<Vec<u8>>,
    result_namespace_row: Option<Vec<u8>>,
}
impl AggregateMigrationProgress {
    pub(super) fn new(
        view: &ReadView,
        current: &NamespaceRecoveryView,
        request: &AggregateMigrationRequest,
        schema: &ReviewedSchema,
    ) -> Result<Self, StoreError> {
        let key = request.progress_key()?;
        let (_, history_row) = NamespaceHistory::capture(view, &current.namespace)?;
        Ok(Self {
            format: 1,
            key_digest: key.key[key.key.len() - 32..]
                .try_into()
                .map_err(|_| StoreError::Corrupt)?,
            fingerprint: request.fingerprint()?,
            checkpoint_digest: request.checkpoint_digest,
            checkpoint_manifest_digest: request.checkpoint_manifest_digest,
            package_digest: request.package_digest,
            declaration_digest: schema.declaration_digest(),
            schema_proof_digest: schema.proof_digest(),
            recipe_digest: Sha256::digest(RECIPE).into(),
            namespace_row: current
                .namespace
                .encode()
                .map_err(|_| StoreError::Corrupt)?,
            history_row,
            guard_row: view.get(&guard_key())?,
            result_namespace_row: None,
        })
    }
    #[must_use]
    pub fn completed(&self) -> bool {
        self.result_namespace_row.is_some()
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
        NamespaceRecord::decode(
            self.result_namespace_row
                .as_deref()
                .ok_or(StoreError::Unavailable)?,
        )
        .map_err(|_| StoreError::Corrupt)
    }
    pub fn result_history(&self) -> Result<NamespaceHistory, StoreError> {
        if !self.completed() {
            return Err(StoreError::Unavailable);
        }
        let mut history = self.source_history()?;
        history.state_schema = schema_ids()?.1.as_str().into();
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
        let history = self.result_history()?;
        let scope = NamespaceRecoveryView {
            namespace: namespace.clone(),
            history: history.clone(),
            guard: None,
        }
        .scope();
        ViewIdentity {
            namespace: namespace.version,
            epochs: history.epochs,
        }
        .token(&scope)
        .map_err(|_| StoreError::Corrupt)
    }
    pub(super) fn finish(&mut self) -> Result<(), StoreError> {
        if self.completed() {
            return Err(StoreError::Conflict);
        }
        let mut namespace = self.source_namespace()?;
        namespace.version.generation = namespace
            .version
            .generation
            .checked_add(1)
            .ok_or(StoreError::Capacity)?;
        namespace.state_schema = schema_ids()?.1.as_str().into();
        self.result_namespace_row = Some(namespace.encode().map_err(|_| StoreError::Corrupt)?);
        self.validate()
    }
    pub(super) fn require_request(
        &self,
        request: &AggregateMigrationRequest,
        schema: &ReviewedSchema,
    ) -> Result<(), StoreError> {
        self.validate()?;
        if self.fingerprint != request.fingerprint()?
            || self.package_digest != schema.declaration().package_digest
            || self.declaration_digest != schema.declaration_digest()
            || self.schema_proof_digest != schema.proof_digest()
        {
            return Err(StoreError::Conflict);
        }
        Ok(())
    }
    pub fn encode(&self) -> Result<Vec<u8>, StoreError> {
        self.validate()?;
        let bytes = serde_json::to_vec(self).map_err(|_| StoreError::Invalid)?;
        if bytes.len() > PROGRESS_BYTES {
            return Err(StoreError::Capacity);
        }
        Ok(bytes)
    }
    pub fn decode(bytes: &[u8]) -> Result<Self, StoreError> {
        if bytes.is_empty() || bytes.len() > PROGRESS_BYTES {
            return Err(StoreError::Capacity);
        }
        let progress: Self = serde_json::from_slice(bytes).map_err(|_| StoreError::Corrupt)?;
        progress.validate()?;
        if progress.encode()? != bytes {
            return Err(StoreError::Corrupt);
        }
        Ok(progress)
    }
    pub fn validate_row(key: &RowKey, bytes: &[u8]) -> Result<(), StoreError> {
        let p = Self::decode(bytes)?;
        let n = p.source_namespace()?;
        let prefix = progress_prefix(&n.tenant, &n.id, n.version.incarnation)?;
        if key.family != Family::Maintenance
            || key.key.len() != prefix.len() + 32
            || !key.key.starts_with(&prefix)
            || key.key[prefix.len()..] != p.key_digest
        {
            return Err(StoreError::Corrupt);
        }
        Ok(())
    }
    pub(super) fn history_key(&self) -> Result<RowKey, StoreError> {
        let n = self.source_namespace()?;
        history_key(&n.tenant, &n.id, n.version.incarnation).map_err(|_| StoreError::Corrupt)
    }
    pub(super) fn namespace_expectation(&self) -> Result<ExpectedRow, StoreError> {
        let n = self.source_namespace()?;
        Ok(ExpectedRow {
            key: RowKey {
                family: Family::Namespace,
                key: namespace_record_key(&n.tenant, &n.id).map_err(|_| StoreError::Corrupt)?,
            },
            value: Some(self.namespace_row.clone()),
        })
    }
    pub(super) fn history_expectation(&self) -> Result<ExpectedRow, StoreError> {
        Ok(ExpectedRow {
            key: self.history_key()?,
            value: self.history_row.clone(),
        })
    }
    pub(super) fn guard_expectation(&self) -> ExpectedRow {
        ExpectedRow {
            key: guard_key(),
            value: self.guard_row.clone(),
        }
    }
    pub(super) fn staged_history(&self) -> Result<Vec<u8>, StoreError> {
        let mut h = self.source_history()?;
        h.status = HistoryStatus::ReconciliationRequired;
        h.encode().map_err(|_| StoreError::Corrupt)
    }
    fn validate(&self) -> Result<(), StoreError> {
        if self.format != 1
            || self.recipe_digest != Sha256::digest(RECIPE).as_slice()
            || [
                self.key_digest,
                self.fingerprint,
                self.checkpoint_digest,
                self.checkpoint_manifest_digest,
                self.package_digest,
                self.declaration_digest,
                self.schema_proof_digest,
            ]
            .contains(&[0; 32])
        {
            return Err(StoreError::Corrupt);
        }
        let n = self.source_namespace()?;
        let h = self.source_history()?;
        if n.status != NamespaceStatus::Quiescing
            || n.state_schema != schema_ids()?.0.as_str()
            || h.status != HistoryStatus::Ready
        {
            return Err(StoreError::Corrupt);
        }
        if let Some(g) = &self.guard_row {
            super::super::RecoveryGuard::decode(g)?.require_ready()?;
        }
        if self.completed() {
            let mut expected = n;
            expected.version.generation = expected
                .version
                .generation
                .checked_add(1)
                .ok_or(StoreError::Corrupt)?;
            expected.state_schema = schema_ids()?.1.as_str().into();
            if self.result_namespace()? != expected {
                return Err(StoreError::Corrupt);
            }
            self.result_history()?
                .check_namespace(&expected)
                .map_err(|_| StoreError::Corrupt)?;
        }
        Ok(())
    }
}
