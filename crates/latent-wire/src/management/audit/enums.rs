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
    RolloutPaused, RolloutAborted, PromotionAccepted, PromotionRejected, RollbackAccepted, RollbackRejected,
    CapabilityGrantAllowed, CapabilityGrantDenied, CapabilityProviderOutcome);
mapping!(actor, AuditActorKind, AuditActorKind; User, Service, Node, Trigger, Administrator, Anonymous, Host);
mapping!(policy, AuditPolicyRole, AuditPolicyRole; Publisher, PublisherRevocation, Builder,
    BuilderRevocation, Sbom, Admission, Delivery);
mapping!(action, AuditControlAction, AuditControlAction; Publish, Revoke, Retire,
    RenewEvidence, DeploymentApply, DeploymentDelete, TriggerApply, TriggerDelete, Rollout, Promotion, Rollback, CapabilityCall);
mapping!(capability_resource, AuditCapabilityResourceClass, AuditCapabilityResourceClass;
    Context, Clock, Random, Log, Http, Blob, Secrets, Events, Telemetry, Service);
mapping!(provider_outcome, AuditProviderOutcome, AuditProviderOutcome;
    NotStarted, LocalDispatchAccepted, HttpResponseReceived, BrokerAcknowledged, BlobSealed,
    SecretResolved, HostCompleted, Rejected, Unknown);
mapping!(capability_digest_scope, AuditCapabilityDigestScope, AuditCapabilityDigestScope;
    ResourceSelection, ProviderRequest);
mapping!(result, AuditOperationResult, AuditOperationResult; Committed, Rejected, NotStarted, Unknown);
mapping!(outcome, AuditOutcome, AuditObservationOutcome; Succeeded, Denied, Failed);
mapping!(cache, AuditCacheKind, AuditCacheKind; Raw, Prepared, Native);
mapping!(stop, AuditPageStop, AuditPageStop; End, RecordLimit, ByteLimit, ScanLimit);

const KINDS: [domain::Phase2AuditEventKind; 18] = {
    use domain::Phase2AuditEventKind::{
        CacheCorruption, CacheHit, CacheMiss, CapabilityGrantAllowed, CapabilityGrantDenied,
        CapabilityProviderOutcome, PromotionAccepted, PromotionRejected, ReleaseRetired,
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
        CapabilityGrantAllowed,
        CapabilityGrantDenied,
        CapabilityProviderOutcome,
    ]
};
pub(super) fn kind_from_proto(value: i32) -> Result<domain::Phase2AuditEventKind, Status> {
    KINDS
        .into_iter()
        .find(|entry| kind(*entry) == value)
        .ok_or_else(|| Status::invalid_argument("invalid audit event kind"))
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
        AuditReason::CanaryCollecting => "canary-collecting",
        AuditReason::CanaryDraining => "canary-draining",
        AuditReason::CanaryNoData => "canary-no-data",
        AuditReason::CanaryInsufficient => "canary-insufficient",
        AuditReason::CanaryIncomplete => "canary-incomplete",
        AuditReason::CanaryFailed => "canary-failed",
        AuditReason::CanaryUnavailable => "canary-unavailable",
    }
}
