use latent_artifacts::{ReleaseActor, ReleaseAuditAck};
use latent_control_store::rollouts::{RolloutId, RolloutOperationReceipt};
use latent_core::{ArtifactBlobDigest, PlatformError, RevisionId, RouteGeneration, TenantId};
use latent_telemetry::{CanaryAssessment, CanaryRevisionBinding, CanaryRevisionSnapshot};

/// Trusted adapter input: the actor comes from the authenticated principal.
pub struct CanaryEvaluationRequest {
    pub tenant: TenantId,
    pub actor: ReleaseActor,
    pub id: RolloutId,
    pub expected_revision: u64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RolloutObservationState {
    Collecting,
    AwaitingEvaluation,
    Unavailable,
    Retired,
}
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct RolloutObservation {
    pub state: RolloutObservationState,
    pub window_epoch: Option<u64>,
}
impl RolloutObservation {
    pub(crate) const fn unavailable() -> Self {
        Self {
            state: RolloutObservationState::Unavailable,
            window_epoch: None,
        }
    }
    pub(crate) const fn maximum() -> Self {
        Self {
            state: RolloutObservationState::AwaitingEvaluation,
            window_epoch: Some(u64::MAX),
        }
    }
}

/// Copyable diagnostic counters and attribution never construct promotion proof.
pub struct CanaryRevisionReport {
    pub binding: CanaryRevisionBinding,
    pub outcomes: CanaryRevisionSnapshot,
}
pub struct CanaryEvaluationReport {
    pub rollout_id: RolloutId,
    pub revision: u64,
    pub step: u32,
    pub route_generation: RouteGeneration,
    pub policy_digest: ArtifactBlobDigest,
    pub window_epoch: Option<u64>,
    pub candidate_revision: RevisionId,
    pub duration_millis: u64,
    pub observation: RolloutObservation,
    pub assessment: Option<CanaryAssessment>,
    pub starts: u64,
    pub selected: u64,
    pub admitted: u64,
    pub terminal: u64,
    pub live: u64,
    pub unattributed: u64,
    pub abandoned: u64,
    pub revisions: Vec<CanaryRevisionReport>,
}

/// Both known rejection and possible success are preflighted before accepting
/// critical audit work. An exact retained replay may have no live decision.
pub struct PromotionPreview<'a> {
    pub receipt: Option<&'a RolloutOperationReceipt>,
    pub decision: Option<&'a CanaryEvaluationReport>,
    pub failure: Option<&'a PlatformError>,
    pub replayed: bool,
    pub audit_ack: ReleaseAuditAck,
    pub observation: Option<RolloutObservation>,
}
