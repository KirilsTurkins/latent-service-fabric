use latent_core::{ArtifactBlobDigest, PackageDigest, PlatformError, PlatformErrorCode};

use crate::PackageBundle;

use super::{SbomPolicy, SbomPresence};
use crate::sbom::{inspect_sbom_association, SbomEvidenceLimits, SbomEvidenceRef};

/// Exact identities accepted by this content policy. This immutable result has
/// no independent publisher authority or currentness; admission must bind it to
/// the current authenticated package and admission policy epoch.
#[derive(Debug)]
#[allow(clippy::struct_field_names)] // Keep content/policy/referrer identity meanings explicit.
pub struct SbomPolicyEvaluation {
    package_digest: PackageDigest,
    policy_digest: ArtifactBlobDigest,
    inventory_digest: Option<ArtifactBlobDigest>,
    referrer_digest: Option<PackageDigest>,
}

impl SbomPolicyEvaluation {
    #[must_use]
    pub fn package_digest(&self) -> &PackageDigest {
        &self.package_digest
    }
    #[must_use]
    pub fn policy_digest(&self) -> &ArtifactBlobDigest {
        &self.policy_digest
    }
    #[must_use]
    pub fn inventory_digest(&self) -> Option<&ArtifactBlobDigest> {
        self.inventory_digest.as_ref()
    }
    #[must_use]
    pub fn referrer_digest(&self) -> Option<&PackageDigest> {
        self.referrer_digest.as_ref()
    }
}

/// Checks every supplied association under aggregate limits before applying
/// presence and attribution. Duplicate/conflicting associations fail; discovery
/// ordering never selects a preferred inventory or changes the error class.
pub fn evaluate_sboms(
    package: &PackageBundle,
    evidence: &[SbomEvidenceRef<'_>],
    policy: &SbomPolicy,
    limits: SbomEvidenceLimits,
) -> Result<SbomPolicyEvaluation, PlatformError> {
    limits.check_all(evidence)?;
    let mut associations = Vec::with_capacity(evidence.len());
    let mut invalid = false;
    let mut exhausted = false;
    for entry in evidence {
        match inspect_sbom_association(package, *entry, limits) {
            Ok(association) => associations.push(association),
            Err(error) => {
                invalid = true;
                exhausted |= error.code == PlatformErrorCode::ResourceExhausted;
            }
        }
    }
    if exhausted {
        return Err(crate::exceeded("sbom-association-set-limit"));
    }
    if invalid {
        return Err(crate::invalid("invalid-sbom-association-set"));
    }
    if associations.len() > 1 {
        let first = associations[0].referrer_digest();
        return Err(crate::invalid(
            if associations
                .iter()
                .all(|entry| entry.referrer_digest() == first)
            {
                "duplicate-sbom-association"
            } else {
                "conflicting-sbom-associations"
            },
        ));
    }
    if policy.config().embedded == SbomPresence::Required && package.sbom().is_none() {
        return Err(crate::invalid("required-embedded-sbom-missing"));
    }
    if policy.config().detached == SbomPresence::Required && associations.is_empty() {
        return Err(crate::invalid("required-detached-sbom-missing"));
    }
    if let Some(inventory) = package.sbom() {
        for kind in &policy.config().require_source {
            let counts = inventory.counts(*kind);
            if counts.entries() != counts.with_source() {
                return Err(crate::invalid("required-sbom-source-unavailable"));
            }
        }
        for kind in &policy.config().require_license {
            let counts = inventory.counts(*kind);
            if counts.entries() != counts.with_license() {
                return Err(crate::invalid("required-sbom-license-unavailable"));
            }
        }
    }
    Ok(SbomPolicyEvaluation {
        package_digest: package.layout().digest().clone(),
        policy_digest: policy.digest().clone(),
        inventory_digest: package.sbom().map(|entry| entry.inventory_digest().clone()),
        referrer_digest: associations
            .first()
            .map(|entry| entry.referrer_digest().clone()),
    })
}
