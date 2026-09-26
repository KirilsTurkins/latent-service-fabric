//! Conservative bounded previous-to-candidate analysis of contract descriptors.
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

fn invalid() -> PlatformError {
    PlatformError {
        code: PlatformErrorCode::InvalidArgument,
        message: "invalid-comparison-input".to_owned(),
        retryable: false,
        details: Vec::new(),
    }
}
