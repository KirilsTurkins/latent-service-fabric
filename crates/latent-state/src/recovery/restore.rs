//! Exact older-history input and loss-window descriptions. These values retain
//! no physical owner or permission. Fresh rooted destination/checkpoint, actual
//! linked staged validation, current authorization and resume remain separate.

use super::{
    snapshot::{
        capture_namespaces, checkpoint, visit_view, NamespaceSnapshot, SnapshotError,
        SnapshotReceipt, MANIFEST_BYTES, SNAPSHOT_FILE_BYTES,
    },
    RecoveryGuard,
};
use crate::{
    embedded::{ReadView, StoreError},
    namespace::history::NamespaceHistory,
    store_identity::StoreIdentity,
};
use serde::Serialize;
use sha2::{Digest, Sha256};
use std::time::Instant;

/// Both rows were decoded from the actual original namespace owners. The
/// proposed history stays paused and changes no business/command/effect ID.
#[derive(Debug, Serialize)]
pub struct NamespaceRecoveryWindow {
    snapshot: NamespaceSnapshot,
    current: NamespaceSnapshot,
    proposed: Vec<u8>,
}
impl NamespaceRecoveryWindow {
    #[must_use]
    pub const fn snapshot(&self) -> &NamespaceSnapshot {
        &self.snapshot
    }
    #[must_use]
    pub const fn current(&self) -> &NamespaceSnapshot {
        &self.current
    }
    pub fn proposed_history(&self) -> Result<NamespaceHistory, StoreError> {
        NamespaceHistory::decode(&self.proposed).map_err(|_| StoreError::Corrupt)
    }
}

/// Complete-unit descriptive precondition. Metadata tenant is never a filter
/// or cross-tenant access grant. Every post-backup command/effect may be unknown;
/// a snapshot's Pending/no-attempt row supplies no evidence of nonexecution.
#[derive(Debug, Serialize)]
pub struct RestoreWindow {
    snapshot_digest: [u8; 32],
    manifest_digest: [u8; 32],
    source_identity: Vec<u8>,
    current_rows_digest: [u8; 32],
    current_rows: u64,
    current_logical_bytes: u64,
    namespaces: Vec<NamespaceRecoveryWindow>,
}
impl RestoreWindow {
    /// The host obtains `snapshot` by rereading its original protected file and
    /// reviews the SAME borrowed current view with original installed codecs.
    /// This captures descriptions only; neither the receipt nor this function
    /// certifies physical quiescence or creates a destination-import grant.
    pub fn capture(
        current: &ReadView,
        snapshot: &SnapshotReceipt,
        deadline: Instant,
        mut check_current: impl FnMut() -> Result<(), StoreError>,
    ) -> Result<Self, SnapshotError> {
        super::snapshot::validate_deadline(deadline).map_err(SnapshotError::source)?;
        check(deadline, &mut check_current)?;
        snapshot
            .manifest
            .validate()
            .map_err(SnapshotError::Review)?;
        let manifest = snapshot.manifest.encode().map_err(SnapshotError::Review)?;
        if snapshot.snapshot_digest == [0; 32]
            || snapshot.manifest_digest != <[u8; 32]>::from(Sha256::digest(&manifest))
            || snapshot.file_bytes == 0
            || snapshot.file_bytes > SNAPSHOT_FILE_BYTES
        {
            return Err(SnapshotError::Review(StoreError::Corrupt));
        }
        let identity = StoreIdentity::inspect(current)
            .map_err(SnapshotError::source)?
            .ok_or(SnapshotError::Review(StoreError::UnsupportedFormat))?;
        if identity.encode() != snapshot.manifest.source_store_identity {
            return Err(SnapshotError::Review(StoreError::Conflict));
        }
        if RecoveryGuard::capture(current)
            .map_err(SnapshotError::source)?
            .is_some_and(|guard| guard.require_ready().is_err())
        {
            return Err(SnapshotError::Review(StoreError::Conflict));
        }
        let actual = capture_namespaces(current).map_err(SnapshotError::source)?;
        if actual.len() != snapshot.manifest.namespaces.len() {
            return Err(SnapshotError::Review(StoreError::Conflict));
        }
        let namespaces = snapshot
            .manifest
            .namespaces
            .iter()
            .zip(actual)
            .map(|(before, now)| pair(before, now))
            .collect::<Result<Vec<_>, _>>()?;
        let mut refusal = None;
        let observed = visit_view(current, deadline, |_, _, _| {
            check(deadline, &mut check_current).map_err(|error| {
                refusal = Some(error);
                StoreError::Invalid
            })
        });
        if let Some(error) = refusal {
            return Err(error);
        }
        let observed = observed.map_err(SnapshotError::source)?;
        check(deadline, &mut check_current)?;
        Ok(Self {
            snapshot_digest: snapshot.snapshot_digest,
            manifest_digest: snapshot.manifest_digest,
            source_identity: identity.encode(),
            current_rows_digest: observed.digest,
            current_rows: observed.rows,
            current_logical_bytes: observed.logical_bytes,
            namespaces,
        })
    }

    #[must_use]
    pub fn namespaces(&self) -> &[NamespaceRecoveryWindow] {
        &self.namespaces
    }
    #[must_use]
    pub const fn snapshot_digest(&self) -> [u8; 32] {
        self.snapshot_digest
    }
    #[must_use]
    pub const fn manifest_digest(&self) -> [u8; 32] {
        self.manifest_digest
    }
    #[must_use]
    pub const fn current_rows_digest(&self) -> [u8; 32] {
        self.current_rows_digest
    }
    #[must_use]
    pub const fn current_rows(&self) -> u64 {
        self.current_rows
    }

    pub fn canonical_bytes(&self) -> Result<Vec<u8>, StoreError> {
        let bytes = serde_json::to_vec(self).map_err(|_| StoreError::Invalid)?;
        if bytes.len() > MANIFEST_BYTES {
            return Err(StoreError::Capacity);
        }
        Ok(bytes)
    }
    pub fn digest(&self) -> Result<[u8; 32], StoreError> {
        let mut digest = Sha256::new();
        digest.update(b"latent-original-recovery-window-v2\0");
        digest.update(self.canonical_bytes()?);
        Ok(digest.finalize().into())
    }
}

fn pair(
    before: &NamespaceSnapshot,
    now: NamespaceSnapshot,
) -> Result<NamespaceRecoveryWindow, SnapshotError> {
    let (record, original) = before.decode().map_err(SnapshotError::Review)?;
    let (current, history) = now.decode().map_err(SnapshotError::source)?;
    if record.tenant != current.tenant
        || record.id != current.id
        || record.version.incarnation != current.version.incarnation
        || record.version.generation > current.version.generation
        || record.status != current.status
    {
        return Err(SnapshotError::Review(StoreError::Conflict));
    }
    let proposed = original
        .restored_after(&history)
        .map_err(|error| match error {
            crate::namespace::NamespaceError::Capacity => SnapshotError::Capacity,
            _ => SnapshotError::Review(StoreError::Conflict),
        })?
        .encode()
        .map_err(|_| SnapshotError::Capacity)?;
    Ok(NamespaceRecoveryWindow {
        snapshot: before.clone(),
        current: now,
        proposed,
    })
}

fn check(
    deadline: Instant,
    current: &mut impl FnMut() -> Result<(), StoreError>,
) -> Result<(), SnapshotError> {
    checkpoint(deadline).map_err(|_| SnapshotError::Deadline)?;
    current().map_err(|error| {
        if error == StoreError::SnapshotExpired {
            SnapshotError::Deadline
        } else {
            SnapshotError::Review(error)
        }
    })
}

#[cfg(test)]
mod tests;
