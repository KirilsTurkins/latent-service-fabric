//! One inverse route index and bounded HTTP/rollout checks under the real writer.
use super::{
    compiler::{CompiledCatalog, RecordIndex, RevisionRecord},
    DirectoryDeploymentRepository,
};
use latent_artifacts::{
    DirectoryArtifactRepository, LifecycleAuthorityHandle, PublicationRef,
    PublicationReferenceAuthority, MAX_PUBLICATION_RETENTION_BATCH,
};
use latent_core::{PlatformError, PlatformErrorCode};
use std::sync::Arc;

pub(super) fn reference_index(
    records: &[Arc<RevisionRecord>],
) -> Result<Box<[RecordIndex]>, PlatformError> {
    // Compilation already bounds record count. Only positions are duplicated;
    // IDs/manifests remain in the shared immutable records. The caller charges
    // every retained position against the existing metadata budget.
    let mut index = Vec::new();
    index
        .try_reserve_exact(records.len())
        .map_err(|_| exhausted())?;
    for (position, record) in records.iter().enumerate() {
        if record.publication.is_some() {
            index.push(RecordIndex(position));
        }
    }
    index.sort_unstable_by(|a, b| records[a.0].publication.cmp(&records[b.0].publication));
    Ok(index.into_boxed_slice())
}
impl CompiledCatalog {
    fn references_publications(&self, publications: &[PublicationRef]) -> bool {
        publications.iter().any(|publication| {
            self.publication_references
                .binary_search_by(|position| {
                    self.records[position.0]
                        .publication
                        .as_ref()
                        .expect("indexed publication")
                        .cmp(&publication.id)
                })
                .is_ok()
        })
    }
}
impl DirectoryDeploymentRepository {
    /// Attach this exact native reference/commit authority. This does not enable
    /// deletion or grant the caller any tenant or administrative permission.
    pub fn bind_publication_reference_authority(
        self: &Arc<Self>,
        artifacts: &DirectoryArtifactRepository,
    ) -> Result<(), PlatformError> {
        let authority: Arc<dyn PublicationReferenceAuthority> = self.clone();
        artifacts.install_publication_reference_authority(&authority)
    }
}
impl PublicationReferenceAuthority for DirectoryDeploymentRepository {
    fn catalog_authority(&self) -> Result<LifecycleAuthorityHandle, PlatformError> {
        self.lifecycle.clone().ok_or_else(unavailable)
    }
    fn with_unreferenced_publications(
        &self,
        owner: &LifecycleAuthorityHandle,
        publications: &[PublicationRef],
        action: &mut dyn FnMut(u64) -> Result<(), PlatformError>,
    ) -> Result<(), PlatformError> {
        if !self.is_bound_to_catalog(owner) {
            return Err(unavailable());
        }
        if publications.is_empty()
            || publications.len() > MAX_PUBLICATION_RETENTION_BATCH
            || publications.windows(2).any(|pair| pair[0].id >= pair[1].id)
        {
            return Err(super::error(
                PlatformErrorCode::InvalidArgument,
                "publication-deletion-targets-invalid",
            ));
        }
        for publication in publications {
            publication.scope.validate()?;
        }
        // Other commits may already hold a lifecycle/web read fence while
        // waiting for this writer. Never block or reverse that lock order.
        let _writer = self.writer.try_lock().map_err(|_| unavailable())?;
        let current = self.current.try_read().map_err(|_| unavailable())?;
        if !current.confirmed {
            return Err(unavailable());
        }
        if current.routes.publication_references.len() != current.routes.records.len()
            || current.rollouts.data.rows.iter().any(|row| {
                row.status.base.publication.is_none() || row.status.candidate.publication.is_none()
            })
        {
            return Err(unavailable());
        }
        if current.routes.references_publications(publications)
            || current.http.references_publications(publications)
            || current.rollouts.data.rows.iter().any(|row| {
                // All retained base/candidate choices are negative retention
                // references, even after terminal rollout state or revocation.
                [
                    &row.status.base.publication,
                    &row.status.candidate.publication,
                ]
                .into_iter()
                .flatten()
                .any(|id| publications.binary_search_by(|p| p.id.cmp(id)).is_ok())
            })
        {
            return Err(super::error(
                PlatformErrorCode::StateConflict,
                "publication-deletion-referenced",
            ));
        }
        // The HTTP and rollout table sizes are independently capped at 256 and
        // 1024. No desired-state scan, filesystem I/O or per-publication owner.
        action(current.transaction)
    }
}
fn unavailable() -> PlatformError {
    super::error(
        PlatformErrorCode::Unavailable,
        "publication-deletion-reference-authority-unavailable",
    )
}
fn exhausted() -> PlatformError {
    super::error(
        PlatformErrorCode::ResourceExhausted,
        "publication-reference-index-limit",
    )
}
