use super::PromotionInput;
use crate::{
    audit, coordinator::Shared, model::maximum_ack, worker::Job, CanaryEvaluationReport,
    MutationResult, PromotionPreview, Result,
};
use latent_audit::{
    AuditActorIdentity, AuditControlAction, AuditHandle, AuditIdentities, AuditOperationAttempt,
    AuditOperationConclusion, AuditOperationResult, AuditReason, AuditScope,
};
use latent_control_store::rollouts::{RolloutContext, RolloutId};
use latent_core::{ArtifactBlobDigest, PlatformError, PlatformErrorCode};
use latent_telemetry::CanaryVerdict;

#[expect(
    clippy::too_many_arguments,
    reason = "bounded worker-owned rejection context is explicit at the audit boundary"
)]
pub(super) async fn run(
    audit_handle: &AuditHandle,
    shared: &Shared,
    job: &mut Job<PromotionInput, MutationResult>,
    preflight: Box<dyn for<'a> FnOnce(PromotionPreview<'a>) -> Result<()> + Send>,
    context: &RolloutContext,
    id: &RolloutId,
    request_digest: ArtifactBlobDigest,
    decision: Option<&CanaryEvaluationReport>,
    audit_decision: Option<latent_audit::AuditCanaryDecision>,
    failure: PlatformError,
) -> Result<MutationResult> {
    let (failure, reason) = classify(failure, decision);
    preflight(PromotionPreview {
        receipt: None,
        decision,
        failure: Some(&failure),
        replayed: false,
        audit_ack: maximum_ack(),
        observation: decision.map(|report| report.observation),
    })?;
    job.check(shared)?;
    let mut identities = AuditIdentities {
        rollout: Some(id.0.clone()),
        rollout_revision: Some(context.operation.expected_revision),
        ..AuditIdentities::default()
    };
    if let Some(report) = decision {
        identities.rollout_step = Some(report.step);
        identities.route_generation = Some(report.route_generation);
        identities.canary_window_epoch = report.window_epoch;
        identities.policies.push(latent_audit::AuditPolicyIdentity {
            role: latent_audit::AuditPolicyRole::Delivery,
            scope: id.0.clone(),
            generation: 1,
            digest: report.policy_digest.clone(),
        });
    }
    let attempt = AuditOperationAttempt {
        expected_state_version: None,
        expected_rollback_target_generation: None,
        scope: AuditScope::Tenant(context.tenant.clone()),
        actor: AuditActorIdentity {
            kind: audit::actor(context.actor.kind),
            subject: context.actor.subject.clone(),
        },
        operation_id: context.operation.operation_id.clone(),
        request_digest,
        preview_receipt_digest: None,
        action: AuditControlAction::Promotion,
        identities: identities.clone(),
        replay: false,
        expected_generation: None,
        expected_deployment_generation: None,
        expected_rollout_revision: Some(context.operation.expected_revision),
        occurred_at_unix_millis: audit::now(),
    };
    let terminal = AuditOperationConclusion {
        result: AuditOperationResult::Rejected,
        canary_decision: audit_decision,
        reason,
        receipt_digest: None,
        identities,
        replay: false,
        occurred_at_unix_millis: audit::now(),
    };
    crate::worker::rejection::finish(audit_handle, shared, job, attempt, terminal, failure).await
}
fn classify(
    failure: PlatformError,
    decision: Option<&CanaryEvaluationReport>,
) -> (PlatformError, AuditReason) {
    let policy_rejection = failure.message == "rollout-canary-not-healthy";
    let observation_rejection = policy_rejection
        || matches!(
            failure.message.as_str(),
            "rollout-canary-evidence-required" | "rollout-canary-unavailable"
        );
    if failure.code == PlatformErrorCode::StateConflict && !policy_rejection {
        return (crate::bounded(failure), AuditReason::GenerationConflict);
    }
    if failure.code == PlatformErrorCode::ResourceExhausted {
        return (crate::bounded(failure), AuditReason::Capacity);
    }
    if !observation_rejection {
        let reason = match failure.code {
            PlatformErrorCode::PermissionDenied => AuditReason::PolicyDenied,
            PlatformErrorCode::Unavailable => AuditReason::Unavailable,
            PlatformErrorCode::CorruptArtifact => AuditReason::IntegrityMismatch,
            _ => AuditReason::Rejected,
        };
        return (crate::bounded(failure), reason);
    }
    let (message, reason) = match decision
        .and_then(|report| report.assessment)
        .map(|assessment| assessment.verdict)
    {
        Some(CanaryVerdict::Collecting) => {
            ("rollout-canary-collecting", AuditReason::CanaryCollecting)
        }
        Some(CanaryVerdict::Draining) => ("rollout-canary-draining", AuditReason::CanaryDraining),
        Some(CanaryVerdict::NoData) => ("rollout-canary-no-data", AuditReason::CanaryNoData),
        Some(CanaryVerdict::Insufficient) => (
            "rollout-canary-insufficient",
            AuditReason::CanaryInsufficient,
        ),
        Some(CanaryVerdict::Incomplete) => {
            ("rollout-canary-incomplete", AuditReason::CanaryIncomplete)
        }
        Some(CanaryVerdict::Failed) => ("rollout-canary-failed", AuditReason::CanaryFailed),
        _ => ("rollout-canary-unavailable", AuditReason::CanaryUnavailable),
    };
    (crate::error(failure.code, message), reason)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn trust_and_source_failures_are_not_reclassified_as_window_failures() {
        for (code, message, expected) in [
            (
                PlatformErrorCode::PermissionDenied,
                "release-grant-revoked",
                AuditReason::PolicyDenied,
            ),
            (
                PlatformErrorCode::Unavailable,
                "admission-authority-busy",
                AuditReason::Unavailable,
            ),
            (
                PlatformErrorCode::CorruptArtifact,
                "retained-package-corrupt",
                AuditReason::IntegrityMismatch,
            ),
        ] {
            let (failure, reason) = classify(crate::error(code, message), None);
            assert_eq!(failure.code, code);
            assert_eq!(reason, expected);
            assert!(!failure.message.starts_with("rollout-canary-"));
        }
    }
}
