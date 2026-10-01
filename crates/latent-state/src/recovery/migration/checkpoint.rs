use super::super::snapshot::{RequiredArtifact, SnapshotClosure, SnapshotReceipt};
use super::{
    schema_ids, AggregateMigrationProgress, AggregateMigrationRecipe, AggregateMigrationRequest,
    PROGRESS_BYTES, V1, V2,
};
use crate::embedded::RowKey;
use crate::embedded::{ReadView, StoreError};
use sha2::{Digest, Sha256};
use std::io::Read;
use std::time::Instant;

/// Created only by inspecting the exact bounded checkpoint stream with installed
/// row/artifact decoders. Public manifest descriptions are not this capability.
pub struct VerifiedMigrationCheckpoint {
    receipt: SnapshotReceipt,
}
impl VerifiedMigrationCheckpoint {
    pub fn inspect(
        view: &ReadView,
        input: &mut impl Read,
        deadline: Instant,
        row: impl FnMut(&RowKey, &[u8]) -> Result<(), StoreError>,
        linked: impl FnOnce(&ReadView) -> Result<SnapshotClosure, StoreError>,
        mut artifact: impl FnMut(&RequiredArtifact) -> Result<(), StoreError>,
    ) -> Result<Self, StoreError> {
        let receipt = super::super::snapshot::inspect_snapshot(input, deadline, row)?;
        linked(view)?.require_declared(&receipt.manifest.metadata)?;
        for required in &receipt.manifest.metadata.required_artifacts {
            artifact(required)?;
        }
        // Reserve marker/history headroom in the same bounded canonical walk.
        if receipt.manifest.rows + 2 > super::super::snapshot::SNAPSHOT_ROWS
            || receipt.manifest.logical_bytes + PROGRESS_BYTES as u64 + 1024
                > super::super::snapshot::SNAPSHOT_LOGICAL_BYTES
        {
            return Err(StoreError::Capacity);
        }
        Ok(Self { receipt })
    }
    #[must_use]
    pub fn receipt(&self) -> &SnapshotReceipt {
        &self.receipt
    }
    pub(super) fn require_request(
        &self,
        r: &AggregateMigrationRequest,
        selected: AggregateMigrationRecipe,
    ) -> Result<(), StoreError> {
        let m = &self.receipt.manifest;
        if self.receipt.snapshot_digest != r.checkpoint_digest
            || self.receipt.manifest_digest != r.checkpoint_manifest_digest
            || m.metadata.tenant != r.scope.tenant.0
        {
            return Err(StoreError::Conflict);
        }
        let (v1, v2) = schema_ids()?;
        let recipe = RequiredArtifact {
            identity: selected.identity().into(),
            digest: selected.digest(),
        };
        let package = RequiredArtifact {
            identity: package_identity(&r.package_digest),
            digest: r.package_digest,
        };
        if !m.metadata.required_artifacts.contains(&recipe)
            || !m.metadata.required_artifacts.contains(&package)
            || [(v1, V1), (v2, V2)].iter().any(|(s, bytes)| {
                !m.metadata.required_artifacts.contains(&RequiredArtifact {
                    identity: s.as_str().into(),
                    digest: Sha256::digest(bytes).into(),
                })
            })
        {
            return Err(StoreError::UnsupportedFormat);
        }
        Ok(())
    }
    pub(super) fn require_current(
        &self,
        view: &ReadView,
        prior: Option<&AggregateMigrationProgress>,
        progress_key: &RowKey,
        deadline: Instant,
    ) -> Result<(), StoreError> {
        let before_history = prior
            .map(AggregateMigrationProgress::history_expectation)
            .transpose()?;
        let mut hash = Sha256::new();
        let mut rows = 0u64;
        let mut logical = 0u64;
        super::super::snapshot::visit_view(view, deadline, |header, key, value| {
            if prior.is_some() && key == progress_key {
                return Ok(());
            }
            let bytes = match &before_history {
                Some(before) if key == &before.key => match &before.value {
                    Some(bytes) => bytes.as_slice(),
                    None => return Ok(()),
                },
                _ => value,
            };
            // Reuse the snapshot header codec when normalizing only the staged
            // history marker; every other original linked row is unchanged.
            let normalized;
            let header = if bytes == value {
                header
            } else {
                normalized = super::super::snapshot::row_header(key, bytes)?;
                &normalized
            };
            rows = rows.checked_add(1).ok_or(StoreError::Capacity)?;
            logical = logical
                .checked_add((key.key.len() + bytes.len() + 1) as u64)
                .ok_or(StoreError::Capacity)?;
            for slice in [&header[..], key.key.as_slice(), bytes] {
                hash.update(slice);
            }
            Ok(())
        })?;
        let m = &self.receipt.manifest;
        let digest: [u8; 32] = hash.finalize().into();
        if rows != m.rows || logical != m.logical_bytes || digest != m.rows_digest {
            return Err(StoreError::Conflict);
        }
        Ok(())
    }
}

#[must_use]
pub fn package_identity(digest: &[u8; 32]) -> String {
    use std::fmt::Write as _;
    let mut value = "package:sha256:".to_string();
    for byte in digest {
        write!(&mut value, "{byte:02x}").expect("bounded String");
    }
    value
}
