//! Current execution capability and permanently inactive desired-state rows.

use latent_artifacts::{
    ArtifactRepository, HistoricalExecutionState, LifecycleAuthorityHandle, ReleaseUseEligibility,
    VerifiedArtifactMetadata,
};
use latent_core::{PlatformError, PlatformErrorCode, ReleaseDigest, TenantId};
use latent_manifest::RuntimeCompatibilityProfile;

use super::super::{error, recovery_admission};

pub(super) enum Execution {
    Unmanaged,
    Eligible(ReleaseUseEligibility),
    Inactive(InactiveRelease),
}

/// No currentness update can turn this retained snapshot into a positive grant.
#[derive(Clone)]
pub(in crate::deployments) struct InactiveRelease {
    release: ReleaseDigest,
    owner: LifecycleAuthorityHandle,
    state: HistoricalExecutionState,
    failure: PlatformError,
}

impl InactiveRelease {
    pub fn release(&self) -> &ReleaseDigest {
        &self.release
    }

    pub fn check_owner(&self, owner: &LifecycleAuthorityHandle) -> Result<(), PlatformError> {
        if !self.owner.same_owner(owner) {
            return Err(error(
                PlatformErrorCode::PermissionDenied,
                "inactive-route-catalog-mismatch",
            ));
        }
        Ok(())
    }

    pub fn authorize_tenant(&self, tenant: &TenantId) -> Result<(), PlatformError> {
        match &self.state {
            HistoricalExecutionState::Eligible(token) => token.authorize_tenant(tenant),
            HistoricalExecutionState::Denied(denied) => denied.authorize_tenant(tenant),
            HistoricalExecutionState::Unmanaged => Err(error(
                PlatformErrorCode::PermissionDenied,
                "inactive-route-owner-missing",
            )),
        }
    }

    pub fn error(&self) -> PlatformError {
        self.failure.clone()
    }

    pub fn retained_bytes(&self) -> usize {
        let state = match &self.state {
            HistoricalExecutionState::Eligible(token) => token.retained_bytes(),
            HistoricalExecutionState::Denied(denied) => denied.retained_bytes(),
            HistoricalExecutionState::Unmanaged => 0,
        };
        std::mem::size_of::<Self>()
            .saturating_add(state)
            .saturating_add(self.release.0.capacity())
            .saturating_add(self.failure.message.capacity())
    }
}

pub(super) async fn load(
    artifacts: &dyn ArtifactRepository,
    release: &ReleaseDigest,
    recovery: bool,
    profile: Option<&RuntimeCompatibilityProfile>,
    lifecycle: Option<&LifecycleAuthorityHandle>,
) -> Result<(VerifiedArtifactMetadata, Execution), PlatformError> {
    let Some(owner) = lifecycle else {
        let metadata = recovery_admission::metadata(artifacts, release, recovery).await?;
        latent_manifest::check_runtime_compatibility(metadata.manifest(), profile)?;
        let token = recovery_admission::eligibility(artifacts, release, recovery).await?;
        return Ok((
            metadata,
            token.map_or(Execution::Unmanaged, Execution::Eligible),
        ));
    };
    let retry = recovery_admission::Retry::new(recovery);
    let snapshot = loop {
        match artifacts.historical_execution_snapshot(release).await {
            Err(failure) if retry.pause(&failure).await => {}
            value => break value?,
        }
    };
    let (metadata, state) = snapshot.into_parts();
    let negative = match &state {
        HistoricalExecutionState::Unmanaged => {
            return Err(error(
                PlatformErrorCode::PermissionDenied,
                "route-lifecycle-required",
            ))
        }
        HistoricalExecutionState::Eligible(token) => {
            if token.release() != release {
                return Err(error(
                    PlatformErrorCode::CorruptArtifact,
                    "route-lifecycle-release-mismatch",
                ));
            }
            token.check_for_lifecycle(owner)?;
            None
        }
        HistoricalExecutionState::Denied(denied) => {
            if denied.release() != release {
                return Err(error(
                    PlatformErrorCode::CorruptArtifact,
                    "route-lifecycle-release-mismatch",
                ));
            }
            denied.check_for_catalog(owner)?;
            Some(denied.error().clone())
        }
    };
    let incompatible =
        match latent_manifest::check_runtime_compatibility(metadata.manifest(), profile) {
            Ok(()) => None,
            Err(failure) if failure.code == PlatformErrorCode::IncompatibleContract => {
                Some(failure)
            }
            Err(failure) => return Err(failure),
        };
    let execution = if let Some(failure) = negative.or(incompatible) {
        Execution::Inactive(InactiveRelease {
            release: release.clone(),
            owner: owner.clone(),
            state,
            failure,
        })
    } else if let HistoricalExecutionState::Eligible(token) = state {
        Execution::Eligible(token)
    } else {
        return Err(error(
            PlatformErrorCode::Internal,
            "historical-execution-state-missing",
        ));
    };
    Ok((metadata, execution))
}
