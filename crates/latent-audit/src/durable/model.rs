use super::codec;
use crate::{AuditOutcome, Phase2AuditEventKind};
use latent_core::{
    ArtifactBlobDigest, DeploymentId, PackageDigest, ReleaseDigest, RevisionId, RouteGeneration,
    TenantId,
};
use serde::{Deserialize, Serialize};
mod canary;
pub use canary::{AuditCanaryDecision, AuditCanaryReason, AuditCanaryVerdict};

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum AuditScope {
    Tenant(TenantId),
    Node,
}
#[derive(Serialize, Deserialize)]
#[serde(
    tag = "kind",
    content = "tenant",
    rename_all = "kebab-case",
    deny_unknown_fields
)]
enum ScopeWire {
    Tenant(String),
    Node,
}
impl Serialize for AuditScope {
    fn serialize<S: serde::Serializer>(&self, s: S) -> std::result::Result<S::Ok, S::Error> {
        match self {
            Self::Tenant(t) => ScopeWire::Tenant(t.0.clone()),
            Self::Node => ScopeWire::Node,
        }
        .serialize(s)
    }
}
impl<'de> Deserialize<'de> for AuditScope {
    fn deserialize<D: serde::Deserializer<'de>>(d: D) -> std::result::Result<Self, D::Error> {
        Ok(match ScopeWire::deserialize(d)? {
            ScopeWire::Tenant(t) => Self::Tenant(TenantId(t)),
            ScopeWire::Node => Self::Node,
        })
    }
}
macro_rules! enumeration {
    ($name:ident { $($variant:ident),* $(,)? }) => {
        #[derive(Debug,Clone,Copy,PartialEq,Eq,Serialize,Deserialize)]
        #[serde(rename_all="kebab-case")]
        pub enum $name { $($variant),* }
    };
}
enumeration!(AuditActorKind {
    User,
    Service,
    Node,
    Trigger,
    Administrator,
    Anonymous,
    Host
});
enumeration!(AuditPolicyRole {
    Publisher,
    PublisherRevocation,
    Builder,
    BuilderRevocation,
    Sbom,
    Admission,
    Delivery
});
enumeration!(AuditControlAction {
    Publish,
    Revoke,
    Retire,
    RenewEvidence,
    DeploymentApply,
    DeploymentDelete,
    Rollout,
    Promotion,
    Rollback
});
enumeration!(AuditOperationResult {
    Committed,
    Rejected,
    NotStarted,
    Unknown
});
enumeration!(AuditReason {
    Verified,
    Rejected,
    Admitted,
    Revoked,
    Retired,
    EvidenceRenewed,
    GenerationConflict,
    PolicyDenied,
    IntegrityMismatch,
    Capacity,
    Unavailable,
    Unsupported,
    CacheHit,
    CacheMiss,
    CacheCorruption,
    Committed,
    NotStarted,
    ReceiptUnavailable,
    MutationUncertain,
    CanaryCollecting,
    CanaryDraining,
    CanaryNoData,
    CanaryInsufficient,
    CanaryIncomplete,
    CanaryFailed,
    CanaryUnavailable
});
enumeration!(AuditCacheKind {
    Raw,
    Prepared,
    Native
});
enumeration!(AuditPageStop {
    End,
    RecordLimit,
    ByteLimit,
    ScanLimit
});

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct AuditActorIdentity {
    pub kind: AuditActorKind,
    pub subject: String,
}
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct AuditPolicyIdentity {
    pub role: AuditPolicyRole,
    pub scope: String,
    pub generation: u64,
    #[serde(with = "codec::text")]
    pub digest: ArtifactBlobDigest,
}
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct AuditIdentities {
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        with = "codec::generation"
    )]
    pub rollback_target_generation: Option<RouteGeneration>,
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        deserialize_with = "codec::present"
    )]
    pub canary_window_epoch: Option<u64>,
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        with = "codec::optional"
    )]
    pub canary_evidence_digest: Option<ArtifactBlobDigest>,
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        with = "codec::optional"
    )]
    pub package: Option<PackageDigest>,
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        with = "codec::optional"
    )]
    pub component: Option<ReleaseDigest>,
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        with = "codec::optional"
    )]
    pub received_manifest_digest: Option<ArtifactBlobDigest>,
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        with = "codec::optional"
    )]
    pub evidence_revision_digest: Option<ArtifactBlobDigest>,
    pub policies: Vec<AuditPolicyIdentity>,
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        with = "codec::optional"
    )]
    pub deployment: Option<DeploymentId>,
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        deserialize_with = "codec::present"
    )]
    pub deployment_generation: Option<u64>,
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        deserialize_with = "codec::present"
    )]
    pub rollout: Option<String>,
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        deserialize_with = "codec::present"
    )]
    pub rollout_revision: Option<u64>,
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        deserialize_with = "codec::present"
    )]
    pub rollout_step: Option<u32>,
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        deserialize_with = "codec::present"
    )]
    pub state_version: Option<u64>,
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        with = "codec::optional"
    )]
    pub revision: Option<RevisionId>,
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        with = "codec::generation"
    )]
    pub route_generation: Option<RouteGeneration>,
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        deserialize_with = "codec::present"
    )]
    pub lifecycle_generation: Option<u64>,
}
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct AuditOperationAttempt {
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        deserialize_with = "codec::present"
    )]
    pub expected_state_version: Option<u64>,
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        with = "codec::generation"
    )]
    pub expected_rollback_target_generation: Option<RouteGeneration>,
    pub scope: AuditScope,
    pub actor: AuditActorIdentity,
    pub operation_id: String,
    #[serde(with = "codec::text")]
    pub request_digest: ArtifactBlobDigest,
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        with = "codec::optional"
    )]
    pub preview_receipt_digest: Option<ArtifactBlobDigest>,
    pub action: AuditControlAction,
    pub identities: AuditIdentities,
    pub replay: bool,
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        deserialize_with = "codec::present"
    )]
    pub expected_generation: Option<u64>,
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        deserialize_with = "codec::present"
    )]
    pub expected_deployment_generation: Option<u64>,
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        deserialize_with = "codec::present"
    )]
    pub expected_rollout_revision: Option<u64>,
    pub occurred_at_unix_millis: u64,
}
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct AuditOperationConclusion {
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        deserialize_with = "codec::present"
    )]
    pub canary_decision: Option<AuditCanaryDecision>,
    pub result: AuditOperationResult,
    pub reason: AuditReason,
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        with = "codec::optional"
    )]
    pub receipt_digest: Option<ArtifactBlobDigest>,
    pub identities: AuditIdentities,
    pub replay: bool,
    pub occurred_at_unix_millis: u64,
}
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct AuditObservation {
    pub scope: AuditScope,
    pub actor: AuditActorIdentity,
    pub kind: Phase2AuditEventKind,
    pub outcome: AuditOutcome,
    pub identities: AuditIdentities,
    pub reason: AuditReason,
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        deserialize_with = "codec::present"
    )]
    pub cache_kind: Option<AuditCacheKind>,
    pub occurred_at_unix_millis: u64,
}
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(
    tag = "kind",
    content = "value",
    rename_all = "kebab-case",
    rename_all_fields = "camelCase",
    deny_unknown_fields
)]
pub enum AuditRecordData {
    Observation(AuditObservation),
    Attempt(AuditOperationAttempt),
    Outcome {
        attempt_sequence: u64,
        conclusion: AuditOperationConclusion,
    },
}
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct AuditStoredRecord {
    pub format_version: u32,
    pub epoch: String,
    pub sequence: u64,
    pub previous_digest: String,
    pub accepted_at_unix_millis: u64,
    pub scope: AuditScope,
    pub actor: AuditActorIdentity,
    pub data: AuditRecordData,
}
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DurableAuditAck {
    pub epoch: String,
    pub sequence: u64,
    pub digest: ArtifactBlobDigest,
}
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AuditPendingAttempt {
    pub sequence: u64,
    pub attempt: AuditOperationAttempt,
}
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct AuditFilter {
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        deserialize_with = "codec::present"
    )]
    pub kind: Option<Phase2AuditEventKind>,
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        deserialize_with = "codec::present"
    )]
    pub actor: Option<String>,
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        deserialize_with = "codec::present"
    )]
    pub from_unix_millis: Option<u64>,
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        deserialize_with = "codec::present"
    )]
    pub to_unix_millis: Option<u64>,
}
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AuditCursor(pub String);
#[derive(Debug, Clone)]
pub struct AuditQueryRequest {
    pub scope: AuditScope,
    pub filter: AuditFilter,
    pub cursor: Option<AuditCursor>,
    pub limit: usize,
    pub maximum_bytes: usize,
}
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AuditPageCoverage {
    pub epoch: String,
    pub retained_floor: u64,
    pub high_watermark: u64,
    pub scanned: usize,
    pub stop: AuditPageStop,
    pub dropped_observations: u64,
    pub unknown_outcomes: u64,
    pub previous_session_loss_unknown: bool,
}
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct AuditSnapshot {
    pub retained_records: usize,
    pub retained_bytes: usize,
    pub reserved_records: usize,
    pub reserved_bytes: usize,
    pub queued_operations: usize,
    pub queued_bytes: usize,
    pub query_owners: usize,
    pub query_bytes: usize,
    pub pending_attempts: usize,
    pub next_sequence: u64,
    pub dropped_observations: u64,
    pub unknown_outcomes: u64,
    pub unavailable_events: u64,
    pub stage_bytes: usize,
    pub recovery_pending: bool,
    pub closed: bool,
    pub previous_session_loss_unknown: bool,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn absent_rollout_fields_preserve_old_canonical_identity_bytes() {
        let old = br#"{"policies":[]}"#;
        let decoded: AuditIdentities = serde_json::from_slice(old).unwrap();
        assert_eq!(serde_json::to_vec(&decoded).unwrap(), old);
        assert_eq!(decoded, AuditIdentities::default());
    }

    #[test]
    fn canary_evidence_fields_require_exact_rollout_and_positive_epoch() {
        let valid = AuditIdentities {
            rollout: Some("rollout".into()),
            canary_window_epoch: Some(7),
            canary_evidence_digest: Some(format!("sha256:{}", "a".repeat(64)).parse().unwrap()),
            ..AuditIdentities::default()
        };
        codec::identities(&valid).unwrap();
        for invalid in [
            AuditIdentities {
                rollout: None,
                ..valid.clone()
            },
            AuditIdentities {
                canary_window_epoch: None,
                ..valid.clone()
            },
            AuditIdentities {
                canary_window_epoch: Some(0),
                ..valid.clone()
            },
        ] {
            assert!(codec::identities(&invalid).is_err());
        }
        for name in ["canaryWindowEpoch", "canaryEvidenceDigest"] {
            let mut value = serde_json::to_value(&valid).unwrap();
            value[name] = serde_json::Value::Null;
            assert!(serde_json::from_value::<AuditIdentities>(value).is_err());
        }
    }

    #[test]
    fn rollout_counters_are_typed_bounded_and_require_their_identity() {
        let valid = AuditIdentities {
            rollout: Some("rollout".into()),
            rollout_revision: Some(1),
            rollout_step: Some(0),
            state_version: Some(2),
            ..AuditIdentities::default()
        };
        codec::identities(&valid).unwrap();
        let bytes = serde_json::to_vec(&valid).unwrap();
        assert_eq!(
            serde_json::from_slice::<AuditIdentities>(&bytes).unwrap(),
            valid
        );
        for value in [
            AuditIdentities {
                rollout: None,
                ..valid.clone()
            },
            AuditIdentities {
                rollout_revision: Some(0),
                ..valid.clone()
            },
            AuditIdentities {
                state_version: Some(0),
                ..valid.clone()
            },
            AuditIdentities {
                rollout_step: Some(64),
                ..valid.clone()
            },
        ] {
            assert!(codec::identities(&value).is_err());
        }
        for name in ["rolloutRevision", "rolloutStep", "stateVersion"] {
            let mut value = serde_json::to_value(&valid).unwrap();
            value[name] = serde_json::Value::Null;
            assert!(serde_json::from_value::<AuditIdentities>(value).is_err());
        }
    }
}
