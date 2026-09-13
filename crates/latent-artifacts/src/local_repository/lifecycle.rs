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
            match self.life_store().record(&identity.release)? {
                None => self
                    .index
                    .write()
                    .map_err(lock_error)?
                    .remove_pending(&identity.release),
                Some(record) if record.evidence_revision_digest.is_some() => {
                    let destination = self.entry_path(&identity.release)?;
                    let verified = self.load_complete_entry(&destination, Retention::Metadata)?;
                    let proof = self.recover_selected_evidence(&destination, &verified)?;
                    self.index
                        .write()
                        .map_err(lock_error)?
                        .install_selected_eligibility(
                            &identity.release,
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
        let mut result = None;
        self.life_store().with_current(&mut |fence| {
            let proof = {
                let index = self.index.read().map_err(lock_error)?;
                let entry = index.by_digest.get(release).ok_or_else(|| {
                    error(PlatformErrorCode::NotFound, "release digest not found")
                })?;
                entry.eligibility.clone()
            };
            if self.admission.is_some() && proof.is_none() {
                return Err(error(
                    PlatformErrorCode::PermissionDenied,
                    "release-is-not-currently-eligible",
                ));
            }
            let token = fence.eligibility(release, proof)?;
            token.check_current()?;
            result = Some(token);
            Ok(())
        })?;
        result.ok_or_else(|| corrupt("missing-catalog-execution-snapshot"))
    }

    pub(super) fn historical_snapshot(
        &self,
        release: &ReleaseDigest,
    ) -> Result<HistoricalExecutionSnapshot, PlatformError> {
        if !self
            .index
            .read()
            .map_err(lock_error)?
            .by_digest
            .contains_key(release)
        {
            return Err(error(
                PlatformErrorCode::NotFound,
                "release digest not found",
            ));
        }
        let verified = self.load_complete_entry(&self.entry_path(release)?, Retention::Metadata)?;
        verified.metadata.verify_requested(release)?;
        self.verify_admission_index(release, &verified)?;
        let identity = self
            .life_store()
            .identity(release)?
            .ok_or_else(|| corrupt("lifecycle-membership-missing"))?;
        if identity.completion != verified.completion.identity()? {
            return Err(corrupt("lifecycle-content-changed"));
        }
        HistoricalExecutionSnapshot::directory(
            verified.metadata,
            self.lifecycle_authority(),
            self.current_execution_eligibility(release),
        )
    }

    pub(super) fn lifecycle_status(
        &self,
        scope: &LifecycleScope,
        release: &ReleaseDigest,
    ) -> Result<Option<ReleaseLifecycleStatus>, PlatformError> {
        scope.validate()?;
        let Some(record) = self
            .life_store()
            .record(release)?
            .filter(|value| &value.scope == scope)
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
            ReleaseLifecycleState::Admitted => match self.current_execution_eligibility(release) {
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
            },
        };
        Ok(Some(ReleaseLifecycleStatus {
            record,
            eligibility,
            eligibility_reason,
        }))
    }
}
