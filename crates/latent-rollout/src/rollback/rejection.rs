use super::{RollbackInput, RollbackPreview};
use crate::{audit, coordinator::Shared, model::maximum_ack, worker::Job, MutationResult, Result};
use latent_audit::{
    AuditActorIdentity, AuditControlAction, AuditHandle, AuditIdentities, AuditOperationAttempt,
    AuditOperationConclusion, AuditOperationResult, AuditReason, AuditScope,
};
use latent_control_store::rollouts::{RolloutContext, RolloutId};
use latent_core::{ArtifactBlobDigest, PlatformError, PlatformErrorCode, RouteGeneration};

#[expect(
    clippy::too_many_arguments,
    reason = "explicit bounded caller/preflight context remains owned through durable rejection"
)]
pub(super) async fn run(
    audit_handle: &AuditHandle,
    shared: &Shared,
    job: &mut Job<RollbackInput, MutationResult>,
    preflight: Box<dyn for<'a> FnOnce(RollbackPreview<'a>) -> Result<()> + Send>,
    context: &RolloutContext,
    id: &RolloutId,
    target_generation: RouteGeneration,
    request_digest: ArtifactBlobDigest,
    failure: PlatformError,
) -> Result<MutationResult> {
    let reason = match failure.code {
        PlatformErrorCode::StateConflict => AuditReason::GenerationConflict,
        PlatformErrorCode::PermissionDenied => AuditReason::PolicyDenied,
        PlatformErrorCode::CorruptArtifact => AuditReason::IntegrityMismatch,
        PlatformErrorCode::ResourceExhausted => AuditReason::Capacity,
        PlatformErrorCode::Unavailable | PlatformErrorCode::NotFound => AuditReason::Unavailable,
        PlatformErrorCode::IncompatibleContract => AuditReason::Unsupported,
        _ => AuditReason::Rejected,
    };
    let failure = crate::bounded(failure);
    preflight(RollbackPreview {
        receipt: None,
        failure: Some(&failure),
        replayed: false,
        audit_ack: maximum_ack(),
        observation: None,
    })?;
    job.check(shared)?;
    let identities = AuditIdentities {
        rollout: Some(id.0.clone()),
        rollout_revision: Some(context.operation.expected_revision),
        ..AuditIdentities::default()
    };
    let attempt = AuditOperationAttempt {
        expected_rollback_target_generation: Some(target_generation),
        scope: AuditScope::Tenant(context.tenant.clone()),
        actor: AuditActorIdentity {
            kind: audit::actor(context.actor.kind),
            subject: context.actor.subject.clone(),
        },
        operation_id: context.operation.operation_id.clone(),
        request_digest,
        preview_receipt_digest: None,
        action: AuditControlAction::Rollback,
        identities: identities.clone(),
        replay: false,
        expected_generation: None,
        expected_deployment_generation: None,
        expected_rollout_revision: Some(context.operation.expected_revision),
        occurred_at_unix_millis: audit::now(),
    };
    let terminal = AuditOperationConclusion {
        canary_decision: None,
        result: AuditOperationResult::Rejected,
        reason,
        receipt_digest: None,
        identities,
        replay: false,
        occurred_at_unix_millis: audit::now(),
    };
    crate::worker::rejection::finish(audit_handle, shared, job, attempt, terminal, failure).await
}
