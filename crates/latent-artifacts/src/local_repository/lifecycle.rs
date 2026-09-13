//! Catalog integration for immutable content and separately mutable permission.
mod evidence;
pub(super) mod input;
mod mutations;
mod publication;
mod request;

use super::*;
use crate::lifecycle::{LifecycleIdentity, LifecycleStore};
use crate::{
    HistoricalExecutionSnapshot, LifecycleAuthorityHandle, LifecycleScope,
    ReleaseEligibilityReason, ReleaseLifecycleState, ReleaseLifecycleStatus,
    ReleaseLiveEligibility, ReleaseUseEligibility,
};

const LIFECYCLE_DIR: &str = "lifecycle";
const LIFECYCLE_MODE_FILE: &str = "LIFECYCLE_MODE";
const LIFECYCLE_MODE: &[u8] = b"lsf-release-lifecycle-v1\n";

impl DirectoryArtifactRepository {
    pub(super) fn life_store(&self) -> &LifecycleStore {
        self.lifecycle
            .get()
            .expect("lifecycle initialized before catalog exposure")
    }

    #[must_use]
    pub fn lifecycle_authority(&self) -> LifecycleAuthorityHandle {
        self.life_store().handle()
    }

    pub(super) fn initialize_lifecycle(
        &self,
        baseline: &[LifecycleIdentity],
    ) -> Result<(), PlatformError> {
        let path = self.root.join(LIFECYCLE_DIR);
        let marker = self.root.join(LIFECYCLE_MODE_FILE);
        let marker_exists = match fs::symlink_metadata(&marker) {
            Ok(_) => true,
            Err(failure) if failure.kind() == std::io::ErrorKind::NotFound => false,
            Err(failure) => return Err(io_error(failure)),
        };
        if marker_exists
            && (read_bounded_file(&marker, 64, "lifecycle mode")? != LIFECYCLE_MODE
                || !path.join("MODE").is_file())
        {
            return Err(corrupt("catalog-lifecycle-history-missing"));
        }
        let store = LifecycleStore::open(
            &path,
            self.lifecycle_limits,
            self.admission
                .as_ref()
                .map(|value| Arc::clone(&value.authority)),
            baseline,
        )?;
        self.lifecycle
            .set(store)
            .map_err(|_| corrupt("catalog-lifecycle-already-initialized"))?;
        if !marker_exists {
            let temporary = self.root.join("LIFECYCLE_MODE.next");
            if fs::symlink_metadata(&temporary).is_ok() {
                // This registered staging name never confers authority. A
                // bounded interrupted first-open write may be retried safely.
                read_bounded_file(&temporary, 64, "lifecycle mode staging")?;
                fs::remove_file(&temporary).map_err(io_error)?;
            }
            write_synced(&temporary, LIFECYCLE_MODE)?;
            fs::rename(&temporary, &marker).map_err(io_error)?;
            sync_dir(&self.root)?;
        }
        // COMPLETE proves content integrity. Only durable lifecycle membership
        // proves that the publication transaction committed.
        for identity in baseline {
            match self
                .life_store()
                .record_publication(&identity.publication()?.id)?
            {
                None => self
                    .index
                    .write()
                    .map_err(lock_error)?
                    .remove_pending(&identity.publication()?.id),
                Some(record) if record.evidence_revision_digest.is_some() => {
                    let destination = self.publication_path(&identity.publication()?.id);
                    let verified = self.load_complete_entry(&destination, Retention::Metadata)?;
                    let proof = self.recover_selected_evidence(&destination, &verified)?;
                    self.index
                        .write()
                        .map_err(lock_error)?
                        .install_selected_eligibility(
                            &identity.publication()?.id,
                            proof,
                            identity.completion,
                            self.config,
                        )?;
                }
                Some(_) => {}
            }
        }
        Ok(())
    }

    pub(super) fn current_execution_eligibility(
        &self,
        release: &ReleaseDigest,
    ) -> Result<ReleaseUseEligibility, PlatformError> {
        self.publication_execution_eligibility(&self.require_legacy_publication(None, release)?)
    }

    pub(super) fn historical_snapshot(
        &self,
        release: &ReleaseDigest,
    ) -> Result<HistoricalExecutionSnapshot, PlatformError> {
        self.selected_historical_snapshot(release, None)
    }

    pub(super) fn lifecycle_status(
        &self,
        scope: &LifecycleScope,
        release: &ReleaseDigest,
    ) -> Result<Option<ReleaseLifecycleStatus>, PlatformError> {
        let Some(reference) = self.resolve_publication(
            scope,
            &crate::PublicationSelector::LegacyComponent(release.clone()),
        )?
        else {
            return Ok(None);
        };
        self.publication_lifecycle_status(&reference)
    }

    pub fn publication_lifecycle_status(
        &self,
        reference: &crate::PublicationRef,
    ) -> Result<Option<ReleaseLifecycleStatus>, PlatformError> {
        if self.publication_catalog_entry(reference)?.is_none() {
            return Ok(None);
        }
        let Some(record) = self
            .life_store()
            .record_publication(&reference.id)?
            .filter(|r| r.scope == reference.scope)
        else {
            return Ok(None);
        };
        let (eligibility, eligibility_reason) = match record.state {
            ReleaseLifecycleState::Revoked => (
                ReleaseLiveEligibility::Denied,
                ReleaseEligibilityReason::Revoked,
            ),
            ReleaseLifecycleState::Retired => (
                ReleaseLiveEligibility::Denied,
                ReleaseEligibilityReason::Retired,
            ),
            ReleaseLifecycleState::Admitted => {
                match self.publication_execution_eligibility(reference) {
                    Ok(_) => (
                        ReleaseLiveEligibility::Eligible,
                        if self.admission.is_some() {
                            ReleaseEligibilityReason::Verified
                        } else {
                            ReleaseEligibilityReason::LocalEligible
                        },
                    ),
                    Err(failure) => match failure.code {
                        PlatformErrorCode::Unavailable | PlatformErrorCode::StateConflict => (
                            ReleaseLiveEligibility::Unknown,
                            ReleaseEligibilityReason::AuthorityUnavailable,
                        ),
                        PlatformErrorCode::IncompatibleContract => (
                            ReleaseLiveEligibility::Denied,
                            ReleaseEligibilityReason::RuntimeIncompatible,
                        ),
                        PlatformErrorCode::CorruptArtifact => (
                            ReleaseLiveEligibility::Denied,
                            ReleaseEligibilityReason::CorruptContent,
                        ),
                        _ => (
                            ReleaseLiveEligibility::Denied,
                            ReleaseEligibilityReason::PolicyDenied,
                        ),
                    },
                }
            }
        };
        Ok(Some(ReleaseLifecycleStatus {
            publication: Some(reference.id.clone()),
            record,
            eligibility,
            eligibility_reason,
        }))
    }
}
