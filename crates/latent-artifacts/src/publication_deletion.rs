//! Exact deletion admission and durable visibility removal. Payload reclamation is separate.
use crate::{
    LifecycleAuthorityHandle, LifecycleScope, PublicationRef, PublicationRetentionFence,
    PublicationRetentionTarget, ReleaseActor,
};
use latent_core::PlatformError;
use serde::{Deserialize, Serialize};

/// Exact authorized selection. A trusted adapter must authenticate scope and actor
/// before constructing it; neither identifiers nor catalog fences grant authority.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PublicationDeletionRequest {
    pub scope: LifecycleScope,
    pub actor: ReleaseActor,
    pub operation_id: String,
    pub expected_catalog_fence: PublicationRetentionFence,
    pub targets: Vec<PublicationRetentionTarget>,
}
impl PublicationDeletionRequest {
    pub(crate) fn validate(&self) -> Result<(), PlatformError> {
        crate::publication_retention::validate_targets(
            &self.scope,
            &self.actor,
            &self.operation_id,
            &self.targets,
            self.targets.capacity(),
        )
    }
}

/// One coherent observation under native reader, lifecycle and reference fences.
/// It changes no disk state, reserves no deletion/audit capacity, and promises
/// nothing about a later operation. The tombstone commit rechecks every fence.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PublicationDeletionAssessment {
    pub request: PublicationDeletionRequest,
    pub reference_revision: u64,
}

/// Trusted host integration, like an admission authority, not an end-user input.
///
/// The implementation must be bound to this exact live artifact owner, retain
/// its durable reference/commit exclusion through `action`, and reject every
/// retained deployment, HTTP-trigger and rollout target in `publications`.
/// Unconfirmed, absent, foreign or dropped reference authority must fail closed.
/// The native control store supplies the maintained implementation. A caller-
/// supplied list, an earlier snapshot or a boolean cannot implement this contract.
pub trait PublicationReferenceAuthority: Send + Sync {
    fn catalog_authority(&self) -> Result<LifecycleAuthorityHandle, PlatformError>;
    fn with_unreferenced_publications(
        &self,
        catalog: &LifecycleAuthorityHandle,
        publications: &[PublicationRef],
        action: &mut dyn FnMut(u64) -> Result<(), PlatformError>,
    ) -> Result<(), PlatformError>;
}

/// Finite negative-authority history. Exhaustion refuses new deletion; tombstones
/// are never evicted to make a publication ID reusable.
pub const MAX_PUBLICATION_TOMBSTONES: usize = 1024;
pub const MAX_PUBLICATION_DELETION_RECEIPTS: usize = 64;

/// Logical deletion has committed, but no publication or shared-blob bytes have
/// been unlinked or refunded. This is deliberately not a reclamation receipt.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum PublicationDeletionStage {
    VisibilityRemoved,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PublicationDeletionReceipt {
    pub request: PublicationDeletionRequest,
    pub revision: u64,
    pub reference_revision: u64,
    pub stage: PublicationDeletionStage,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PublicationDeletionResult {
    pub receipt: PublicationDeletionReceipt,
    /// A retained original receipt was returned; no mutation was executed.
    pub replay: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PublicationDeletionLookup {
    Found(PublicationDeletionReceipt),
    /// Absence or eviction proves neither nonexecution nor permission to replay.
    Unknown,
    /// Reopen the complete installation and query the original operation ID.
    Uncertain,
}
