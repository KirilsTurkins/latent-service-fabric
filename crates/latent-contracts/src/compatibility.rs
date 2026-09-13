//! Conservative bounded previous-to-candidate analysis of legacy descriptors.
mod descriptor;
mod limits;
#[cfg(test)]
mod tests;

pub use descriptor::compare_descriptors;
use latent_core::{PlatformError, PlatformErrorCode};
pub use limits::{Analysis, ComparisonLimits, ComparisonWork};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum StructuralCompatibility {
    Identical,
    BackwardCompatible,
    Breaking,
    Unsupported,
    Unknown,
}

/// Stable diagnostic codes; descriptions and signature text are never authority.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum StructuralIssueCode {
    IdentityChanged,
    DependencyChanged,
    ImportChanged,
    RemovedInterface,
    RemovedFunction,
    RemovedType,
    FunctionChanged,
    TypeChanged,
    MissingTypeDefinition,
    UnsupportedType,
    UnsupportedPackage,
    AnalysisLimit,
}

impl StructuralIssueCode {
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::IdentityChanged => "identity-changed",
            Self::DependencyChanged => "dependency-changed",
            Self::ImportChanged => "import-changed",
            Self::RemovedInterface => "removed-interface",
            Self::RemovedFunction => "removed-function",
            Self::RemovedType => "removed-type",
            Self::FunctionChanged => "function-changed",
            Self::TypeChanged => "type-changed",
            Self::MissingTypeDefinition => "missing-type-definition",
            Self::UnsupportedType => "unsupported-type",
            Self::UnsupportedPackage => "unsupported-package",
            Self::AnalysisLimit => "analysis-limit",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct StructuralIssue {
    pub path: Box<str>,
    pub code: StructuralIssueCode,
}

/// Pure analysis, not an authorization or a verified-package capability.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct StructuralReport {
    pub level: StructuralCompatibility,
    pub analysis_complete: bool,
    pub diagnostics_truncated: bool,
    pub issues: Box<[StructuralIssue]>,
    pub work: ComparisonWork,
}

#[derive(Debug, Clone, Copy, Default)]
pub struct BoundedCompatibilityChecker;

impl crate::CompatibilityChecker for BoundedCompatibilityChecker {
    fn compare(
        &self,
        previous: &crate::ContractDescriptor,
        candidate: &crate::ContractDescriptor,
    ) -> crate::CompatibilityReport {
        match compare_descriptors(previous, candidate, ComparisonLimits::default()) {
            Ok(report) => crate::CompatibilityReport {
                level: match report.level {
                    StructuralCompatibility::Identical => crate::CompatibilityLevel::Identical,
                    StructuralCompatibility::BackwardCompatible => {
                        crate::CompatibilityLevel::BackwardCompatible
                    }
                    StructuralCompatibility::Breaking => crate::CompatibilityLevel::Breaking,
                    StructuralCompatibility::Unsupported | StructuralCompatibility::Unknown => {
                        crate::CompatibilityLevel::Unknown
                    }
                },
                issues: report
                    .issues
                    .into_vec()
                    .into_iter()
                    .map(|issue| crate::CompatibilityIssue {
                        path: issue.path.into_string(),
                        code: issue.code.as_str().to_owned(),
                        message: issue.code.as_str().to_owned(),
                    })
                    .collect(),
            },
            Err(_) => crate::CompatibilityReport {
                level: crate::CompatibilityLevel::Unknown,
                issues: vec![crate::CompatibilityIssue {
                    path: "$".to_owned(),
                    code: "invalid-comparison-input".to_owned(),
                    message: "invalid-comparison-input".to_owned(),
                }],
            },
        }
    }
}

fn invalid() -> PlatformError {
    PlatformError {
        code: PlatformErrorCode::InvalidArgument,
        message: "invalid-comparison-input".to_owned(),
        retryable: false,
        details: Vec::new(),
    }
}
