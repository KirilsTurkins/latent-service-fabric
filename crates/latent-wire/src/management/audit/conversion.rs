use super::{enums, proto};
use latent_audit as domain;
use tonic::Status;

pub(super) fn scope(
    records: &[domain::AuditStoredRecord],
    expected: &domain::AuditScope,
) -> Result<(), Status> {
    if records.iter().any(|record| &record.scope != expected) {
        Err(Status::internal("audit query returned another scope"))
    } else {
        Ok(())
    }
}
fn scope_to_proto(value: domain::AuditScope) -> proto::AuditQueryScope {
    match value {
        domain::AuditScope::Tenant(tenant) => proto::AuditQueryScope {
            kind: proto::AuditScopeKind::Tenant as i32,
            tenant: Some(tenant.0),
        },
        domain::AuditScope::Node => proto::AuditQueryScope {
            kind: proto::AuditScopeKind::Node as i32,
            tenant: None,
        },
    }
}
pub(super) fn identities(value: domain::AuditIdentities) -> proto::AuditIdentities {
    proto::AuditIdentities {
        package_digest: value.package.map(latent_core::PackageDigest::into_string),
        component_digest: value.component.map(|value| value.0),
        policies: value
            .policies
            .into_iter()
            .map(|policy| proto::AuditPolicyIdentity {
                role: enums::policy(policy.role),
                scope: policy.scope,
                generation: policy.generation,
                digest: policy.digest.into_string(),
            })
            .collect(),
        rollout: value.rollout,
        revision: value.revision.map(|value| value.0),
        route_generation: value.route_generation.map(|value| value.0),
        lifecycle_generation: value.lifecycle_generation,
        received_manifest_digest: value
            .received_manifest_digest
            .map(latent_core::ArtifactBlobDigest::into_string),
        evidence_revision_digest: value
            .evidence_revision_digest
            .map(latent_core::ArtifactBlobDigest::into_string),
        deployment: value.deployment.map(|value| value.0),
        deployment_generation: value.deployment_generation,
    }
}
pub(super) fn record(value: domain::AuditStoredRecord) -> Result<proto::Phase2AuditRecord, Status> {
    use proto::phase2_audit_record::Data;
    let data = match value.data {
        domain::AuditRecordData::Observation(observation) => {
            if observation.scope != value.scope || observation.actor != value.actor {
                return Err(Status::internal("audit observation association changed"));
            }
            Data::Observation(proto::Phase2AuditObservation {
                kind: enums::kind(observation.kind),
                outcome: enums::outcome(observation.outcome),
                identities: Some(identities(observation.identities)),
                reason: enums::reason(observation.reason).into(),
                cache_kind: observation.cache_kind.map(enums::cache),
                occurred_at_unix_millis: observation.occurred_at_unix_millis,
            })
        }
        domain::AuditRecordData::Attempt(attempt) => {
            if attempt.scope != value.scope || attempt.actor != value.actor {
                return Err(Status::internal("audit attempt association changed"));
            }
            Data::Attempt(proto::Phase2AuditAttempt {
                operation_id: attempt.operation_id,
                request_digest: attempt.request_digest.into_string(),
                action: enums::action(attempt.action),
                identities: Some(identities(attempt.identities)),
                expected_generation: attempt.expected_generation,
                occurred_at_unix_millis: attempt.occurred_at_unix_millis,
                replay: attempt.replay,
                expected_deployment_generation: attempt.expected_deployment_generation,
                preview_receipt_digest: attempt
                    .preview_receipt_digest
                    .map(latent_core::ArtifactBlobDigest::into_string),
            })
        }
        domain::AuditRecordData::Outcome {
            attempt_sequence,
            conclusion,
        } => Data::Outcome(proto::Phase2AuditOutcome {
            attempt_sequence,
            result: enums::result(conclusion.result),
            reason: enums::reason(conclusion.reason).into(),
            receipt_digest: conclusion
                .receipt_digest
                .map(latent_core::ArtifactBlobDigest::into_string),
            identities: Some(identities(conclusion.identities)),
            replay: conclusion.replay,
            occurred_at_unix_millis: conclusion.occurred_at_unix_millis,
        }),
    };
    Ok(proto::Phase2AuditRecord {
        format_version: value.format_version,
        epoch: value.epoch,
        sequence: value.sequence,
        previous_digest: value.previous_digest,
        accepted_at_unix_millis: value.accepted_at_unix_millis,
        scope: Some(scope_to_proto(value.scope)),
        actor: Some(proto::AuditActorIdentity {
            kind: enums::actor(value.actor.kind),
            subject: value.actor.subject,
        }),
        data: Some(data),
    })
}
pub(super) fn coverage(value: domain::AuditPageCoverage) -> proto::AuditQueryCoverage {
    proto::AuditQueryCoverage {
        epoch: value.epoch,
        retained_floor: value.retained_floor,
        high_watermark: value.high_watermark,
        scanned: value.scanned as u64,
        stop: enums::stop(value.stop),
        dropped_observations: value.dropped_observations,
        unknown_outcomes: value.unknown_outcomes,
        previous_session_loss_unknown: value.previous_session_loss_unknown,
    }
}
