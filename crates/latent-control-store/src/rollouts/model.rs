use super::{codec, invalid, Result};
use latent_artifacts::ReleaseActor;
use latent_core::{
    ArtifactBlobDigest, DeploymentId, PackageDigest, ReleaseDigest, RouteGeneration, ServiceId,
    TenantId,
};
use latent_manifest::{
    __serde::{Deserialize, Serialize},
    DeploymentManifest,
};

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(crate = "latent_manifest::__serde", transparent)]
pub struct RolloutId(pub String);
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RolloutOperationPrecondition {
    pub operation_id: String,
    pub expected_revision: u64,
}
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RolloutContext {
    pub tenant: TenantId,
    pub actor: ReleaseActor,
    pub operation: RolloutOperationPrecondition,
}
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DeploymentExpectation {
    pub id: DeploymentId,
    pub generation: u64,
}
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct StartRolloutSpec {
    pub id: RolloutId,
    pub base: DeploymentExpectation,
    pub candidate: DeploymentManifest,
    pub candidate_weights: Vec<u16>,
    pub canary_policy: Option<super::RolloutCanaryPolicy>,
}
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RolloutCommand {
    Advance { next_step: u32 },
    Promote { next_step: u32 },
    Rollback { target_generation: RouteGeneration },
    Pause,
    Resume,
    Abort,
}
#[derive(Debug, Clone, PartialEq, Eq)]
#[expect(
    clippy::large_enum_variant,
    reason = "one fixed request slot is explicitly included in retained command accounting"
)]
pub enum RolloutRequest {
    Start {
        context: RolloutContext,
        spec: StartRolloutSpec,
    },
    Change {
        context: RolloutContext,
        id: RolloutId,
        command: RolloutCommand,
    },
}
macro_rules! enumeration { ($name:ident{$($v:ident),*$(,)?})=>{
    #[derive(Debug,Clone,Copy,PartialEq,Eq,Serialize,Deserialize)]
    #[serde(crate="latent_manifest::__serde",rename_all="kebab-case")]
    pub enum $name{$($v),*}
};}
enumeration!(RolloutState {
    Running,
    Paused,
    Completed,
    Aborted,
    RolledBack,
    Conflicted
});
enumeration!(RolloutAction {
    Start,
    Advance,
    Promote,
    Pause,
    Resume,
    Abort,
    Rollback
});
enumeration!(RolloutReason {
    OperatorRequested,
    StageApplied,
    Completed,
    GenerationConflict,
    CohortChanged,
    ReleaseIneligible,
    IncompatibleRelease,
    ResourceLimit,
    RecoveryRequired,
    OutcomeUncertain,
    RollbackApplied
});
enumeration!(RolloutOperationOutcome { Committed });
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(
    crate = "latent_manifest::__serde",
    rename_all = "camelCase",
    deny_unknown_fields
)]
pub struct RolloutRelease {
    #[serde(with = "codec::text")]
    pub deployment_id: DeploymentId,
    #[serde(with = "codec::text")]
    pub component: ReleaseDigest,
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        with = "codec::optional"
    )]
    pub package: Option<PackageDigest>,
}
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(
    crate = "latent_manifest::__serde",
    rename_all = "camelCase",
    deny_unknown_fields
)]
pub struct RolloutObjectVersion {
    #[serde(with = "codec::text")]
    pub deployment_id: DeploymentId,
    pub generation: u64,
}
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(
    crate = "latent_manifest::__serde",
    rename_all = "camelCase",
    deny_unknown_fields
)]
pub struct RolloutStatus {
    pub id: RolloutId,
    #[serde(with = "codec::text")]
    pub tenant: TenantId,
    #[serde(with = "codec::text")]
    pub service: ServiceId,
    pub revision: u64,
    pub state: RolloutState,
    pub reason: RolloutReason,
    pub current_step: u32,
    pub candidate_weights: Vec<u16>,
    pub base: RolloutRelease,
    pub candidate: RolloutRelease,
    pub objects: Vec<RolloutObjectVersion>,
    #[serde(with = "codec::generation")]
    pub route_generation: RouteGeneration,
    pub state_version: u64,
    #[serde(with = "codec::text")]
    pub plan_digest: ArtifactBlobDigest,
    #[serde(with = "codec::generation")]
    pub previous_route_generation: RouteGeneration,
    pub created_at_unix_millis: u64,
    pub updated_at_unix_millis: u64,
    pub retained_operation_floor: u64,
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        deserialize_with = "super::canary::optional"
    )]
    pub canary_policy: Option<super::RolloutCanaryPolicy>,
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        deserialize_with = "super::canary::optional"
    )]
    pub rollback_target: Option<super::RolloutRollbackTarget>,
}
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(
    crate = "latent_manifest::__serde",
    rename_all = "camelCase",
    deny_unknown_fields
)]
pub struct RolloutOperationReceipt {
    pub rollout_id: RolloutId,
    #[serde(with = "codec::text")]
    pub tenant: TenantId,
    pub operation_id: String,
    #[serde(with = "codec::text")]
    pub request_digest: ArtifactBlobDigest,
    pub actor: ReleaseActor,
    pub action: RolloutAction,
    pub expected_revision: u64,
    pub revision: u64,
    pub outcome: RolloutOperationOutcome,
    pub reason: RolloutReason,
    pub state_version: u64,
    #[serde(with = "codec::generation")]
    pub route_generation: RouteGeneration,
    pub state: RolloutState,
    pub step: u32,
    #[serde(with = "codec::text")]
    pub plan_digest: ArtifactBlobDigest,
    pub completed_at_unix_millis: u64,
    #[serde(with = "codec::text")]
    pub receipt_digest: ArtifactBlobDigest,
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        deserialize_with = "super::canary::optional"
    )]
    pub canary_decision: Option<super::RolloutCanaryDecision>,
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        deserialize_with = "super::canary::optional"
    )]
    pub rollback_target: Option<super::RolloutRollbackTarget>,
}
impl RolloutOperationReceipt {
    pub fn canonical_bytes(&self) -> Result<Vec<u8>> {
        codec::encode(self, super::MAX_RECEIPT_BYTES)
    }
}
#[derive(Debug, Clone, PartialEq, Eq)]
#[expect(
    clippy::large_enum_variant,
    reason = "the bounded receipt moves to a pre-reserved response owner without another allocation"
)]
pub enum RolloutOperationLookup {
    Found(RolloutOperationReceipt),
    Unknown,
    Uncertain,
}
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RolloutCommitResult {
    pub receipt: RolloutOperationReceipt,
    pub replayed: bool,
    pub durability: Result<()>,
}
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RolloutPageRequest {
    pub tenant: TenantId,
    pub service: Option<ServiceId>,
    pub state: Option<RolloutState>,
    pub cursor: Option<String>,
    pub limit: usize,
    pub maximum_bytes: usize,
}
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RolloutPage {
    pub rollouts: Vec<RolloutStatus>,
    pub next_cursor: Option<String>,
    pub state_version: u64,
}
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct RolloutLimits {
    pub maximum_active: usize,
    pub maximum_rows: usize,
    pub maximum_stages: usize,
    pub maximum_receipts: usize,
    pub maximum_metadata_bytes: usize,
}
impl Default for RolloutLimits {
    fn default() -> Self {
        Self {
            maximum_active: 16,
            maximum_rows: 256,
            maximum_stages: 16,
            maximum_receipts: 256,
            maximum_metadata_bytes: 8 * 1024 * 1024,
        }
    }
}
impl RolloutLimits {
    /// Reads previously valid history when the node has disabled rollout RPCs.
    /// This is an explicit recovery ceiling; it enables no coordinator or mutation path.
    #[must_use]
    pub const fn recovery_maximum() -> Self {
        Self {
            maximum_active: 64,
            maximum_rows: 1024,
            maximum_stages: 64,
            maximum_receipts: 1024,
            maximum_metadata_bytes: 32 * 1024 * 1024,
        }
    }
    pub fn validate(self) -> Result<Self> {
        if [
            (self.maximum_active, 64),
            (self.maximum_rows, 1024),
            (self.maximum_stages, 64),
            (self.maximum_receipts, 1024),
            (self.maximum_metadata_bytes, 32 * 1024 * 1024),
        ]
        .iter()
        .any(|(v, m)| *v == 0 || v > m)
            || self.maximum_active > self.maximum_rows
            || self.maximum_metadata_bytes < 256 * 1024
        {
            return Err(invalid());
        }
        Ok(self)
    }
}
