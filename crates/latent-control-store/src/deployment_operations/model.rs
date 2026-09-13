use super::{codec, invalid, Result, MAX_RECEIPT_BYTES};
use crate::VersionedDeployment;
use latent_artifacts::ReleaseActor;
use latent_core::{
    ArtifactBlobDigest, DeploymentId, PlatformError, ReleaseDigest, RouteGeneration, TenantId,
};
use latent_manifest::{
    __serde::{Deserialize, Serialize},
    DeploymentManifest,
};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DeploymentOperationContext {
    pub tenant: TenantId,
    pub actor: ReleaseActor,
    pub operation_id: String,
    pub expected_state_version: u64,
}
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum DeploymentOperationRequest {
    Apply {
        context: DeploymentOperationContext,
        manifest: DeploymentManifest,
        expected_generation: u64,
    },
    Delete {
        context: DeploymentOperationContext,
        id: DeploymentId,
        expected_generation: u64,
    },
}
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(crate = "latent_manifest::__serde", rename_all = "kebab-case")]
pub enum DeploymentOperationAction {
    Apply,
    Delete,
}
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(
    crate = "latent_manifest::__serde",
    rename_all = "camelCase",
    deny_unknown_fields
)]
pub struct DeploymentOperationReceipt {
    pub format_version: u32,
    #[serde(with = "codec::tenant")]
    pub tenant: TenantId,
    pub actor: ReleaseActor,
    pub operation_id: String,
    pub action: DeploymentOperationAction,
    #[serde(with = "codec::id")]
    pub deployment_id: DeploymentId,
    #[serde(with = "crate::rollouts::codec::text")]
    pub request_digest: ArtifactBlobDigest,
    pub expected_state_version: u64,
    pub expected_generation: u64,
    pub object_generation: u64,
    #[serde(with = "crate::rollouts::codec::generation")]
    pub route_generation: RouteGeneration,
    pub state_version: u64,
    #[serde(with = "crate::rollouts::codec::text")]
    pub manifest_digest: ArtifactBlobDigest,
    #[serde(with = "crate::rollouts::codec::text")]
    pub component: ReleaseDigest,
    pub completed_at_unix_millis: u64,
    #[serde(with = "crate::rollouts::codec::text")]
    pub receipt_digest: ArtifactBlobDigest,
}
impl DeploymentOperationReceipt {
    pub fn canonical_bytes(&self) -> Result<Vec<u8>> {
        codec::encode(self, MAX_RECEIPT_BYTES)
    }
}
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum DeploymentOperationLookup {
    Found(DeploymentOperationReceipt),
    Unknown {
        retained_floor: u64,
        high_watermark: u64,
    },
    Uncertain,
}
#[derive(Debug, PartialEq, Eq)]
pub struct DeploymentOperationSnapshot {
    pub deployment: Option<VersionedDeployment>,
    pub state_version: u64,
    pub route_generation: RouteGeneration,
    pub confirmed: bool,
}
#[derive(Debug, PartialEq, Eq)]
pub struct DeploymentOperationCommit {
    pub receipt: DeploymentOperationReceipt,
    pub deployment: Option<VersionedDeployment>,
    pub replayed: bool,
    pub durability: std::result::Result<(), PlatformError>,
}
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct DeploymentOperationLimits {
    pub maximum_receipts: usize,
    pub maximum_metadata_bytes: usize,
    pub maximum_read_owners: usize,
}
impl Default for DeploymentOperationLimits {
    fn default() -> Self {
        Self {
            maximum_receipts: 256,
            maximum_metadata_bytes: 8 * 1024 * 1024,
            maximum_read_owners: 64,
        }
    }
}
impl DeploymentOperationLimits {
    pub fn validate(self) -> Result<Self> {
        if self.maximum_receipts == 0
            || self.maximum_receipts > 1024
            || self.maximum_metadata_bytes < 64 * 1024
            || self.maximum_metadata_bytes > 8 * 1024 * 1024
            || self.maximum_read_owners == 0
            || self.maximum_read_owners > 1024
        {
            return Err(invalid());
        }
        Ok(self)
    }
}
