mod rollback;
mod web;
use crate::rollouts::{corrupt, error, Result};
use latent_artifacts::{ArtifactRepository, RetainedPackageSource};
use latent_contracts::{compare_descriptors, ComparisonLimits, StructuralCompatibility};
use latent_core::{PackageDigest, PlatformErrorCode, ReleaseDigest, TenantId};
use latent_packaging::{
    compare_packages, inspect_bundle, BundleInput, PackageBundle, PackageComparisonLimits,
    PackagingLimits,
};
pub(super) use rollback::compare as rollback;
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
    old_release: &crate::rollouts::RolloutRelease,
    candidate_release: &crate::rollouts::RolloutRelease,
) -> Result<(Option<PackageDigest>, Option<PackageDigest>)> {
    let old = &old_release.component;
    let candidate = &candidate_release.component;
    let op = old_release.publication.as_ref();
    let cp = candidate_release.publication.as_ref();
    let old_eligibility = repository.execution_eligibility_selected(old, op)?;
    let new_eligibility = repository.execution_eligibility_selected(candidate, cp)?;
    for (eligibility, publication, release) in [
        (&old_eligibility, op, old),
        (&new_eligibility, cp, candidate),
    ] {
        if let Some(token) = eligibility {
            if Some(token.publication()) != publication || token.release() != release {
                return Err(incompatible());
            }
            token.authorize_tenant(tenant)?;
            token.check_current()?;
        }
    }
    match (
        old_eligibility
            .as_ref()
            .and_then(|token| token.web_projection()),
        new_eligibility
            .as_ref()
            .and_then(|token| token.web_projection()),
    ) {
        (Some(previous), Some(next)) => {
            web::compare(previous.layout(), next.layout())?;
            return Ok((
                Some(previous.layout().package().clone()),
                Some(next.layout().package().clone()),
            ));
        }
        (None, None) => {}
        _ => return Err(incompatible()),
    }
    let old_proof = match &old_eligibility {
        Some(e) => e.admission().cloned(),
        None => repository.release_eligibility(old)?,
    };
    let new_proof = match &new_eligibility {
        Some(e) => e.admission().cloned(),
        None => repository.release_eligibility(candidate)?,
    };
    let old_source = repository
        .retained_package_source_selected(tenant, old, op, MAX_PACKAGE)
        .await?;
    let new_source = repository
        .retained_package_source_selected(tenant, candidate, cp, MAX_PACKAGE)
        .await?;
    for (proof, source, publication) in
        [(&old_proof, &old_source, op), (&new_proof, &new_source, cp)]
    {
        if source
            .as_ref()
            .is_some_and(|source| Some(source.publication()) != publication)
        {
            return Err(incompatible());
        }
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
            let previous = repository.fetch_verified_metadata_selected(old, op).await?;
            let next = repository
                .fetch_verified_metadata_selected(candidate, cp)
                .await?;
            descriptors(&previous, &next, old, candidate)?;
            Ok((None, None))
        }
        _ => Err(incompatible()),
    }
}

fn descriptors(
    previous: &latent_artifacts::VerifiedArtifactMetadata,
    next: &latent_artifacts::VerifiedArtifactMetadata,
    old: &ReleaseDigest,
    candidate: &ReleaseDigest,
) -> Result<()> {
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
                StructuralCompatibility::Identical | StructuralCompatibility::BackwardCompatible
            )
        {
            return Err(incompatible());
        }
    }
    Ok(())
}
