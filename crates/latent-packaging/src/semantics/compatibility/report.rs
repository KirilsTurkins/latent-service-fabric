use crate::{PackageBundle, SemanticLimits};
use latent_contracts::{ComparisonLimits, StructuralCompatibility, StructuralReport};
use latent_core::{ArtifactBlobDigest, PackageDigest, PlatformError};

/// Two-input control-operation ceilings. Semantic limits apply to the captured
/// WIT graph; sealed components are not decoded or compiled a second time.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PackageComparisonLimits {
    pub semantics: SemanticLimits,
    pub comparison: ComparisonLimits,
    pub max_total_wit_bytes: usize,
    pub max_total_wit_packages: usize,
}
impl Default for PackageComparisonLimits {
    fn default() -> Self {
        Self {
            semantics: SemanticLimits::default(),
            comparison: ComparisonLimits::default(),
            max_total_wit_bytes: 8 * 1024 * 1024,
            max_total_wit_packages: 512,
        }
    }
}
impl PackageComparisonLimits {
    pub(super) fn validate(self) -> Result<(), PlatformError> {
        self.semantics.validate()?;
        self.comparison.validate()?;
        let hard = Self::default();
        if self.max_total_wit_bytes == 0
            || self.max_total_wit_bytes > hard.max_total_wit_bytes
            || self.max_total_wit_packages == 0
            || self.max_total_wit_packages > hard.max_total_wit_packages
        {
            return Err(crate::invalid("invalid-package-comparison-limits"));
        }
        Ok(())
    }
}
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ComparedPackageIdentity {
    package: PackageDigest,
    component: Option<ArtifactBlobDigest>,
}
impl ComparedPackageIdentity {
    pub(super) fn of(bundle: &PackageBundle) -> Self {
        Self {
            package: bundle.layout().digest().clone(),
            component: bundle
                .surface()
                .map(|surface| surface.component_digest().clone()),
        }
    }
    #[must_use]
    pub fn package(&self) -> &PackageDigest {
        &self.package
    }
    #[must_use]
    pub fn component(&self) -> Option<&ArtifactBlobDigest> {
        self.component.as_ref()
    }
}

/// Explicit caller decision scoped to one exact pair; not publisher, tenant,
/// runtime, or route revision authorization.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BreakingChangeAllowance {
    previous: ComparedPackageIdentity,
    candidate: ComparedPackageIdentity,
}
impl BreakingChangeAllowance {
    pub fn for_pair(
        previous: &PackageBundle,
        candidate: &PackageBundle,
    ) -> Result<Self, PlatformError> {
        let previous = ComparedPackageIdentity::of(previous);
        let candidate = ComparedPackageIdentity::of(candidate);
        if previous.component.is_none() || candidate.component.is_none() {
            return Err(crate::invalid("breaking-allowance-requires-capsules"));
        }
        Ok(Self {
            previous,
            candidate,
        })
    }
}
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PackageCompatibilityReport {
    previous: ComparedPackageIdentity,
    candidate: ComparedPackageIdentity,
    structural: StructuralReport,
}
impl PackageCompatibilityReport {
    pub(super) fn new(
        previous: ComparedPackageIdentity,
        candidate: ComparedPackageIdentity,
        structural: StructuralReport,
    ) -> Self {
        Self {
            previous,
            candidate,
            structural,
        }
    }
    #[must_use]
    pub fn previous(&self) -> &ComparedPackageIdentity {
        &self.previous
    }
    #[must_use]
    pub fn candidate(&self) -> &ComparedPackageIdentity {
        &self.candidate
    }
    #[must_use]
    pub fn structural(&self) -> &StructuralReport {
        &self.structural
    }
    /// A structural decision only. The caller must separately enforce live
    /// admission, host requirements and the expected deployment revision.
    #[must_use]
    pub fn allows_replacement(&self, allowance: Option<&BreakingChangeAllowance>) -> bool {
        if !self.structural.analysis_complete {
            return false;
        }
        match self.structural.level {
            StructuralCompatibility::Identical | StructuralCompatibility::BackwardCompatible => {
                true
            }
            StructuralCompatibility::Breaking => allowance.is_some_and(|allowance| {
                allowance.previous == self.previous && allowance.candidate == self.candidate
            }),
            StructuralCompatibility::Unsupported | StructuralCompatibility::Unknown => false,
        }
    }
}

#[cfg(test)]
pub(super) fn assert_unknown_rejects_allowance(structural: StructuralReport) {
    let identity = ComparedPackageIdentity {
        package: format!("sha256:{}", "1".repeat(64)).parse().unwrap(),
        component: Some(format!("sha256:{}", "2".repeat(64)).parse().unwrap()),
    };
    let allowance = BreakingChangeAllowance {
        previous: identity.clone(),
        candidate: identity.clone(),
    };
    let report = PackageCompatibilityReport::new(identity.clone(), identity, structural);
    assert!(!report.allows_replacement(Some(&allowance)));
}
