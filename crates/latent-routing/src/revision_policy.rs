//! Trusted, immutable execution policy associated with an exact resolved revision.
//!
//! Implementations must verify the complete tenant/target/revision/release/generation
//! tuple against the pinned catalog. Caller-supplied `ResolvedRevision::attributes`
//! are never an authority for resource ceilings, placement, or trust.

use latent_core::{PlatformError, ResourceBudget};

pub use latent_manifest::{
    ExecutionBackendKind, ExecutionRequirements, PlacementPolicy, StateModel, ThreadingModel,
};

use crate::ResolvedRevision;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RevisionAdmissionPolicy {
    pub deployment_ceiling: ResourceBudget,
    pub execution: ExecutionRequirements,
    pub placement: PlacementPolicy,
}

/// A trusted local policy lookup, not an authentication or remote policy engine.
///
/// Use the same pinned catalog view for resolution and this lookup. A view must
/// keep serving its original revisions while newer catalog generations replace
/// them. No artifact fetch, compilation, or execution allocation belongs here.
pub trait RevisionPolicySource: Send + Sync {
    fn admission_policy(
        &self,
        revision: &ResolvedRevision,
    ) -> Result<RevisionAdmissionPolicy, PlatformError>;
}
