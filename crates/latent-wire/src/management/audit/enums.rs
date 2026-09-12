use super::super::proto;
use latent_audit as domain;
use tonic::Status;

macro_rules! mapping {
    ($function:ident,$source:ident,$target:ident; $($variant:ident),+ $(,)?) => {
        pub(super) fn $function(value: domain::$source) -> i32 {
            match value { $(domain::$source::$variant => proto::$target::$variant as i32),+ }
        }
    };
}
mapping!(kind, Phase2AuditEventKind, Phase2AuditEventKind;
    VerificationAccepted, VerificationRejected, ReleaseRevoked, ReleaseRetired,
    CacheHit, CacheMiss, CacheCorruption, RolloutStarted, RolloutStageChanged,
    RolloutPaused, RolloutAborted, PromotionAccepted, PromotionRejected, RollbackAccepted, RollbackRejected);
mapping!(actor, AuditActorKind, AuditActorKind; User, Service, Node, Trigger, Administrator, Anonymous, Host);
mapping!(policy, AuditPolicyRole, AuditPolicyRole; Publisher, PublisherRevocation, Builder,
    BuilderRevocation, Sbom, Admission, Delivery);
mapping!(action, AuditControlAction, AuditControlAction; Publish, Revoke, Retire,
    RenewEvidence, DeploymentApply, DeploymentDelete, Rollout, Promotion, Rollback);
mapping!(result, AuditOperationResult, AuditOperationResult; Committed, Rejected, NotStarted, Unknown);
mapping!(outcome, AuditOutcome, AuditObservationOutcome; Succeeded, Denied, Failed);
mapping!(cache, AuditCacheKind, AuditCacheKind; Raw, Prepared, Native);
mapping!(stop, AuditPageStop, AuditPageStop; End, RecordLimit, ByteLimit, ScanLimit);

const KINDS: [domain::Phase2AuditEventKind; 15] = {
    use domain::Phase2AuditEventKind::{
        CacheCorruption, CacheHit, CacheMiss, PromotionAccepted, PromotionRejected, ReleaseRetired,
        ReleaseRevoked, RollbackAccepted, RollbackRejected, RolloutAborted, RolloutPaused,
        RolloutStageChanged, RolloutStarted, VerificationAccepted, VerificationRejected,
    };
    [
        VerificationAccepted,
        VerificationRejected,
        ReleaseRevoked,
        ReleaseRetired,
        CacheHit,
        CacheMiss,
        CacheCorruption,
        RolloutStarted,
        RolloutStageChanged,
        RolloutPaused,
        RolloutAborted,
        PromotionAccepted,
        PromotionRejected,
        RollbackAccepted,
        RollbackRejected,
    ]
};
pub(super) fn kind_from_proto(value: i32) -> Result<domain::Phase2AuditEventKind, Status> {
    KINDS
        .into_iter()
        .find(|entry| kind(*entry) == value)
        .ok_or_else(|| Status::invalid_argument("invalid audit event kind"))
}
pub(super) fn kind_from_name(value: &str) -> Result<domain::Phase2AuditEventKind, Status> {
    KINDS
        .into_iter()
        .find(|entry| entry.wire_name() == value)
        .ok_or_else(|| Status::invalid_argument("unsupported audit action filter"))
}
pub(super) fn reason(value: domain::AuditReason) -> &'static str {
    use domain::AuditReason;
    match value {
        AuditReason::Verified => "verified",
        AuditReason::Rejected => "rejected",
        AuditReason::Admitted => "admitted",
        AuditReason::Revoked => "revoked",
        AuditReason::Retired => "retired",
        AuditReason::EvidenceRenewed => "evidence-renewed",
        AuditReason::GenerationConflict => "generation-conflict",
        AuditReason::PolicyDenied => "policy-denied",
        AuditReason::IntegrityMismatch => "integrity-mismatch",
        AuditReason::Capacity => "capacity",
        AuditReason::Unavailable => "unavailable",
        AuditReason::Unsupported => "unsupported",
        AuditReason::CacheHit => "cache-hit",
        AuditReason::CacheMiss => "cache-miss",
        AuditReason::CacheCorruption => "cache-corruption",
        AuditReason::Committed => "committed",
        AuditReason::NotStarted => "not-started",
        AuditReason::ReceiptUnavailable => "receipt-unavailable",
        AuditReason::MutationUncertain => "mutation-uncertain",
    }
}
pub(super) fn action_name(value: domain::AuditControlAction) -> &'static str {
    use domain::AuditControlAction;
    match value {
        AuditControlAction::Publish => "publish",
        AuditControlAction::Revoke => "revoke",
        AuditControlAction::Retire => "retire",
        AuditControlAction::RenewEvidence => "renew-evidence",
        AuditControlAction::DeploymentApply => "deployment-apply",
        AuditControlAction::DeploymentDelete => "deployment-delete",
        AuditControlAction::Rollout => "rollout",
        AuditControlAction::Promotion => "promotion",
        AuditControlAction::Rollback => "rollback",
    }
}
pub(super) fn actor_name(value: domain::AuditActorKind) -> &'static str {
    use domain::AuditActorKind;
    match value {
        AuditActorKind::User => "user",
        AuditActorKind::Service => "service",
        AuditActorKind::Node => "node",
        AuditActorKind::Trigger => "trigger",
        AuditActorKind::Administrator => "administrator",
        AuditActorKind::Anonymous => "anonymous",
        AuditActorKind::Host => "host",
    }
}
