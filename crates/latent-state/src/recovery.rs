//! Deliberately offline recovery of the common physical transaction store.
//! Historical identities and snapshot bytes are descriptions, never renewed
//! publication/provider/result authority. Restored work stays paused for review.

use crate::{
    embedded::{AtomicBatch, ExpectedRow, Family, ReadView, RowKey, RowMutation, StoreError},
    namespace::{
        history::{HistoryStatus, NamespaceHistory},
        namespace_record_key, NamespaceRecord, NamespaceStatus,
    },
};
use latent_core::{StateNamespaceId, TenantId};

#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
pub mod offline;
pub mod restore;
pub mod snapshot;

pub const GUARD_KEY: &[u8] = b"recovery-control-v1\0";
pub const GUARD_BYTES: usize = 133;
const MAGIC: &[u8] = b"RCV\x01";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RecoveryStatus {
    Staging,
    ReconciliationRequired,
    ReviewAccepted,
}

/// Durable complete-store guard. Its original identity is copied, never derived
/// again from a new publication or effect ID. Receipt bytes grant no authority.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RecoveryGuard {
    operation_digest: [u8; 32],
    snapshot_digest: [u8; 32],
    window_digest: [u8; 32],
    review_digest: [u8; 32],
    status: RecoveryStatus,
}

impl RecoveryGuard {
    pub fn staging(
        operation_digest: [u8; 32],
        snapshot_digest: [u8; 32],
        window_digest: [u8; 32],
    ) -> Result<Self, StoreError> {
        let guard = Self {
            operation_digest,
            snapshot_digest,
            window_digest,
            review_digest: [0; 32],
            status: RecoveryStatus::Staging,
        };
        guard.validate()?;
        Ok(guard)
    }

    #[must_use]
    pub fn status(&self) -> RecoveryStatus {
        self.status
    }

    #[must_use]
    pub fn snapshot_digest(&self) -> [u8; 32] {
        self.snapshot_digest
    }

    #[must_use]
    pub fn operation_digest(&self) -> [u8; 32] {
        self.operation_digest
    }

    #[must_use]
    pub fn window_digest(&self) -> [u8; 32] {
        self.window_digest
    }

    pub fn encode(&self) -> Result<Vec<u8>, StoreError> {
        self.validate()?;
        let mut bytes = Vec::with_capacity(GUARD_BYTES);
        bytes.extend_from_slice(MAGIC);
        bytes.push(match self.status {
            RecoveryStatus::Staging => 1,
            RecoveryStatus::ReconciliationRequired => 2,
            RecoveryStatus::ReviewAccepted => 3,
        });
        for digest in [
            self.operation_digest,
            self.snapshot_digest,
            self.window_digest,
            self.review_digest,
        ] {
            bytes.extend_from_slice(&digest);
        }
        Ok(bytes)
    }

    pub fn decode(bytes: &[u8]) -> Result<Self, StoreError> {
        if bytes.len() != GUARD_BYTES || !bytes.starts_with(MAGIC) {
            return Err(StoreError::Corrupt);
        }
        let guard = Self {
            status: match bytes[4] {
                1 => RecoveryStatus::Staging,
                2 => RecoveryStatus::ReconciliationRequired,
                3 => RecoveryStatus::ReviewAccepted,
                _ => return Err(StoreError::UnsupportedFormat),
            },
            operation_digest: bytes[5..37].try_into().map_err(|_| StoreError::Corrupt)?,
            snapshot_digest: bytes[37..69].try_into().map_err(|_| StoreError::Corrupt)?,
            window_digest: bytes[69..101].try_into().map_err(|_| StoreError::Corrupt)?,
            review_digest: bytes[101..133]
                .try_into()
                .map_err(|_| StoreError::Corrupt)?,
        };
        guard.validate().map_err(|_| StoreError::Corrupt)?;
        Ok(guard)
    }

    pub fn validate_row(key: &RowKey, bytes: &[u8]) -> Result<(), StoreError> {
        if *key != guard_key() {
            return Err(StoreError::UnsupportedFormat);
        }
        Self::decode(bytes)?;
        Ok(())
    }

    pub fn capture(view: &ReadView) -> Result<Option<Self>, StoreError> {
        view.get(&guard_key())?
            .as_deref()
            .map(Self::decode)
            .transpose()
    }

    pub fn require_ready(&self) -> Result<(), StoreError> {
        self.validate()?;
        if self.status != RecoveryStatus::ReviewAccepted {
            return Err(StoreError::Unavailable);
        }
        Ok(())
    }

    /// Initial fresh-root staging must precede imported rows. Interrupted work
    /// remains distinguishable and cannot open command/query/dispatch admission.
    pub fn prepare_staging(&self) -> Result<AtomicBatch, StoreError> {
        if self.status != RecoveryStatus::Staging {
            return Err(StoreError::Invalid);
        }
        Ok(AtomicBatch {
            expectations: vec![ExpectedRow {
                key: guard_key(),
                value: None,
            }],
            mutations: vec![RowMutation {
                key: guard_key(),
                value: Some(self.encode()?),
            }],
        })
    }

    /// Only after all staged rows and required linked payload/artifact decoders
    /// validate. This publishes paused recovery, not automatic business resume.
    pub fn prepare_completed(&self) -> Result<AtomicBatch, StoreError> {
        if self.status != RecoveryStatus::Staging {
            return Err(StoreError::Invalid);
        }
        let mut completed = self.clone();
        completed.status = RecoveryStatus::ReconciliationRequired;
        self.replacement(&completed)
    }

    /// The configured control owner reviews the actual linked restored view,
    /// current grants, conservative clock continuity and declared data-loss
    /// window. Acceptance cannot itself activate paused namespace histories.
    pub fn prepare_reviewed(
        &self,
        view: &ReadView,
        review_digest: [u8; 32],
        review: impl FnOnce(&ReadView, &Self, [u8; 32]) -> Result<(), StoreError>,
    ) -> Result<AtomicBatch, StoreError> {
        if self.status != RecoveryStatus::ReconciliationRequired || review_digest == [0; 32] {
            return Err(StoreError::Invalid);
        }
        if Self::capture(view)?.as_ref() != Some(self) {
            return Err(StoreError::Conflict);
        }
        review(view, self, review_digest)?;
        let mut approved = self.clone();
        approved.status = RecoveryStatus::ReviewAccepted;
        approved.review_digest = review_digest;
        self.replacement(&approved)
    }

    fn replacement(&self, after: &Self) -> Result<AtomicBatch, StoreError> {
        Ok(AtomicBatch {
            expectations: vec![ExpectedRow {
                key: guard_key(),
                value: Some(self.encode()?),
            }],
            mutations: vec![RowMutation {
                key: guard_key(),
                value: Some(after.encode()?),
            }],
        })
    }

    fn validate(&self) -> Result<(), StoreError> {
        if [
            self.operation_digest,
            self.snapshot_digest,
            self.window_digest,
        ]
        .contains(&[0; 32])
            || (self.status == RecoveryStatus::ReviewAccepted) != (self.review_digest != [0; 32])
        {
            return Err(StoreError::Invalid);
        }
        Ok(())
    }
}

#[must_use]
pub fn guard_key() -> RowKey {
    RowKey {
        family: Family::Maintenance,
        key: GUARD_KEY.to_vec(),
    }
}

/// Call on the actual current worker-owned view for command/query admission.
/// Absence is the unchanged pre-recovery profile; malformed guards fail closed.
pub fn require_ready(view: &ReadView) -> Result<(), StoreError> {
    match RecoveryGuard::capture(view)? {
        Some(guard) => guard.require_ready(),
        None => Ok(()),
    }
}

/// Real dispatch selection also checks the original namespace/incarnation and
/// paused history. A global review does not move an effect to a replacement
/// namespace, renew a provider grant or bypass original ordered predecessors.
pub fn require_namespace_ready(
    view: &ReadView,
    tenant: &TenantId,
    namespace: &StateNamespaceId,
    incarnation: u64,
) -> Result<(), StoreError> {
    require_ready(view)?;
    let key = RowKey {
        family: Family::Namespace,
        key: namespace_record_key(tenant, namespace).map_err(|_| StoreError::Invalid)?,
    };
    let record = NamespaceRecord::decode(&view.get(&key)?.ok_or(StoreError::Corrupt)?)
        .map_err(|_| StoreError::Corrupt)?;
    if record.tenant != *tenant
        || record.id != *namespace
        || record.version.incarnation != incarnation
    {
        return Err(StoreError::Conflict);
    }
    if record.status != NamespaceStatus::Active {
        return Err(StoreError::Unavailable);
    }
    let (history, _) = NamespaceHistory::capture(view, &record)?;
    if history.status != HistoryStatus::Ready {
        return Err(StoreError::Unavailable);
    }
    Ok(())
}

#[cfg(test)]
mod tests;
