//! Loss-aware typed clients use `QueryPhase2Audit`; this retains the older projection.
use super::{enums, proto};
use latent_audit as domain;
use std::collections::HashMap;

pub(super) fn record(value: domain::AuditStoredRecord) -> proto::AuditEvent {
    let mut attributes = HashMap::new();
    attributes.insert("audit.sequence".into(), value.sequence.to_string());
    let (action, outcome, reason, time, identities) = match value.data {
        domain::AuditRecordData::Observation(observation) => (
            observation.kind.wire_name(),
            match observation.outcome {
                domain::AuditOutcome::Succeeded => "succeeded",
                domain::AuditOutcome::Denied => "denied",
                domain::AuditOutcome::Failed => "failed",
            },
            observation.reason,
            observation.occurred_at_unix_millis,
            observation.identities,
        ),
        domain::AuditRecordData::Attempt(attempt) => {
            attributes.insert("audit.operationId".into(), attempt.operation_id);
            attributes.insert(
                "audit.requestDigest".into(),
                attempt.request_digest.into_string(),
            );
            (
                enums::action_name(attempt.action),
                "attempted",
                domain::AuditReason::NotStarted,
                attempt.occurred_at_unix_millis,
                attempt.identities,
            )
        }
        domain::AuditRecordData::Outcome {
            attempt_sequence,
            conclusion,
        } => {
            attributes.insert("audit.attemptSequence".into(), attempt_sequence.to_string());
            (
                "operation-outcome",
                match conclusion.result {
                    domain::AuditOperationResult::Committed => "succeeded",
                    domain::AuditOperationResult::Rejected => "denied",
                    domain::AuditOperationResult::NotStarted => "not-started",
                    domain::AuditOperationResult::Unknown => "unknown",
                },
                conclusion.reason,
                conclusion.occurred_at_unix_millis,
                conclusion.identities,
            )
        }
    };
    let resource = identities
        .package
        .map(latent_core::PackageDigest::into_string)
        .or_else(|| identities.component.map(|value| value.0))
        .or(identities.rollout)
        .unwrap_or_else(|| "audit-operation".into());
    proto::AuditEvent {
        id: format!("{}:{}", value.epoch, value.sequence),
        actor: Some(proto::AuditActor {
            subject: value.actor.subject,
            actor_type: enums::actor_name(value.actor.kind).into(),
            tenant: match value.scope {
                domain::AuditScope::Tenant(tenant) => Some(tenant.0),
                domain::AuditScope::Node => None,
            },
            attributes: HashMap::new(),
        }),
        action: action.into(),
        resource,
        outcome: outcome.into(),
        occurred_at_unix_millis: time,
        reason: Some(enums::reason(reason).into()),
        attributes,
    }
}
