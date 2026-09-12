use latent_audit::{
    AuditActorIdentity, AuditControlAction, AuditIdentities, AuditOperationAttempt,
    AuditOperationConclusion, AuditOperationResult, AuditReason, AuditScope,
};
use latent_control_store::deployment_operations::{
    DeploymentOperationAction, DeploymentOperationReceipt,
};
use latent_core::ArtifactBlobDigest;
use sha2::{Digest, Sha256};

fn digest(receipt: &DeploymentOperationReceipt) -> crate::Result<ArtifactBlobDigest> {
    format!("sha256:{:x}", Sha256::digest(receipt.canonical_bytes()?))
        .parse()
        .map_err(|_| super::invalid())
}
fn identities(receipt: &DeploymentOperationReceipt) -> AuditIdentities {
    AuditIdentities {
        deployment: Some(receipt.deployment_id.clone()),
        component: Some(receipt.component.clone()),
        deployment_generation: Some(receipt.object_generation),
        route_generation: Some(receipt.route_generation),
        state_version: Some(receipt.state_version),
        ..AuditIdentities::default()
    }
}
pub(super) fn action(action: DeploymentOperationAction) -> AuditControlAction {
    match action {
        DeploymentOperationAction::Apply => AuditControlAction::DeploymentApply,
        DeploymentOperationAction::Delete => AuditControlAction::DeploymentDelete,
    }
}
pub(super) fn attempt(
    receipt: &DeploymentOperationReceipt,
    replay: bool,
) -> crate::Result<AuditOperationAttempt> {
    // Validate bounded receipt syntax before copying any caller-owned strings.
    let receipt_digest = digest(receipt)?;
    Ok(AuditOperationAttempt {
        scope: AuditScope::Tenant(receipt.tenant.clone()),
        actor: AuditActorIdentity {
            kind: crate::audit::actor(receipt.actor.kind),
            subject: receipt.actor.subject.clone(),
        },
        operation_id: receipt.operation_id.clone(),
        request_digest: receipt.request_digest.clone(),
        preview_receipt_digest: Some(receipt_digest),
        action: action(receipt.action),
        identities: identities(receipt),
        replay,
        expected_generation: None,
        expected_deployment_generation: Some(receipt.expected_generation),
        expected_rollout_revision: None,
        expected_rollback_target_generation: None,
        expected_state_version: Some(receipt.expected_state_version),
        occurred_at_unix_millis: crate::audit::now(),
    })
}
pub(super) fn matches(
    expected: &AuditOperationAttempt,
    receipt: &DeploymentOperationReceipt,
) -> bool {
    expected.scope == AuditScope::Tenant(receipt.tenant.clone())
        && expected.actor.kind == crate::audit::actor(receipt.actor.kind)
        && expected.actor.subject == receipt.actor.subject
        && expected.operation_id == receipt.operation_id
        && expected.action == action(receipt.action)
        && expected.request_digest == receipt.request_digest
        && expected.preview_receipt_digest.is_some()
        && expected.preview_receipt_digest == digest(receipt).ok()
        && expected.identities == identities(receipt)
        && expected.expected_deployment_generation == Some(receipt.expected_generation)
        && expected.expected_state_version == Some(receipt.expected_state_version)
        && expected.expected_generation.is_none()
        && expected.expected_rollout_revision.is_none()
        && expected.expected_rollback_target_generation.is_none()
}
pub(super) fn conclusion(
    expected: &AuditOperationAttempt,
    receipt: Option<&DeploymentOperationReceipt>,
) -> AuditOperationConclusion {
    let receipt = receipt.filter(|receipt| matches(expected, receipt));
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
        receipt_digest: receipt.and_then(|receipt| digest(receipt).ok()),
        identities: expected.identities.clone(),
        replay: expected.replay,
        occurred_at_unix_millis: crate::audit::now(),
        canary_decision: None,
    }
}
