//! Explicit namespace activation after offline review. Receipts describe the
//! original decision; they never renew a grant or make a later namespace ready.

use super::{guard_key, require_ready, RecoveryGuard};
use crate::{
    embedded::{AtomicBatch, ExpectedRow, Family, ReadView, RowKey, RowMutation, StoreError},
    namespace::{
        history::{history_key, HistoryStatus, NamespaceHistory},
        namespace_record_key, NamespaceRecord, NamespaceStatus,
    },
    session::{version::ViewIdentity, StateMode, StateScope},
};
use latent_core::{StateNamespaceId, TenantId};
use sha2::{Digest, Sha256};

pub const RECEIPT_PREFIX: &[u8] = b"namespace-resume-v1\0";
pub const RECEIPT_BYTES: usize = 6144;
const MAGIC: &[u8] = b"NRS\x01";

/// This operation checkpoint has its own decoder, independent of app schemas.
#[must_use]
pub fn retained_format() -> crate::namespace::compatibility::RetainedFormat {
    use crate::namespace::compatibility::{RetainedFormat, RetainedKind};
    RetainedFormat {
        kind: RetainedKind::MigrationCheckpoint,
        identity: "lsf.namespace-resume.v1".into(),
    }
}

/// Administrative observation of actual paused history. This is not a lease,
/// a minimum-version certificate or evidence that pending effects are unsent.
#[derive(Debug, Clone)]
pub struct NamespaceRecoveryView {
    pub namespace: NamespaceRecord,
    pub history: NamespaceHistory,
    pub guard: Option<RecoveryGuard>,
}
impl NamespaceRecoveryView {
    pub fn capture(
        view: &ReadView,
        tenant: &TenantId,
        namespace: &StateNamespaceId,
    ) -> Result<Self, StoreError> {
        let key = RowKey {
            family: Family::Namespace,
            key: namespace_record_key(tenant, namespace).map_err(|_| StoreError::Invalid)?,
        };
        let namespace = NamespaceRecord::decode(&view.get(&key)?.ok_or(StoreError::Conflict)?)
            .map_err(|_| StoreError::Corrupt)?;
        if namespace.tenant != *tenant
            || key.key
                != namespace_record_key(&namespace.tenant, &namespace.id)
                    .map_err(|_| StoreError::Corrupt)?
        {
            return Err(StoreError::Corrupt);
        }
        let (history, _) = NamespaceHistory::capture(view, &namespace)?;
        Ok(Self {
            namespace,
            history,
            guard: RecoveryGuard::capture(view)?,
        })
    }
    #[must_use]
    pub fn scope(&self) -> StateScope {
        scope(&self.namespace)
    }
    pub fn view_token(&self) -> Result<Vec<u8>, StoreError> {
        ViewIdentity {
            namespace: self.namespace.version,
            epochs: self.history.epochs,
        }
        .token(&self.scope())
        .map_err(|_| StoreError::Corrupt)
    }
}

#[derive(Debug, Clone)]
pub struct NamespaceResumeRequest {
    pub scope: StateScope,
    pub operation_id: String,
    /// Authenticated operator identity, never a guest-selected actor.
    pub operator_id: String,
    pub expected_view: Vec<u8>,
    /// Exact installed review evidence, including current clock and authority.
    pub review_digest: [u8; 32],
}

impl NamespaceResumeRequest {
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
            || self.scope.mode != StateMode::Command
            || self.review_digest == [0; 32]
        {
            return Err(StoreError::Invalid);
        }
        ViewIdentity::from_token(&self.scope, &self.expected_view)
            .map_err(|_| StoreError::Invalid)?;
        Ok(())
    }

    fn fingerprint(&self) -> Result<[u8; 32], StoreError> {
        self.validate()?;
        let mut hash = Sha256::new();
        hash.update(b"lsf-namespace-resume-input-v1\0");
        for value in [
            self.scope.tenant.0.as_bytes(),
            self.scope.namespace.0.as_bytes(),
            self.scope.state_schema.as_bytes(),
            self.operation_id.as_bytes(),
            self.operator_id.as_bytes(),
            self.expected_view.as_slice(),
            self.review_digest.as_slice(),
        ] {
            hash.update((value.len() as u64).to_le_bytes());
            hash.update(value);
        }
        Ok(hash.finalize().into())
    }

    pub fn receipt_key(&self) -> Result<RowKey, StoreError> {
        self.validate()?;
        let mut hash = Sha256::new();
        hash.update(RECEIPT_PREFIX);
        for value in [
            self.scope.tenant.0.as_bytes(),
            self.operator_id.as_bytes(),
            self.operation_id.as_bytes(),
        ] {
            hash.update((value.len() as u64).to_le_bytes());
            hash.update(value);
        }
        let mut key = RECEIPT_PREFIX.to_vec();
        key.extend_from_slice(&hash.finalize());
        Ok(RowKey {
            family: Family::Maintenance,
            key,
        })
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NamespaceResumeReceipt {
    key_digest: [u8; 32],
    fingerprint: [u8; 32],
    namespace: NamespaceRecord,
    history: NamespaceHistory,
}

impl NamespaceResumeReceipt {
    #[must_use]
    pub fn namespace(&self) -> &NamespaceRecord {
        &self.namespace
    }
    #[must_use]
    pub fn history(&self) -> &NamespaceHistory {
        &self.history
    }
    pub fn view_token(&self) -> Result<Vec<u8>, StoreError> {
        ViewIdentity {
            namespace: self.namespace.version,
            epochs: self.history.epochs,
        }
        .token(&scope(&self.namespace))
        .map_err(|_| StoreError::Corrupt)
    }
    pub fn encode(&self) -> Result<Vec<u8>, StoreError> {
        self.validate()?;
        let mut bytes = MAGIC.to_vec();
        bytes.extend_from_slice(&self.key_digest);
        bytes.extend_from_slice(&self.fingerprint);
        for row in [
            self.namespace.encode().map_err(|_| StoreError::Corrupt)?,
            self.history.encode().map_err(|_| StoreError::Corrupt)?,
        ] {
            bytes.extend_from_slice(
                &u16::try_from(row.len())
                    .map_err(|_| StoreError::Capacity)?
                    .to_le_bytes(),
            );
            bytes.extend_from_slice(&row);
        }
        if bytes.len() > RECEIPT_BYTES {
            return Err(StoreError::Capacity);
        }
        Ok(bytes)
    }
    pub fn decode(bytes: &[u8]) -> Result<Self, StoreError> {
        if bytes.len() < 72 || bytes.len() > RECEIPT_BYTES || !bytes.starts_with(MAGIC) {
            return Err(StoreError::Corrupt);
        }
        let mut offset = 68usize;
        let mut take_row = || -> Result<&[u8], StoreError> {
            let length = u16::from_le_bytes(
                bytes
                    .get(offset..offset + 2)
                    .ok_or(StoreError::Corrupt)?
                    .try_into()
                    .map_err(|_| StoreError::Corrupt)?,
            );
            offset += 2;
            let row = bytes
                .get(offset..offset + usize::from(length))
                .ok_or(StoreError::Corrupt)?;
            offset += usize::from(length);
            Ok(row)
        };
        let namespace = NamespaceRecord::decode(take_row()?).map_err(|_| StoreError::Corrupt)?;
        let history = NamespaceHistory::decode(take_row()?).map_err(|_| StoreError::Corrupt)?;
        if offset != bytes.len() {
            return Err(StoreError::Corrupt);
        }
        let receipt = Self {
            key_digest: bytes[4..36].try_into().map_err(|_| StoreError::Corrupt)?,
            fingerprint: bytes[36..68].try_into().map_err(|_| StoreError::Corrupt)?,
            namespace,
            history,
        };
        receipt.validate()?;
        Ok(receipt)
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
    fn validate(&self) -> Result<(), StoreError> {
        self.namespace.validate().map_err(|_| StoreError::Corrupt)?;
        self.history
            .check_namespace(&self.namespace)
            .map_err(|_| StoreError::Corrupt)?;
        if self.namespace.status != NamespaceStatus::Active
            || self.history.status != HistoryStatus::Ready
            || self.key_digest == [0; 32]
            || self.fingerprint == [0; 32]
        {
            return Err(StoreError::Corrupt);
        }
        Ok(())
    }
}

/// Actual rows are supplied to the installed reviewer before receipt disclosure
/// or any change. A historical accepted receipt remains distinct from this view.
pub struct NamespaceResumeObservation<'a> {
    pub namespace: &'a NamespaceRecord,
    pub history: &'a NamespaceHistory,
    pub guard: Option<&'a RecoveryGuard>,
    pub original_receipt: Option<&'a NamespaceResumeReceipt>,
}

pub struct NamespaceResumePlan {
    batch: AtomicBatch,
    receipt: NamespaceResumeReceipt,
    replayed: bool,
}

impl NamespaceResumePlan {
    pub fn prepare(
        view: &ReadView,
        request: &NamespaceResumeRequest,
        review: impl FnOnce(
            &ReadView,
            &NamespaceResumeRequest,
            NamespaceResumeObservation<'_>,
        ) -> Result<(), StoreError>,
    ) -> Result<Self, StoreError> {
        request.validate()?;
        require_ready(view)?;
        let namespace_key = RowKey {
            family: Family::Namespace,
            key: namespace_record_key(&request.scope.tenant, &request.scope.namespace)
                .map_err(|_| StoreError::Invalid)?,
        };
        let original = view.get(&namespace_key)?.ok_or(StoreError::Conflict)?;
        let namespace = NamespaceRecord::decode(&original).map_err(|_| StoreError::Corrupt)?;
        if namespace.tenant != request.scope.tenant || namespace.id != request.scope.namespace {
            return Err(StoreError::Corrupt);
        }
        let (history, history_bytes) = NamespaceHistory::capture(view, &namespace)?;
        let guard_bytes = view.get(&guard_key())?;
        let guard = guard_bytes
            .as_deref()
            .map(RecoveryGuard::decode)
            .transpose()?;
        let receipt_key = request.receipt_key()?;
        let original_receipt = view.get(&receipt_key)?;
        let fingerprint = request.fingerprint()?;
        let prior = original_receipt
            .as_deref()
            .map(NamespaceResumeReceipt::decode)
            .transpose()?;
        if let Some(prior) = &prior {
            NamespaceResumeReceipt::validate_row(&receipt_key, original_receipt.as_ref().unwrap())?;
            if prior.fingerprint != fingerprint {
                return Err(StoreError::Conflict);
            }
        } else if namespace.status != NamespaceStatus::Quiescing
            || namespace.version.incarnation != request.scope.incarnation
            || namespace.state_schema != request.scope.state_schema
            || (ViewIdentity {
                namespace: namespace.version,
                epochs: history.epochs,
            })
            .token(&request.scope)
            .map_err(|_| StoreError::Invalid)?
                != request.expected_view
        {
            return Err(StoreError::Conflict);
        }
        if prior.is_none() {
            super::migration::require_resume_ready(view, &namespace)?;
        }
        review(
            view,
            request,
            NamespaceResumeObservation {
                namespace: &namespace,
                history: &history,
                guard: guard.as_ref(),
                original_receipt: prior.as_ref(),
            },
        )?;
        let batch = AtomicBatch {
            expectations: vec![
                ExpectedRow {
                    key: namespace_key.clone(),
                    value: Some(original),
                },
                ExpectedRow {
                    key: history_key(
                        &namespace.tenant,
                        &namespace.id,
                        namespace.version.incarnation,
                    )
                    .map_err(|_| StoreError::Corrupt)?,
                    value: history_bytes,
                },
                ExpectedRow {
                    key: guard_key(),
                    value: guard_bytes,
                },
                ExpectedRow {
                    key: receipt_key.clone(),
                    value: original_receipt,
                },
            ],
            mutations: vec![],
        };
        if let Some(receipt) = prior {
            return Ok(Self {
                batch,
                receipt,
                replayed: true,
            });
        }
        Self::activate(batch, namespace, history, fingerprint)
    }

    fn activate(
        mut batch: AtomicBatch,
        mut namespace: NamespaceRecord,
        mut history: NamespaceHistory,
        fingerprint: [u8; 32],
    ) -> Result<Self, StoreError> {
        let namespace_key = batch.expectations[0].key.clone();
        let receipt_key = batch.expectations[3].key.clone();
        namespace.version.generation = namespace
            .version
            .generation
            .checked_add(1)
            .ok_or(StoreError::Capacity)?;
        namespace.status = NamespaceStatus::Active;
        history.status = HistoryStatus::Ready;
        let receipt = NamespaceResumeReceipt {
            key_digest: receipt_key.key[RECEIPT_PREFIX.len()..]
                .try_into()
                .map_err(|_| StoreError::Corrupt)?,
            fingerprint,
            namespace,
            history,
        };
        batch.mutations = vec![
            RowMutation {
                key: namespace_key,
                value: Some(
                    receipt
                        .namespace
                        .encode()
                        .map_err(|_| StoreError::Corrupt)?,
                ),
            },
            RowMutation {
                key: batch.expectations[1].key.clone(),
                value: Some(receipt.history.encode().map_err(|_| StoreError::Corrupt)?),
            },
            RowMutation {
                key: receipt_key,
                value: Some(receipt.encode()?),
            },
        ];
        Ok(Self {
            batch,
            receipt,
            replayed: false,
        })
    }
    #[must_use]
    pub fn receipt(&self) -> &NamespaceResumeReceipt {
        &self.receipt
    }
    #[must_use]
    pub fn replayed(&self) -> bool {
        self.replayed
    }
    /// The physical owner must still use its actual final currentness fence.
    #[must_use]
    pub fn into_batch(self) -> AtomicBatch {
        self.batch
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

#[cfg(test)]
mod tests;
