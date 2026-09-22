use latent_audit::{
    AuditActorIdentity, AuditControlAction, AuditIdentities, AuditOperationAttempt,
    AuditOperationConclusion, AuditOperationResult, AuditReason, AuditScope,
};
use latent_control_store::http_routes::{
    TriggerOperationAction, TriggerOperationReceipt, TriggerTargetIdentity,
};
use latent_core::{ArtifactBlobDigest, DeploymentId, RevisionId, RouteGeneration, TenantId};
use sha2::{Digest, Sha256};

fn digest(receipt: &TriggerOperationReceipt) -> crate::Result<ArtifactBlobDigest> {
    format!("sha256:{:x}", Sha256::digest(receipt.canonical_bytes()?))
        .parse()
        .map_err(|_| super::invalid())
}
fn identities(r: &TriggerOperationReceipt) -> crate::Result<AuditIdentities> {
    let target = r.target_identity().ok_or_else(super::invalid)?;
    let (component, deployment, deployment_generation, revision) = match &target {
        TriggerTargetIdentity::Application {
            component,
            deployment_id,
            deployment_generation,
            revision,
            ..
        } => (
            Some(component.clone()),
            Some(DeploymentId(deployment_id.clone())),
            Some(*deployment_generation),
            Some(RevisionId(revision.clone())),
        ),
        TriggerTargetIdentity::StaticWeb { .. } => (None, None, None, None),
    };
    Ok(AuditIdentities {
        trigger: Some(r.trigger_id.clone()),
        trigger_generation: Some(r.object_generation),
        publication: Some(target.publication().id.clone()),
        component,
        deployment,
        deployment_generation,
        revision,
        route_generation: Some(RouteGeneration(r.route_generation)),
        state_version: Some(r.state_version),
        ..AuditIdentities::default()
    })
}
fn action(action: TriggerOperationAction) -> AuditControlAction {
    match action {
        TriggerOperationAction::Apply => AuditControlAction::TriggerApply,
        TriggerOperationAction::Delete => AuditControlAction::TriggerDelete,
    }
}
pub(super) fn attempt(
    r: &TriggerOperationReceipt,
    replay: bool,
) -> crate::Result<AuditOperationAttempt> {
    let preview = digest(r)?;
    Ok(AuditOperationAttempt {
        scope: AuditScope::Tenant(TenantId(r.tenant.clone())),
        actor: AuditActorIdentity {
            kind: crate::audit::actor(r.actor.kind),
            subject: r.actor.subject.clone(),
        },
        operation_id: r.operation_id.clone(),
        request_digest: r.request_digest.parse().map_err(|_| super::invalid())?,
        preview_receipt_digest: Some(preview),
        action: action(r.action),
        identities: identities(r)?,
        replay,
        expected_generation: Some(r.expected_generation),
        expected_deployment_generation: r
            .target_identity()
            .and_then(|target| target.deployment_generation()),
        expected_rollout_revision: None,
        expected_rollback_target_generation: None,
        expected_state_version: Some(r.expected_state_version),
        occurred_at_unix_millis: crate::audit::now(),
    })
}
pub(super) fn matches(expected: &AuditOperationAttempt, receipt: &TriggerOperationReceipt) -> bool {
    attempt(receipt, expected.replay).is_ok_and(|mut actual| {
        actual.occurred_at_unix_millis = expected.occurred_at_unix_millis;
        actual == *expected
    })
}
pub(super) fn conclusion(
    expected: &AuditOperationAttempt,
    receipt: Option<&TriggerOperationReceipt>,
) -> AuditOperationConclusion {
    let receipt = receipt.filter(|r| matches(expected, r));
    AuditOperationConclusion {
        result: if receipt.is_some() {
            AuditOperationResult::Committed
        } else {
            AuditOperationResult::Unknown
        },
        reason: if receipt.is_some() {
            AuditReason::Committed
        } else {
            AuditReason::ReceiptUnavailable
        },
        receipt_digest: receipt.and_then(|r| digest(r).ok()),
        identities: expected.identities.clone(),
        replay: expected.replay,
        occurred_at_unix_millis: crate::audit::now(),
        canary_decision: None,
    }
}
