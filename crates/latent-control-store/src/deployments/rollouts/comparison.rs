use crate::rollouts::{corrupt, error, Result};
use latent_artifacts::{ArtifactRepository, RetainedPackageSource};
use latent_contracts::{compare_descriptors, ComparisonLimits, StructuralCompatibility};
use latent_core::{PackageDigest, PlatformErrorCode, ReleaseDigest, TenantId};
use latent_packaging::{
    compare_packages, inspect_bundle, BundleInput, PackageBundle, PackageComparisonLimits,
    PackagingLimits,
};
const MAX_PACKAGE: usize = 32 * 1024 * 1024;
fn incompatible() -> latent_core::PlatformError {
    error(
        PlatformErrorCode::IncompatibleContract,
        "rollout-incompatible-release",
    )
}
fn bundle(
    source: RetainedPackageSource,
    tenant: &TenantId,
    release: &ReleaseDigest,
) -> Result<PackageBundle> {
    if source.tenant() != tenant
        || source.component() != release
        || source.retained_bytes() > MAX_PACKAGE
    {
        return Err(corrupt());
    }
    let expected = source.package().clone();
    let (manifest, configuration, layers) = source.into_parts();
    let bundle = inspect_bundle(
        BundleInput {
            manifest,
            configuration,
            layers,
        },
        PackagingLimits::default(),
    )?;
    if bundle.layout().digest() != &expected
        || bundle
            .surface()
            .is_none_or(|s| s.component_digest().as_str() != release.0)
    {
        return Err(corrupt());
    }
    Ok(bundle)
}
pub(super) async fn compare(
    repository: &dyn ArtifactRepository,
    tenant: &TenantId,
    old: &ReleaseDigest,
    candidate: &ReleaseDigest,
) -> Result<(Option<PackageDigest>, Option<PackageDigest>)> {
    for release in [old, candidate] {
        if let Some(e) = repository.execution_eligibility(release)? {
            e.authorize_tenant(tenant)?;
            e.check_current()?;
        }
    }
    let old_proof = repository.release_eligibility(old)?;
    let new_proof = repository.release_eligibility(candidate)?;
    let old_source = repository
        .retained_package_source(tenant, old, MAX_PACKAGE)
        .await?;
    let new_source = repository
        .retained_package_source(tenant, candidate, MAX_PACKAGE)
        .await?;
    for (proof, source) in [(&old_proof, &old_source), (&new_proof, &new_source)] {
        if let Some(proof) = proof {
            proof.check_current()?;
            if proof.tenant() != tenant
                || source
                    .as_ref()
                    .is_none_or(|s| s.package() != proof.package())
            {
                return Err(incompatible());
            }
        }
    }
    match (old_source, new_source) {
        (Some(old_source), Some(new_source)) => {
            let old_bundle = bundle(old_source, tenant, old)?;
            let new_bundle = bundle(new_source, tenant, candidate)?;
            let report =
                compare_packages(&old_bundle, &new_bundle, PackageComparisonLimits::default())?;
            if !report.allows_replacement(None) {
                return Err(incompatible());
            }
            Ok((
                Some(old_bundle.layout().digest().clone()),
                Some(new_bundle.layout().digest().clone()),
            ))
        }
        (None, None) if old_proof.is_none() && new_proof.is_none() => {
            let previous = repository.fetch_verified_metadata(old).await?;
            let next = repository.fetch_verified_metadata(candidate).await?;
            if previous.verified_digest() != old
                || next.verified_digest() != candidate
                || previous.manifest().world != next.manifest().world
                || previous.manifest().imports != next.manifest().imports
                || previous.contracts().is_empty()
            {
                return Err(incompatible());
            }
            for prior in previous.contracts() {
                let mut candidates = next.contracts().iter().filter(|c| c.id == prior.id);
                let matched = candidates.next().ok_or_else(incompatible)?;
                if candidates.next().is_some() {
                    return Err(incompatible());
                }
                let report = compare_descriptors(prior, matched, ComparisonLimits::default())?;
                if !report.analysis_complete
                    || !matches!(
                        report.level,
                        StructuralCompatibility::Identical
                            | StructuralCompatibility::BackwardCompatible
                    )
                {
                    return Err(incompatible());
                }
            }
            Ok((None, None))
        }
        _ => Err(incompatible()),
    }
}
