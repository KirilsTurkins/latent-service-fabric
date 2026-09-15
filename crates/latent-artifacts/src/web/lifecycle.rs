use crate::{
    PublicationRef, ReleaseActor, ReleaseEligibilityReason, ReleaseLifecycleAction,
    ReleaseLifecycleReason, ReleaseLifecycleState, ReleaseLiveEligibility,
    ReleaseOperationDisposition,
};
use latent_core::{ArtifactBlobDigest, PackageDigest};
use serde::{Deserialize, Serialize};

/// Historical web publication lifecycle. No optional or synthetic capsule
/// identity is used to authorize assets or an independently prepared renderer.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct WebLifecycleRecord {
    pub publication: PublicationRef,
    #[serde(with = "super::codec::package")]
    pub package: PackageDigest,
    #[serde(with = "super::codec::blob")]
    pub manifest: ArtifactBlobDigest,
    #[serde(with = "super::codec::blob")]
    pub assets: ArtifactBlobDigest,
    pub state: ReleaseLifecycleState,
    pub generation: u64,
    pub actor: ReleaseActor,
    pub reason: ReleaseLifecycleReason,
    pub operation_id: String,
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        with = "super::codec::optional_blob"
    )]
    pub evidence_revision: Option<ArtifactBlobDigest>,
}

/// Finite retained operation result. Identity/receipt fields never become
/// current eligibility; exact retries are reported independently of their hash.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct WebOperationReceipt {
    pub format_version: u32,
    pub publication: PublicationRef,
    pub operation_id: String,
    pub action: ReleaseLifecycleAction,
    pub actor: ReleaseActor,
    pub expected_generation: u64,
    pub resulting_generation: u64,
    pub disposition: ReleaseOperationDisposition,
    pub reason: ReleaseLifecycleReason,
    #[serde(with = "super::codec::blob")]
    pub request_digest: ArtifactBlobDigest,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WebMutationResult {
    pub receipt: WebOperationReceipt,
    pub replay: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WebPublicationStatus {
    pub record: WebLifecycleRecord,
    pub eligibility: ReleaseLiveEligibility,
    pub eligibility_reason: ReleaseEligibilityReason,
}
