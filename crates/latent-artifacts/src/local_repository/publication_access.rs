//! Exact publication reads share the catalog's one owner and bounded index.

use super::*;
use crate::{
    ArtifactCatalogEntry, LifecycleScope, PublicationRef, PublicationSelector,
    ReleaseOperationReceipt,
};
use latent_core::PublicationId;

impl DirectoryArtifactRepository {
    pub(super) fn publication_content_files<'a>(
        &self,
        prepared: &'a PreparedPublication,
        admission: Option<&'a admission_storage::PreparedAdmissionFiles>,
        completion: &'a [u8],
    ) -> Result<Vec<(&'a str, &'a [u8])>, PlatformError> {
        let count = 4usize
            .checked_add(admission.map_or(0, |files| files.content_file_count()))
            .filter(|count| *count <= self.config.max_publication_files)
            .ok_or_else(|| resource_exhausted("publication-file-count-limit"))?;
        let mut files = Vec::new();
        files
            .try_reserve_exact(count)
            .map_err(|_| resource_exhausted("publication-file-allocation"))?;
        files.extend([
            (METADATA_FILE, prepared.metadata_bytes.as_slice()),
            (MANIFEST_FILE, prepared.manifest_bytes.as_slice()),
            (COMPONENT_FILE, prepared.artifact.component_bytes.as_slice()),
        ]);
        if let Some(admission) = admission {
            admission.append_content_files(&mut files);
        }
        files.push((COMPLETE_FILE, completion));
        Ok(files)
    }

    pub fn publication_storage_snapshot(
        &self,
    ) -> Result<PublicationStorageSnapshot, PlatformError> {
        Ok(self.content.lock().map_err(lock_error)?.snapshot())
    }

    /// Bounded maintenance of uncommitted leftovers and zero-reference blobs.
    /// Committed, revoked and retired publications keep their content/history pins.
    pub fn reclaim_uncommitted_content(
        &self,
        maximum: usize,
    ) -> Result<PublicationContentReclamation, PlatformError> {
        if maximum == 0 || maximum > 1024 {
            return Err(resource_exhausted("publication-reclamation-batch-limit"));
        }
        let _work = self
            .admission_work
            .try_lock()
            .map_err(|_| resource_exhausted("admission-work-busy"))?;
        let mut result = PublicationContentReclamation::default();
        self.life_store().with_exclusive(&mut |_fence| {
            let mut writer = self.publish_lock.lock().map_err(lock_error)?;
            if writer.pending.is_some() {
                return Err(error(
                    PlatformErrorCode::Unavailable,
                    "catalog-publication-reopen-required",
                ));
            }
            let ids = self.index.read().map_err(lock_error)?.pending_ids(maximum);
            for id in ids {
                if self.life_store().record_publication(&id)?.is_some() {
                    return Err(corrupt("committed-publication-cannot-be-reclaimed"));
                }
                self.content
                    .lock()
                    .map_err(lock_error)?
                    .forget_uncommitted(&id, &self.publication_path(&id))?;
                self.index
                    .write()
                    .map_err(lock_error)?
                    .forget_pending(&id)?;
                writer.release_directories = writer
                    .release_directories
                    .checked_sub(1)
                    .ok_or_else(|| corrupt("publication-directory-accounting"))?;
                result.publications += 1;
            }
            if result.publications < maximum {
                let blobs = self
                    .content
                    .lock()
                    .map_err(lock_error)?
                    .reclaim(maximum - result.publications)?;
                result.blobs = blobs.blobs;
                result.unlinked_blob_bytes = blobs.unlinked_blob_bytes;
            }
            Ok(())
        })?;
        Ok(result)
    }

    /// The trusted adapter must authorize `scope` before invoking this lookup.
    /// Foreign references appear absent; legacy selection never skips revoked rows.
    pub fn resolve_publication(
        &self,
        scope: &LifecycleScope,
        selector: &PublicationSelector,
    ) -> Result<Option<PublicationRef>, PlatformError> {
        scope.validate()?;
        let index = self.index.read().map_err(lock_error)?;
        let entry = match selector {
            PublicationSelector::Publication(reference) => {
                if &reference.scope != scope {
                    return Err(error(
                        PlatformErrorCode::InvalidArgument,
                        "publication-selector-scope-mismatch",
                    ));
                }
                index.exact(reference)?
            }
            PublicationSelector::LegacyComponent(component) => {
                index.legacy_component(Some(scope), component)?
            }
        };
        Ok(entry.map(|entry| entry.publication.clone()))
    }

    pub fn publication_catalog_entry(
        &self,
        publication: &PublicationRef,
    ) -> Result<Option<ArtifactCatalogEntry>, PlatformError> {
        let index = self.index.read().map_err(lock_error)?;
        let Some(entry) = index.exact(publication)? else {
            return Ok(None);
        };
        if entry.page_bytes > self.config.max_page_bytes {
            return Err(resource_exhausted("artifact-page-byte-limit"));
        }
        Ok(Some(entry.value.clone()))
    }

    pub(super) fn require_legacy_publication(
        &self,
        scope: Option<&LifecycleScope>,
        component: &ReleaseDigest,
    ) -> Result<PublicationRef, PlatformError> {
        let index = self.index.read().map_err(lock_error)?;
        index
            .legacy_component(scope, component)?
            .map(|entry| entry.publication.clone())
            .ok_or_else(|| error(PlatformErrorCode::NotFound, "release digest not found"))
    }

    pub(super) fn publication_path(&self, id: &PublicationId) -> PathBuf {
        self.root.join(RELEASES_DIR).join(id.hex())
    }

    #[cfg(test)]
    pub(super) fn local_publication_ref(
        &self,
        artifact: &CapsuleArtifact,
    ) -> Result<PublicationRef, PlatformError> {
        let metadata = encode_metadata(artifact, self.config.max_metadata_bytes)?;
        let manifest = self
            .codec
            .encode_capsule(&artifact.manifest)
            .map_err(|_| corrupt("capsule-manifest-encoding"))?;
        let completion =
            CompletionRecord::from_payloads(&artifact.descriptor, &metadata, &manifest);
        PublicationRef::trusted_local(
            artifact
                .manifest
                .metadata
                .tenant
                .clone()
                .map_or(LifecycleScope::LocalUnscoped, LifecycleScope::Tenant),
            &completion.identity()?,
        )
    }

    pub(super) fn operation_publication_ref(
        &self,
        receipt: &ReleaseOperationReceipt,
    ) -> Result<PublicationRef, PlatformError> {
        let id = self
            .life_store()
            .operation_publication(&receipt.scope, &receipt.operation_id)?
            .ok_or_else(|| corrupt("operation-publication-history-missing"))?;
        let reference = PublicationRef {
            id,
            scope: receipt.scope.clone(),
        };
        let index = self.index.read().map_err(lock_error)?;
        let entry = index
            .exact(&reference)?
            .ok_or_else(|| corrupt("operation-publication-missing"))?;
        if receipt.component_digest.as_ref() != Some(&entry.value.descriptor.release_digest) {
            return Err(corrupt("operation-publication-association"));
        }
        Ok(reference)
    }

    /// A sealed lifecycle grant for one publication. Content identity never supplies it.
    pub fn publication_execution_eligibility(
        &self,
        reference: &PublicationRef,
    ) -> Result<crate::ReleaseUseEligibility, PlatformError> {
        let mut result = None;
        self.life_store().with_current(&mut |fence| {
            let proof = {
                let index = self.index.read().map_err(lock_error)?;
                let entry = index
                    .exact(reference)?
                    .ok_or_else(|| error(PlatformErrorCode::NotFound, "publication not found"))?;
                entry.eligibility.clone()
            };
            if self.admission.is_some() && proof.is_none() {
                return Err(error(
                    PlatformErrorCode::PermissionDenied,
                    "release-is-not-currently-eligible",
                ));
            }
            let token = fence.publication_eligibility(&reference.id, proof)?;
            token.check_current()?;
            result = Some(token);
            Ok(())
        })?;
        result.ok_or_else(|| corrupt("missing-catalog-execution-snapshot"))
    }

    pub(super) fn verify_publication_index(
        &self,
        reference: &PublicationRef,
        verified: &VerifiedEntry,
    ) -> Result<(), PlatformError> {
        if &verified.publication != reference {
            return Err(corrupt("publication-content-association-changed"));
        }
        if let Some(lifecycle) = self.lifecycle.get() {
            let expected = lifecycle
                .identity_publication(&reference.id)?
                .ok_or_else(|| corrupt("lifecycle-membership-missing"))?;
            if expected.completion != verified.completion.identity()?
                || expected.publication()? != *reference
            {
                return Err(corrupt("stored-content-changed-after-lifecycle-adoption"));
            }
        }
        if self.admission.is_some() {
            let index = self.index.read().map_err(lock_error)?;
            let entry = index
                .exact(reference)?
                .ok_or_else(|| corrupt("admission-index-history-missing"))?;
            if entry.admission_completion != Some(verified.completion.identity()?) {
                return Err(corrupt("stored-admission-changed-after-adoption"));
            }
        }
        Ok(())
    }

    /// Reads one currently eligible publication without globally resolving its component.
    pub fn fetch_publication(
        &self,
        reference: &PublicationRef,
    ) -> Result<CapsuleArtifact, PlatformError> {
        self.publication_execution_eligibility(reference)?;
        let verified =
            self.load_complete_entry(&self.publication_path(&reference.id), Retention::Component)?;
        self.verify_publication_index(reference, &verified)?;
        self.publication_execution_eligibility(reference)?;
        let (descriptor, manifest, contracts) = verified.metadata.into_parts();
        Ok(CapsuleArtifact {
            descriptor,
            manifest,
            contracts,
            component_bytes: verified.component_bytes,
        })
    }
}
