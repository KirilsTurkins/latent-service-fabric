//! A reviewed older-history restore preserves original business rows and IDs.
//! Only the local live history fence changes, and the entire root stays paused.

use super::{
    snapshot::{
        capture_namespaces, inspect_snapshot, NamespaceSnapshot, SnapshotClosure, SnapshotReceipt,
        MANIFEST_BYTES, SNAPSHOT_NAMESPACES,
    },
    RecoveryGuard,
};
use crate::{
    embedded::{
        AtomicBatch, EmbeddedStore, ReadView, RowKey, RowMutation, StoreError, StoreLimits,
    },
    namespace::history::{history_key, NamespaceHistory},
};
use serde::Serialize;
use sha2::{Digest, Sha256};
use std::{io::Read, time::Instant};

#[derive(Debug, Clone, Serialize)]
pub struct NamespaceRecoveryWindow {
    pub snapshot: NamespaceSnapshot,
    pub current: NamespaceSnapshot,
}

/// Captured from the actual quiesced source, never caller-supplied generations.
/// Post-backup commands and remote acknowledgements may be unknown after
/// restore. Their reconciliation is mandatory even when old rows say Pending.
#[derive(Debug, Serialize)]
pub struct RestoreWindow {
    snapshot_digest: [u8; 32],
    tenant: String,
    namespaces: Vec<NamespaceRecoveryWindow>,
}

impl RestoreWindow {
    pub fn capture(current: &ReadView, snapshot: &SnapshotReceipt) -> Result<Self, StoreError> {
        snapshot.manifest.validate()?;
        super::require_ready(current)?;
        let actual = capture_namespaces(current, &snapshot.manifest.metadata.tenant)?;
        // This first profile refuses roster/incarnation changes. Restoring a
        // destroyed/recreated namespace cannot reuse its old business identity.
        if actual.len() != snapshot.manifest.namespaces.len() {
            return Err(StoreError::Conflict);
        }
        let mut namespaces = Vec::with_capacity(actual.len());
        for (before, now) in snapshot.manifest.namespaces.iter().zip(actual) {
            let (record, history) = before.decode()?;
            let (current_record, current_history) = now.decode()?;
            if record.tenant != current_record.tenant
                || record.id != current_record.id
                || record.version.incarnation != current_record.version.incarnation
                || record.version.generation > current_record.version.generation
            {
                return Err(StoreError::Conflict);
            }
            history
                .restored_after(&current_history)
                .map_err(|_| StoreError::Conflict)?;
            namespaces.push(NamespaceRecoveryWindow {
                snapshot: before.clone(),
                current: now,
            });
        }
        Ok(Self {
            snapshot_digest: snapshot.snapshot_digest,
            tenant: snapshot.manifest.metadata.tenant.clone(),
            namespaces,
        })
    }

    #[must_use]
    pub fn namespaces(&self) -> &[NamespaceRecoveryWindow] {
        &self.namespaces
    }

    pub fn canonical_bytes(&self) -> Result<Vec<u8>, StoreError> {
        let bytes = serde_json::to_vec(self).map_err(|_| StoreError::Invalid)?;
        if bytes.len() > MANIFEST_BYTES {
            return Err(StoreError::Capacity);
        }
        Ok(bytes)
    }

    pub fn digest(&self) -> Result<[u8; 32], StoreError> {
        let mut hash = Sha256::new();
        hash.update(b"latent-recovery-window-v1\0");
        hash.update(self.canonical_bytes()?);
        Ok(hash.finalize().into())
    }
}

#[derive(Debug, Clone)]
pub struct RestoreRequest {
    pub operation_id: String,
    pub operator_id: String,
    pub snapshot_digest: [u8; 32],
    /// Exact installed runtime. Unsupported upgrade/downgrade is refused; an
    /// application-reader declaration cannot certify storage/work decoding.
    pub runtime_digest: [u8; 32],
    /// Explicit acknowledgement of the current, source-backed recovery window.
    pub window_acknowledgement: [u8; 32],
}

/// No public constructor bypasses actual source capture and installed review.
pub struct RestorePlan {
    snapshot: SnapshotReceipt,
    guard: RecoveryGuard,
    histories: Vec<NamespaceHistory>,
}

impl RestorePlan {
    pub fn prepare(
        current: &ReadView,
        snapshot: SnapshotReceipt,
        request: &RestoreRequest,
        review: impl FnOnce(&RestoreWindow, &RestoreRequest) -> Result<(), StoreError>,
    ) -> Result<Self, StoreError> {
        for identity in [&request.operation_id, &request.operator_id] {
            crate::namespace::identity(identity).map_err(|_| StoreError::Invalid)?;
        }
        if request.snapshot_digest == [0; 32] || request.snapshot_digest != snapshot.snapshot_digest
        {
            return Err(StoreError::Corrupt);
        }
        if request.runtime_digest == [0; 32]
            || request.runtime_digest != snapshot.manifest.metadata.runtime_digest
        {
            return Err(StoreError::UnsupportedFormat);
        }
        let window = RestoreWindow::capture(current, &snapshot)?;
        let window_digest = window.digest()?;
        if request.window_acknowledgement != window_digest {
            return Err(StoreError::Conflict);
        }
        let histories = window
            .namespaces
            .iter()
            .map(|entry| {
                let (_, original) = entry.snapshot.decode()?;
                let (_, actual) = entry.current.decode()?;
                original
                    .restored_after(&actual)
                    .map_err(|_| StoreError::Capacity)
            })
            .collect::<Result<Vec<_>, StoreError>>()?;
        review(&window, request)?;
        let mut operation = Sha256::new();
        operation.update(b"latent-offline-restore-operation-v1\0");
        for value in [&request.operation_id, &request.operator_id] {
            operation.update(
                u16::try_from(value.len())
                    .map_err(|_| StoreError::Invalid)?
                    .to_le_bytes(),
            );
            operation.update(value.as_bytes());
        }
        operation.update(window_digest);
        Ok(Self {
            guard: RecoveryGuard::staging(
                operation.finalize().into(),
                snapshot.snapshot_digest,
                window_digest,
            )?,
            snapshot,
            histories,
        })
    }

    #[must_use]
    pub fn guard(&self) -> &RecoveryGuard {
        &self.guard
    }

    /// Conservative admission reserves a guard plus every potentially absent
    /// live history row before creating a destination. It never silently raises
    /// the selected store's configured physical/logical quotas.
    pub fn require_capacity(&self, limits: StoreLimits) -> Result<(), StoreError> {
        if self
            .snapshot
            .manifest
            .rows
            .checked_add(1 + u64::try_from(self.histories.len()).map_err(|_| StoreError::Capacity)?)
            .is_none_or(|rows| rows > u64::try_from(limits.maximum_rows).unwrap_or(0))
            || self
                .snapshot
                .manifest
                .logical_bytes
                .checked_add(
                    u64::try_from(SNAPSHOT_NAMESPACES * 4096).map_err(|_| StoreError::Capacity)?,
                )
                .is_none_or(|bytes| {
                    bytes > u64::try_from(limits.maximum_logical_bytes).unwrap_or(0)
                })
        {
            return Err(StoreError::Capacity);
        }
        Ok(())
    }

    /// Caller has inspected the whole protected input before creating a fresh
    /// selected-engine destination. Re-reading uses the same finite codec and
    /// validates the exact digest again. Interruption leaves durable Staging.
    pub fn execute(
        self,
        input: &mut impl Read,
        destination: &EmbeddedStore,
        deadline: Instant,
        mut validate_row: impl FnMut(&RowKey, &[u8]) -> Result<(), StoreError>,
        validate_staged: impl FnOnce(&ReadView) -> Result<SnapshotClosure, StoreError>,
    ) -> Result<RecoveryGuard, StoreError> {
        super::snapshot::validate_deadline(deadline)?;
        self.require_capacity(destination.limits())?;
        require_empty(destination)?;
        destination.apply(self.guard.prepare_staging()?)?;
        let mut importer = Importer {
            destination,
            batch: AtomicBatch::default(),
            bytes: 0,
            deadline,
        };
        let observed = inspect_snapshot(input, deadline, |key, value| {
            validate_row(key, value)?;
            // Historical guard bytes are not present-day authority. The fresh
            // root's staging guard must remain installed throughout every page.
            if *key != super::guard_key() {
                importer.put(key, value)?;
            }
            Ok(())
        })?;
        importer.flush()?;
        if observed != self.snapshot {
            return Err(StoreError::Corrupt);
        }
        {
            let view = destination.snapshot()?;
            require_original_namespaces(&view, &self.snapshot)?;
            let actual = validate_staged(&view)?;
            actual.require_declared(&self.snapshot.manifest.metadata)?;
            if actual.inventory != self.snapshot.manifest.inventory()? {
                return Err(StoreError::Corrupt);
            }
        }
        super::snapshot::checkpoint(deadline)?;
        publish_histories(destination, &self.histories, deadline)?;
        super::snapshot::checkpoint(deadline)?;
        destination.apply(self.guard.prepare_completed()?)?;
        RecoveryGuard::capture(&destination.snapshot()?)?.ok_or(StoreError::Corrupt)
    }
}

fn require_empty(destination: &EmbeddedStore) -> Result<(), StoreError> {
    let view = destination.snapshot()?;
    for family in super::snapshot::FAMILIES {
        if !view.scan(family, b"", 1, 4096)?.is_empty() {
            return Err(StoreError::Conflict);
        }
    }
    Ok(())
}

fn require_original_namespaces(
    view: &ReadView,
    snapshot: &SnapshotReceipt,
) -> Result<(), StoreError> {
    if capture_namespaces(view, &snapshot.manifest.metadata.tenant)? != snapshot.manifest.namespaces
    {
        return Err(StoreError::Corrupt);
    }
    Ok(())
}

fn publish_histories(
    destination: &EmbeddedStore,
    histories: &[NamespaceHistory],
    deadline: Instant,
) -> Result<(), StoreError> {
    for page in histories.chunks(destination.limits().maximum_batch_rows.min(128)) {
        super::snapshot::checkpoint(deadline)?;
        let view = destination.snapshot()?;
        let mut batch = AtomicBatch::default();
        for history in page {
            let key = history_key(&history.tenant, &history.namespace, history.incarnation)
                .map_err(|_| StoreError::Corrupt)?;
            batch.expectations.push(crate::embedded::ExpectedRow {
                value: view.get(&key)?,
                key: key.clone(),
            });
            batch.mutations.push(RowMutation {
                key,
                value: Some(history.encode().map_err(|_| StoreError::Corrupt)?),
            });
        }
        drop(view);
        destination.apply(batch)?;
    }
    Ok(())
}

struct Importer<'a> {
    destination: &'a EmbeddedStore,
    batch: AtomicBatch,
    bytes: usize,
    deadline: Instant,
}
impl Importer<'_> {
    fn put(&mut self, key: &RowKey, value: &[u8]) -> Result<(), StoreError> {
        let bytes = key
            .key
            .len()
            .checked_add(value.len())
            .ok_or(StoreError::Capacity)?;
        if bytes > 4 * 1024 * 1024 {
            return Err(StoreError::Capacity);
        }
        if self.batch.mutations.len() >= self.destination.limits().maximum_batch_rows.min(128)
            || self
                .bytes
                .checked_add(bytes)
                .is_none_or(|total| total > 4 * 1024 * 1024)
        {
            self.flush()?;
        }
        self.bytes += bytes;
        self.batch.mutations.push(RowMutation {
            key: key.clone(),
            value: Some(value.to_vec()),
        });
        Ok(())
    }
    fn flush(&mut self) -> Result<(), StoreError> {
        super::snapshot::checkpoint(self.deadline)?;
        if !self.batch.mutations.is_empty() {
            self.destination.apply(std::mem::take(&mut self.batch))?;
            self.bytes = 0;
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests;
