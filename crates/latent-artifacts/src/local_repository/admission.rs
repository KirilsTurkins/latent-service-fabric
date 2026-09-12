//! One configured authority gates every concrete repository reuse path.
pub(super) mod association;

use std::fs;
use std::path::Path;
use std::sync::Arc;

use latent_core::{PlatformError, PlatformErrorCode, ReleaseDigest, TenantId};

use super::{
    corrupt, error, lock_error, resource_exhausted, sync_dir, write_synced,
    DirectoryArtifactRepository, Retention, VerifiedEntry,
};
use crate::admission::EligibilityOwner;
use crate::{
    AdmissionAuthority, AdmissionBinding, AdmissionStorageLimits, ArtifactCatalogEntry,
    ReleaseEligibility, VerifiedAdmission,
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
        if let Some(lifecycle) = self.lifecycle.get() {
            lifecycle.retire();
        }
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
        if self.lifecycle.get().is_some() {
            return self
                .current_execution_eligibility(release)
                .map(|token| token.admission().cloned());
        }
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
        if let Some(lifecycle) = self.lifecycle.get() {
            let expected = lifecycle
                .identity(release)?
                .ok_or_else(|| corrupt("lifecycle-membership-missing"))?;
            if expected.completion != verified.completion.identity()? {
                return Err(corrupt("stored-content-changed-after-lifecycle-adoption"));
            }
        }
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
                        | PlatformErrorCode::IncompatibleContract
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

    pub(super) fn validate_verified(
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

    /// Explicit bounded control-plane proof refresh. The persisted lifecycle
    /// state and selected raw evidence remain unchanged; terminal rows deny it.
    pub fn reverify_retained(
        &self,
        tenant: &TenantId,
        release: &ReleaseDigest,
    ) -> Result<ArtifactCatalogEntry, PlatformError> {
        let _work = self
            .admission_work
            .try_lock()
            .map_err(|_| resource_exhausted("admission-work-busy"))?;
        self.admission.as_ref().ok_or_else(|| {
            error(
                PlatformErrorCode::PermissionDenied,
                "reverification-requires-enforced-mode",
            )
        })?;
        let row = self
            .life_store()
            .record(release)?
            .filter(|row| row.scope.tenant() == Some(tenant))
            .ok_or_else(|| error(PlatformErrorCode::NotFound, "release digest not found"))?;
        if row.state != crate::ReleaseLifecycleState::Admitted {
            return Err(error(
                PlatformErrorCode::PermissionDenied,
                "release-lifecycle-ineligible",
            ));
        }
        let destination = self.entry_path(release)?;
        let verified = self.load_complete_entry(&destination, Retention::Metadata)?;
        self.verify_admission_index(release, &verified)?;
        let token = if row.evidence_revision_digest.is_some() {
            self.recover_selected_evidence(&destination, &verified)?
        } else {
            self.recover_eligibility(&destination, &verified)?
                .and_then(|value| value.eligibility)
        }
        .ok_or_else(|| {
            error(
                PlatformErrorCode::PermissionDenied,
                "retained-admission-is-not-current",
            )
        })?;
        let summary = ArtifactCatalogEntry {
            descriptor: verified.metadata.descriptor().clone(),
            tenant: verified.metadata.manifest().metadata.tenant.clone(),
            service: latent_core::ServiceId(verified.metadata.manifest().metadata.name.clone()),
            semantic_version: verified.metadata.manifest().semantic_version.clone(),
            world: verified.metadata.manifest().world.clone(),
        };
        self.life_store().with_current(&mut |_fence| {
            let current = self
                .life_store()
                .record(release)?
                .ok_or_else(|| corrupt("lifecycle-record-missing"))?;
            if current != row {
                return Err(error(
                    PlatformErrorCode::StateConflict,
                    "release-generation-conflict",
                ));
            }
            token.with_current(&mut |check| {
                let _publication = self.publish_lock.lock().map_err(lock_error)?;
                let mut index = self.index.write().map_err(lock_error)?;
                check.check()?;
                index.install_selected_eligibility(
                    release,
                    Some(token.clone()),
                    verified.completion.identity()?,
                    self.config,
                )
            })
        })?;
        Ok(summary)
    }
}
