//! One configured authority gates every concrete repository reuse path.
mod association;

use std::fs;
use std::path::Path;
use std::sync::Arc;

use latent_core::{PlatformError, PlatformErrorCode, ReleaseDigest, TenantId};

use super::{
    admission_storage::PreparedAdmissionFiles, corrupt, error, lock_error, resource_exhausted,
    sync_dir, write_synced, DirectoryArtifactRepository, Retention, VerifiedEntry,
};
use crate::admission::EligibilityOwner;
use crate::{
    AdmissionAuthority, AdmissionBinding, AdmissionStorageLimits, ArtifactCatalogEntry,
    PackageAdmissionUpload, ReleaseEligibility, VerifiedAdmission,
};

const MODE_FILE: &str = "ADMISSION_MODE";
const MODE: &[u8] = b"lsf-enforced-admission-v1\n";

pub(super) struct RepositoryAdmission {
    pub(super) authority: Arc<dyn AdmissionAuthority>,
    pub(super) owner: Arc<EligibilityOwner>,
    pub(super) limits: AdmissionStorageLimits,
}
impl RepositoryAdmission {
    pub(super) fn new(
        authority: Arc<dyn AdmissionAuthority>,
        limits: AdmissionStorageLimits,
    ) -> Self {
        Self {
            owner: Arc::new(EligibilityOwner::new(Arc::clone(&authority))),
            authority,
            limits,
        }
    }
}
pub(super) struct RecoveredAdmission {
    pub(super) binding: AdmissionBinding,
    pub(super) eligibility: Option<ReleaseEligibility>,
}

pub(super) fn check_mode(root: &Path, enforced: bool) -> Result<(), PlatformError> {
    let path = root.join(MODE_FILE);
    let metadata = match fs::symlink_metadata(&path) {
        Ok(metadata) => Some(metadata),
        Err(failure) if failure.kind() == std::io::ErrorKind::NotFound => None,
        Err(failure) => return Err(super::io_error(failure)),
    };
    if let Some(metadata) = metadata {
        if !metadata.file_type().is_file()
            || super::read_bounded_file(&path, 64, "admission mode")? != MODE
        {
            return Err(corrupt("invalid-admission-mode-marker"));
        }
        #[cfg(windows)]
        {
            use std::os::windows::fs::MetadataExt;
            if metadata.file_attributes() & 0x400 != 0 {
                return Err(corrupt("linked-admission-mode-marker"));
            }
        }
        if !enforced {
            return Err(error(
                PlatformErrorCode::PermissionDenied,
                "enforced-catalog-requires-admission-authority",
            ));
        }
    }
    Ok(())
}
pub(super) fn persist_mode(root: &Path) -> Result<(), PlatformError> {
    let path = root.join(MODE_FILE);
    if !path.exists() {
        write_synced(&path, MODE)?;
    }
    sync_dir(root)
}

impl Drop for DirectoryArtifactRepository {
    fn drop(&mut self) {
        if let Some(admission) = &self.admission {
            admission.owner.retire();
        }
    }
}

impl DirectoryArtifactRepository {
    pub(super) fn current_eligibility(
        &self,
        release: &ReleaseDigest,
    ) -> Result<Option<ReleaseEligibility>, PlatformError> {
        if self.admission.is_none() {
            return Ok(None);
        }
        let token = {
            let index = self.index.read().map_err(lock_error)?;
            let entry = index
                .by_digest
                .get(release)
                .ok_or_else(|| error(PlatformErrorCode::NotFound, "release digest not found"))?;
            entry.eligibility.clone().ok_or_else(|| {
                error(
                    PlatformErrorCode::PermissionDenied,
                    "release-is-not-currently-eligible",
                )
            })?
        };
        token.check_current()?;
        Ok(Some(token))
    }

    pub(super) fn verify_admission_index(
        &self,
        release: &ReleaseDigest,
        verified: &VerifiedEntry,
    ) -> Result<(), PlatformError> {
        if self.admission.is_none() {
            return Ok(());
        }
        let expected = self
            .index
            .read()
            .map_err(lock_error)?
            .by_digest
            .get(release)
            .and_then(|entry| entry.admission_completion)
            .ok_or_else(|| corrupt("admission-index-history-missing"))?;
        if expected != verified.completion.identity()? {
            return Err(corrupt("stored-admission-changed-after-adoption"));
        }
        Ok(())
    }

    pub(super) fn recover_eligibility(
        &self,
        path: &Path,
        verified: &VerifiedEntry,
    ) -> Result<Option<RecoveredAdmission>, PlatformError> {
        let Some(config) = &self.admission else {
            return Ok(None);
        };
        let stored = verified
            .admission
            .as_ref()
            .ok_or_else(|| corrupt("admission-record-missing"))?;
        let binding = stored.binding(path, config.limits)?;
        let upload = stored.upload(path, config.limits, self.config.max_component_bytes)?;
        association::verify(&binding, &upload, &verified.metadata, &self.codec)?;
        let recovered = config.authority.recover(&binding, upload);
        let eligibility = match recovered {
            Ok(value) => {
                self.validate_verified(&binding.tenant, &value)?;
                if value.grant.binding() != &binding
                    || value.artifact.descriptor != *verified.metadata.descriptor()
                    || value.artifact.manifest != *verified.metadata.manifest()
                    || value.artifact.contracts != verified.metadata.contracts()
                {
                    return Err(corrupt("recovered-admission-association"));
                }
                Some(ReleaseEligibility::new(
                    value.grant,
                    Arc::clone(&config.owner),
                ))
            }
            Err(failure)
                if matches!(
                    failure.code,
                    PlatformErrorCode::PermissionDenied
                        | PlatformErrorCode::StateConflict
                        | PlatformErrorCode::Unavailable
                ) =>
            {
                None
            }
            Err(failure) => return Err(failure),
        };
        Ok(Some(RecoveredAdmission {
            binding,
            eligibility,
        }))
    }

    fn validate_verified(
        &self,
        tenant: &TenantId,
        value: &VerifiedAdmission,
    ) -> Result<(), PlatformError> {
        let config = self
            .admission
            .as_ref()
            .ok_or_else(|| corrupt("admission-mode-missing"))?;
        config.limits.check_binding(value.grant.binding())?;
        config
            .limits
            .check_upload(&value.upload, self.config.max_component_bytes)?;
        if value.grant.retained_bytes() > config.limits.max_grant_bytes {
            return Err(resource_exhausted("admission-grant-retention-limit"));
        }
        if &value.grant.binding().tenant != tenant
            || value.artifact.manifest.metadata.tenant.as_ref() != Some(tenant)
            || value.grant.binding().release != value.artifact.descriptor.release_digest
            || value.artifact.descriptor.publisher.is_none()
        {
            return Err(corrupt("verified-admission-association"));
        }
        Ok(())
    }

    pub(super) fn admit_sync(
        &self,
        tenant: &TenantId,
        upload: PackageAdmissionUpload,
        preflight: &mut (dyn FnMut(&ArtifactCatalogEntry) -> Result<(), PlatformError> + Send),
    ) -> Result<ArtifactCatalogEntry, PlatformError> {
        let _work = self
            .admission_work
            .try_lock()
            .map_err(|_| resource_exhausted("admission-work-busy"))?;
        let config = self.admission.as_ref().ok_or_else(|| {
            error(
                PlatformErrorCode::PermissionDenied,
                "package-admission-requires-enforced-mode",
            )
        })?;
        config
            .limits
            .check_upload(&upload, self.config.max_component_bytes)?;
        let verified = config.authority.verify(tenant, upload)?;
        self.validate_verified(tenant, &verified)?;
        let VerifiedAdmission {
            artifact,
            upload,
            grant,
        } = verified;
        let files = PreparedAdmissionFiles::prepare(
            grant.binding(),
            upload,
            &artifact,
            config.limits,
            self.config.max_component_bytes,
        )?;
        let mut prepared = self.prepare_publication(artifact)?;
        let summary = summary(&prepared.artifact);
        // Rejection-only user callback: no authority, publication or index lock.
        preflight(&summary)?;
        let release = prepared.artifact.descriptor.release_digest.clone();
        let destination = self.entry_path(&release)?;
        let mut staging = None;
        let (eligibility, completion) = if destination.exists() {
            let existing = self.load_complete_entry(&destination, Retention::Metadata)?;
            if !prepared.completion.same_artifact(&existing.completion)
                || !files.same_upload(
                    existing
                        .admission
                        .as_ref()
                        .ok_or_else(|| corrupt("admission-record-missing"))?,
                )
            {
                return Err(error(
                    PlatformErrorCode::AlreadyExists,
                    "release contains different package or evidence",
                ));
            }
            let recovered = self
                .recover_eligibility(&destination, &existing)?
                .ok_or_else(|| corrupt("admission-recovery-missing"))?;
            let token = recovered.eligibility.ok_or_else(|| {
                error(
                    PlatformErrorCode::PermissionDenied,
                    "retained-admission-is-not-current",
                )
            })?;
            (token, existing.completion)
        } else {
            prepared.completion.bind_admission(&files.record_bytes);
            self.index.read().map_err(lock_error)?.preflight_admission(
                &prepared.artifact.descriptor,
                &prepared.artifact.manifest,
                grant.binding(),
                prepared.completion.identity()?,
                grant.retained_bytes().saturating_add(256),
                self.config,
            )?;
            staging = Some(Staged(
                self.stage_publication_with_admission(&prepared, Some(&files))?,
            ));
            (
                ReleaseEligibility::new(grant, Arc::clone(&config.owner)),
                prepared.completion.clone(),
            )
        };
        let super::PreparedPublication { artifact, .. } = prepared;
        let crate::CapsuleArtifact {
            descriptor,
            manifest,
            ..
        } = artifact;
        drop(files);
        self.commit_admission(
            &destination,
            staging.as_ref().map(|value| value.0.as_path()),
            &completion,
            &eligibility,
            &descriptor,
            &manifest,
        )?;
        Ok(summary)
    }

    fn commit_admission(
        &self,
        destination: &Path,
        staged: Option<&Path>,
        expected: &super::CompletionRecord,
        eligibility: &ReleaseEligibility,
        descriptor: &crate::ArtifactDescriptor,
        manifest: &latent_manifest::CapsuleManifest,
    ) -> Result<(), PlatformError> {
        let release = eligibility.release();
        eligibility.with_current(&mut |check| {
            let mut publication = self.publish_lock.lock().map_err(lock_error)?;
            if publication
                .pending
                .as_ref()
                .is_some_and(|pending| pending != release)
            {
                return Err(error(
                    PlatformErrorCode::Unavailable,
                    "catalog-needs-pending-admission-recovery",
                ));
            }
            self.index.read().map_err(lock_error)?.preflight_admission(
                descriptor,
                manifest,
                eligibility.binding(),
                expected.identity()?,
                eligibility.retained_bytes(),
                self.config,
            )?;
            check.check()?;
            if let Some(staged) = staged {
                if destination.exists() {
                    return Err(error(
                        PlatformErrorCode::StateConflict,
                        "concurrent-admission-retry-required",
                    ));
                }
                if publication.release_directories >= self.config.max_recovery_directories {
                    return Err(resource_exhausted(
                        "catalog recovery directory capacity reached",
                    ));
                }
                check.check()?;
                fs::rename(staged, destination).map_err(super::io_error)?;
                publication.release_directories += 1;
                publication.pending = Some(release.clone());
                #[cfg(test)]
                super::integrity::faults::after_rename(destination);
            }
            publication.pending = Some(release.clone());
            let verified = self.load_complete_entry(destination, Retention::Metadata)?;
            if &verified.completion != expected {
                return Err(corrupt("admission-completion-changed"));
            }
            #[cfg(test)]
            if self
                .fail_parent_sync_once
                .swap(false, std::sync::atomic::Ordering::SeqCst)
            {
                return Err(error(
                    PlatformErrorCode::Internal,
                    "injected parent-directory sync failure after rename",
                ));
            }
            sync_dir(&self.root.join(super::RELEASES_DIR))?;
            let stamp = self.preparation_stamp(&verified.metadata);
            let mut index = self.index.write().map_err(lock_error)?;
            // Reuse the already-held fence; do not acquire authority while the
            // index is held. Waiting for existing catalog readers must not leave
            // the post-sync currentness sample stale before adoption.
            check.check()?;
            index.insert_admitted(
                verified.metadata,
                stamp,
                eligibility.binding().clone(),
                Some(eligibility.clone()),
                expected.identity()?,
                self.config,
            )?;
            publication.pending = None;
            Ok(())
        })
    }

    /// Explicit control-plane revalidation using original retained evidence.
    /// It refreshes only bounded process-local proof ownership, not stored bytes.
    pub fn reverify_retained(
        &self,
        tenant: &TenantId,
        release: &ReleaseDigest,
    ) -> Result<ArtifactCatalogEntry, PlatformError> {
        let _work = self
            .admission_work
            .try_lock()
            .map_err(|_| resource_exhausted("admission-work-busy"))?;
        let config = self.admission.as_ref().ok_or_else(|| {
            error(
                PlatformErrorCode::PermissionDenied,
                "reverification-requires-enforced-mode",
            )
        })?;
        {
            let index = self.index.read().map_err(lock_error)?;
            if index
                .by_digest
                .get(release)
                .and_then(|entry| entry.value.tenant.as_ref())
                != Some(tenant)
            {
                return Err(error(
                    PlatformErrorCode::NotFound,
                    "release digest not found",
                ));
            }
        }
        let destination = self.entry_path(release)?;
        let existing = self.load_complete_entry(&destination, Retention::Metadata)?;
        self.verify_admission_index(release, &existing)?;
        let recovered = self
            .recover_eligibility(&destination, &existing)?
            .ok_or_else(|| corrupt("admission-record-missing"))?;
        let token = recovered.eligibility.ok_or_else(|| {
            error(
                PlatformErrorCode::PermissionDenied,
                "retained-admission-is-not-current",
            )
        })?;
        if token.grant.retained_bytes() > config.limits.max_grant_bytes {
            return Err(resource_exhausted("admission-grant-retention-limit"));
        }
        let summary = ArtifactCatalogEntry {
            descriptor: existing.metadata.descriptor().clone(),
            tenant: existing.metadata.manifest().metadata.tenant.clone(),
            service: latent_core::ServiceId(existing.metadata.manifest().metadata.name.clone()),
            semantic_version: existing.metadata.manifest().semantic_version.clone(),
            world: existing.metadata.manifest().world.clone(),
        };
        self.commit_admission(
            &destination,
            None,
            &existing.completion,
            &token,
            existing.metadata.descriptor(),
            existing.metadata.manifest(),
        )?;
        Ok(summary)
    }
}

struct Staged(std::path::PathBuf);
impl Drop for Staged {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}
fn summary(artifact: &crate::CapsuleArtifact) -> ArtifactCatalogEntry {
    ArtifactCatalogEntry {
        descriptor: artifact.descriptor.clone(),
        tenant: artifact.manifest.metadata.tenant.clone(),
        service: latent_core::ServiceId(artifact.manifest.metadata.name.clone()),
        semantic_version: artifact.manifest.semantic_version.clone(),
        world: artifact.manifest.world.clone(),
    }
}
