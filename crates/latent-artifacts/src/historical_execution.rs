//! A sealed historical metadata read, explicitly separate from permission to run.

use latent_core::{PlatformError, PlatformErrorCode, ReleaseDigest, TenantId};

use crate::{
    LifecycleAuthorityHandle, LifecycleScope, ReleaseUseEligibility, VerifiedArtifactMetadata,
};

/// The default trait adapter has no catalog authority. Only a concrete catalog
/// constructs an eligible or denied snapshot from its verified immutable bytes.
pub struct HistoricalExecutionSnapshot {
    metadata: VerifiedArtifactMetadata,
    state: HistoricalExecutionState,
}

#[derive(Clone)]
pub enum HistoricalExecutionState {
    Unmanaged,
    Eligible(ReleaseUseEligibility),
    Denied(HistoricalReleaseDenial),
}

/// An owner-bound negative observation. It cannot be converted to a grant.
#[derive(Clone)]
pub struct HistoricalReleaseDenial {
    owner: LifecycleAuthorityHandle,
    scope: LifecycleScope,
    release: ReleaseDigest,
    failure: PlatformError,
}

impl HistoricalExecutionSnapshot {
    pub(crate) fn unmanaged(metadata: VerifiedArtifactMetadata) -> Self {
        Self {
            metadata,
            state: HistoricalExecutionState::Unmanaged,
        }
    }

    pub(crate) fn directory(
        metadata: VerifiedArtifactMetadata,
        owner: LifecycleAuthorityHandle,
        eligibility: Result<ReleaseUseEligibility, PlatformError>,
    ) -> Result<Self, PlatformError> {
        let scope = metadata
            .manifest()
            .metadata
            .tenant
            .clone()
            .map_or(LifecycleScope::LocalUnscoped, LifecycleScope::Tenant);
        let release = metadata.verified_digest().clone();
        let state = match eligibility {
            Ok(token) => {
                if token.release() != &release
                    || token.scope() != &scope
                    || !token.belongs_to_catalog(&owner)
                {
                    return Err(error(
                        PlatformErrorCode::CorruptArtifact,
                        "historical-execution-association-mismatch",
                    ));
                }
                HistoricalExecutionState::Eligible(token)
            }
            Err(failure) => {
                let message = match failure.code {
                    PlatformErrorCode::PermissionDenied => "historical-release-denied",
                    PlatformErrorCode::IncompatibleContract => "historical-release-incompatible",
                    PlatformErrorCode::Unavailable => "historical-release-unavailable",
                    PlatformErrorCode::StateConflict => "historical-release-stale",
                    // Missing/tampered/ill-formed content cannot become an inactive
                    // route that hides failure of the stored integrity contract.
                    _ => return Err(failure),
                };
                HistoricalExecutionState::Denied(HistoricalReleaseDenial {
                    owner,
                    scope,
                    release,
                    failure: error(failure.code, message),
                })
            }
        };
        Ok(Self { metadata, state })
    }

    #[must_use]
    pub fn metadata(&self) -> &VerifiedArtifactMetadata {
        &self.metadata
    }

    #[must_use]
    pub fn into_parts(self) -> (VerifiedArtifactMetadata, HistoricalExecutionState) {
        (self.metadata, self.state)
    }
}

impl HistoricalReleaseDenial {
    #[must_use]
    pub fn release(&self) -> &ReleaseDigest {
        &self.release
    }

    #[must_use]
    pub fn error(&self) -> &PlatformError {
        &self.failure
    }

    #[must_use]
    pub fn retained_bytes(&self) -> usize {
        let scope = match &self.scope {
            LifecycleScope::Tenant(tenant) => tenant.0.capacity(),
            LifecycleScope::LocalUnscoped => 0,
        };
        std::mem::size_of::<Self>()
            .saturating_add(128)
            .saturating_add(scope)
            .saturating_add(self.release.0.capacity())
            .saturating_add(self.failure.message.capacity())
    }

    /// Identity check only: a negative row never consults positive proof freshness.
    pub fn check_for_catalog(&self, owner: &LifecycleAuthorityHandle) -> Result<(), PlatformError> {
        if !self.owner.same_owner(owner) {
            return Err(error(
                PlatformErrorCode::PermissionDenied,
                "historical-catalog-owner-mismatch",
            ));
        }
        Ok(())
    }

    /// Checks scope for diagnostics. The caller must still return this denial.
    pub fn authorize_tenant(&self, tenant: &TenantId) -> Result<(), PlatformError> {
        match &self.scope {
            LifecycleScope::Tenant(expected) if expected == tenant => Ok(()),
            LifecycleScope::LocalUnscoped if self.owner.required_authority().is_none() => Ok(()),
            _ => Err(error(
                PlatformErrorCode::PermissionDenied,
                "historical-release-tenant-mismatch",
            )),
        }
    }
}

fn error(code: PlatformErrorCode, message: &'static str) -> PlatformError {
    PlatformError {
        code,
        message: message.into(),
        retryable: code == PlatformErrorCode::Unavailable,
        details: Vec::new(),
    }
}
