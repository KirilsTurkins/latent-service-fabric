use super::{
    recipe, AggregateMigrationProgress, AggregateMigrationRecipe, AggregateMigrationRequest,
    MigrationError, PROGRESS_BYTES,
};
use crate::{
    embedded::{ExpectedRow, ReadView, RowKey, StoreError},
    recovery::snapshot::{self, RequiredArtifact, SnapshotClosure, SnapshotReceipt},
};
use sha2::{Digest, Sha256};
use std::{
    io::{Read, Seek},
    time::Instant,
};

/// Constructed only from the exact bounded file with installed original row,
/// linked-work and immutable artifact reviewers on the same physical worker.
pub struct VerifiedMigrationCheckpoint {
    receipt: SnapshotReceipt,
}

impl VerifiedMigrationCheckpoint {
    pub fn inspect(
        view: &ReadView,
        input: &mut (impl Read + Seek),
        deadline: Instant,
        row: impl FnMut(&RowKey, &[u8]) -> Result<(), StoreError>,
        linked: impl FnOnce(&ReadView) -> Result<SnapshotClosure, MigrationError>,
        mut artifact: impl FnMut(&RequiredArtifact) -> Result<(), StoreError>,
    ) -> Result<Self, MigrationError> {
        let receipt =
            snapshot::inspect_snapshot(input, deadline, row).map_err(MigrationError::Review)?;
        linked(view)?
            .require_declared(&receipt.manifest.metadata)
            .map_err(MigrationError::Review)?;
        for required in &receipt.manifest.metadata.required_artifacts {
            artifact(required).map_err(MigrationError::Review)?;
        }
        if receipt.manifest.rows + 2 > snapshot::SNAPSHOT_ROWS
            || receipt.manifest.logical_bytes + PROGRESS_BYTES as u64 + 1024
                > snapshot::SNAPSHOT_LOGICAL_BYTES
        {
            return Err(MigrationError::Capacity);
        }
        Ok(Self { receipt })
    }

    #[must_use]
    pub fn receipt(&self) -> &SnapshotReceipt {
        &self.receipt
    }

    pub(super) fn require_request(
        &self,
        request: &AggregateMigrationRequest,
        recipe: AggregateMigrationRecipe,
    ) -> Result<(), StoreError> {
        let manifest = &self.receipt.manifest;
        // Snapshot actor metadata is descriptive; the whole-unit namespace
        // roster supplies the exact requested tenant/namespace/incarnation.
        if self.receipt.snapshot_digest != request.checkpoint_digest
            || self.receipt.manifest_digest != request.checkpoint_manifest_digest
            || !manifest.namespaces.iter().any(|source| {
                source.decode().is_ok_and(|(n, _)| {
                    n.tenant == request.scope.tenant
                        && n.id == request.scope.namespace
                        && n.version.incarnation == request.scope.incarnation
                })
            })
        {
            return Err(StoreError::Conflict);
        }
        let (v1, v2) = recipe::schema_ids()?;
        let required = [
            RequiredArtifact {
                identity: recipe.identity().into(),
                digest: recipe.digest(),
            },
            RequiredArtifact {
                identity: package_identity(&request.package_digest),
                digest: request.package_digest,
            },
            RequiredArtifact {
                identity: v1.as_str().into(),
                digest: recipe::schema_definitions()[0].1,
            },
            RequiredArtifact {
                identity: v2.as_str().into(),
                digest: recipe::schema_definitions()[1].1,
            },
        ];
        if required
            .iter()
            .any(|artifact| !manifest.metadata.required_artifacts.contains(artifact))
        {
            return Err(StoreError::UnsupportedFormat);
        }
        if !manifest
            .metadata
            .decoder_formats
            .contains(&super::retained_format())
        {
            return Err(StoreError::UnsupportedFormat);
        }
        Ok(())
    }

    pub(super) fn require_current(
        &self,
        view: &ReadView,
        prior: Option<(&AggregateMigrationProgress, &[u8])>,
        key: &RowKey,
        deadline: Instant,
    ) -> Result<(), StoreError> {
        if let Some((progress, bytes)) = prior {
            super::accounting::require_staged(view, key, bytes, progress)?;
        }
        let replacements = prior
            .map(|(progress, _)| -> Result<[ExpectedRow; 2], StoreError> {
                Ok([
                    progress.history_expectation()?,
                    progress.quota_expectation(false)?,
                ])
            })
            .transpose()?;
        let summary = normalized(view, deadline, prior.map(|_| key), replacements.as_ref())?;
        let manifest = &self.receipt.manifest;
        if summary.rows != manifest.rows
            || summary.logical_bytes != manifest.logical_bytes
            || summary.digest != manifest.rows_digest
        {
            return Err(StoreError::Conflict);
        }
        Ok(())
    }
}

fn normalized(
    view: &ReadView,
    deadline: Instant,
    omit: Option<&RowKey>,
    replacements: Option<&[ExpectedRow; 2]>,
) -> Result<snapshot::RowSummary, StoreError> {
    let mut hash = Sha256::new();
    let mut rows = 0u64;
    let mut logical_bytes = 0u64;
    snapshot::visit_view(view, deadline, |header, key, value| {
        if omit == Some(key) {
            return Ok(());
        }
        let original = replacements
            .into_iter()
            .flatten()
            .find(|old| old.key == *key);
        let value = match original {
            Some(old) => match old.value.as_deref() {
                Some(bytes) => bytes,
                None => return Ok(()),
            },
            None => value,
        };
        let normalized;
        let header = if original.is_some() {
            normalized = snapshot::row_header(key, value)?;
            &normalized
        } else {
            header
        };
        rows = rows.checked_add(1).ok_or(StoreError::Capacity)?;
        logical_bytes = logical_bytes
            .checked_add((key.key.len() + value.len() + 1) as u64)
            .ok_or(StoreError::Capacity)?;
        for bytes in [&header[..], &key.key, value] {
            hash.update(bytes);
        }
        Ok(())
    })?;
    Ok(snapshot::RowSummary {
        rows,
        logical_bytes,
        digest: hash.finalize().into(),
    })
}

#[must_use]
pub fn package_identity(digest: &[u8; 32]) -> String {
    use std::fmt::Write as _;
    let mut value = String::from("package:sha256:");
    for byte in digest {
        write!(&mut value, "{byte:02x}").expect("bounded String");
    }
    value
}
