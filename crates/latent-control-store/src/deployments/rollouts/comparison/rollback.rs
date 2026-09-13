//! Reverse comparison reads historical source integrity without reviving its grant.
use super::{bundle, descriptors, incompatible, MAX_PACKAGE};
use crate::rollouts::{error, Result, RolloutRelease};
use latent_artifacts::{
    AdmissionAuthority, ArtifactRepository, HistoricalExecutionState, LifecycleAuthorityHandle,
};
use latent_core::{PlatformErrorCode, TenantId};
use latent_packaging::{compare_packages, PackageComparisonLimits};
use std::sync::Arc;

pub(in crate::deployments::rollouts) async fn compare(
    repository: &dyn ArtifactRepository,
    owner: Option<&LifecycleAuthorityHandle>,
    authority: Option<&Arc<dyn AdmissionAuthority>>,
    tenant: &TenantId,
    served: &RolloutRelease,
    target: &RolloutRelease,
) -> Result<()> {
    // The snapshot's metadata and permission state have one sealed constructor.
    // A negative state is used solely for source identity, never route authority.
    let historical = repository
        .historical_execution_snapshot(&served.component)
        .await?;
    let (previous, state) = historical.into_parts();
    if previous.verified_digest() != &served.component
        || previous
            .manifest()
            .metadata
            .tenant
            .as_ref()
            .is_some_and(|scope| scope != tenant)
    {
        return Err(incompatible());
    }
    match (&state, owner) {
        (HistoricalExecutionState::Unmanaged, None) if authority.is_none() => {}
        (HistoricalExecutionState::Eligible(token), owner) => {
            if owner.is_some_and(|owner| !token.belongs_to_catalog(owner))
                || token.release() != &served.component
                || token.package() != served.package.as_ref()
            {
                return Err(owner_mismatch());
            }
            token.authorize_tenant(tenant)?;
        }
        (HistoricalExecutionState::Denied(denial), owner) => {
            if let Some(owner) = owner {
                denial.check_for_catalog(owner)?;
            }
            denial.authorize_tenant(tenant)?;
            if denial.release() != &served.component {
                return Err(owner_mismatch());
            }
        }
        _ => return Err(owner_mismatch()),
    }
    let target_eligibility = repository.execution_eligibility(&target.component)?;
    match (target_eligibility.as_ref(), owner) {
        (Some(token), owner) => {
            if let Some(owner) = owner {
                token.check_for_lifecycle(owner)?;
            }
            if let Some(authority) = authority {
                token.check_for_authority(authority)?;
            }
            token.check_current()?;
            token.authorize_tenant(tenant)?;
            if token.release() != &target.component || token.package() != target.package.as_ref() {
                return Err(owner_mismatch());
            }
        }
        (None, None) if authority.is_none() => {}
        _ => return Err(owner_mismatch()),
    }
    let old_source = repository
        .retained_package_source(tenant, &served.component, MAX_PACKAGE)
        .await?;
    let new_source = repository
        .retained_package_source(tenant, &target.component, MAX_PACKAGE)
        .await?;
    if old_source
        .as_ref()
        .map(latent_artifacts::RetainedPackageSource::package)
        != served.package.as_ref()
        || new_source
            .as_ref()
            .map(latent_artifacts::RetainedPackageSource::package)
            != target.package.as_ref()
    {
        return Err(incompatible());
    }
    match (old_source, new_source) {
        (Some(old), Some(new)) => {
            let previous = bundle(old, tenant, &served.component)?;
            let next = bundle(new, tenant, &target.component)?;
            if !compare_packages(&previous, &next, PackageComparisonLimits::default())?
                .allows_replacement(None)
            {
                return Err(incompatible());
            }
        }
        (None, None) => {
            let next = repository
                .fetch_verified_metadata(&target.component)
                .await?;
            if next
                .manifest()
                .metadata
                .tenant
                .as_ref()
                .is_some_and(|scope| scope != tenant)
            {
                return Err(incompatible());
            }
            descriptors(&previous, &next, &served.component, &target.component)?;
        }
        _ => return Err(incompatible()),
    }
    Ok(())
}
fn owner_mismatch() -> latent_core::PlatformError {
    error(
        PlatformErrorCode::PermissionDenied,
        "rollout-historical-owner-mismatch",
    )
}
