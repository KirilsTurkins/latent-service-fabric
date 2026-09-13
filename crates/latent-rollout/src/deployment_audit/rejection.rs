use super::{check_deadline, mapping};
use latent_artifacts::ReleaseAuditAck;
use latent_audit::{
    AuditActorIdentity, AuditHandle, AuditIdentities, AuditOperationAttempt,
    AuditOperationConclusion, AuditOperationResult, AuditReason, AuditScope,
};
use latent_control_store::deployment_operations::DeploymentOperationRequest;
use latent_core::{PlatformError, PlatformErrorCode};
use std::time::Instant;

/// Compact rejected-attempt identity; never retains the request manifest.
pub struct DeploymentRejectionIdentity(AuditOperationAttempt);

impl DeploymentRejectionIdentity {
    #[must_use]
    pub fn request_digest(&self) -> &latent_core::ArtifactBlobDigest {
        &self.0.request_digest
    }

    /// Precharge `MAX_AUDIT_RETAINED_BYTES` before validation/digest scratch.
    pub fn from_request(request: &DeploymentOperationRequest) -> crate::Result<Self> {
        request.validate()?;
        let request_digest = request.request_digest()?;
        let context = request.context();
        let identities = AuditIdentities {
            deployment: Some(request.id().clone()),
            ..AuditIdentities::default()
        };
        let expected = AuditOperationAttempt {
            scope: AuditScope::Tenant(context.tenant.clone()),
            actor: AuditActorIdentity {
                kind: crate::audit::actor(context.actor.kind),
                subject: context.actor.subject.clone(),
            },
            operation_id: context.operation_id.clone(),
            request_digest,
            preview_receipt_digest: None,
            action: mapping::action(request.action()),
            identities: identities.clone(),
            replay: false,
            expected_generation: None,
            expected_deployment_generation: Some(request.expected_generation()),
            expected_rollout_revision: None,
            expected_rollback_target_generation: None,
            expected_state_version: Some(context.expected_state_version),
            occurred_at_unix_millis: crate::audit::now(),
        };
        Ok(Self(expected))
    }
}

/// The adapter must preflight its bounded failure response before calling this.
/// Only a validated request has a stable identity eligible for a rejected audit.
pub async fn record_rejection(
    audit: &AuditHandle,
    identity: DeploymentRejectionIdentity,
    failure: &PlatformError,
    expires: Instant,
) -> crate::Result<ReleaseAuditAck> {
    check_deadline(expires)?;
    let DeploymentRejectionIdentity(mut expected) = identity;
    expected.occurred_at_unix_millis = crate::audit::now();
    let reason = match failure.code {
        PlatformErrorCode::StateConflict => AuditReason::GenerationConflict,
        PlatformErrorCode::PermissionDenied => AuditReason::PolicyDenied,
        PlatformErrorCode::CorruptArtifact => AuditReason::IntegrityMismatch,
        PlatformErrorCode::ResourceExhausted => AuditReason::Capacity,
        PlatformErrorCode::Unavailable | PlatformErrorCode::NotFound => AuditReason::Unavailable,
        PlatformErrorCode::IncompatibleContract => AuditReason::Unsupported,
        _ => AuditReason::Rejected,
    };
    let terminal = AuditOperationConclusion {
        result: AuditOperationResult::Rejected,
        reason,
        receipt_digest: None,
        identities: expected.identities.clone(),
        replay: false,
        occurred_at_unix_millis: crate::audit::now(),
        canary_decision: None,
    };
    audit.preflight_conclusion(&expected, &terminal)?;
    audit.preflight_conclusion(&expected, &mapping::conclusion(&expected, None))?;
    let reservation = audit.try_reserve_critical(&expected)?;
    check_deadline(expires)?;
    let attempt = tokio::time::timeout_at(expires.into(), reservation.begin().wait())
        .await
        .map_err(|_| super::deadline())??;
    let sequence = attempt.sequence();
    let persisted = tokio::time::timeout_at(expires.into(), attempt.finish(terminal).wait())
        .await
        .is_ok_and(|result| result.is_ok())
        && Instant::now() < expires;
    Ok(crate::audit::ack(sequence, persisted))
}
