use crate::{invalid, Result};
pub(crate) mod canary;
mod pending;
use latent_artifacts::{ReleaseActorKind, ReleaseAuditAck, ReleaseAuditStatus};
use latent_audit::{
    AuditActorIdentity, AuditActorKind, AuditControlAction, AuditHandle, AuditIdentities,
    AuditOperationAttempt, AuditOperationConclusion, AuditOperationResult, AuditReason, AuditScope,
};
use latent_control_store::{
    rollouts::{RolloutAction, RolloutId, RolloutOperationLookup, RolloutOperationReceipt},
    DirectoryDeploymentRepository,
};
use latent_core::ArtifactBlobDigest;
use sha2::{Digest, Sha256};
use std::time::{Instant, SystemTime, UNIX_EPOCH};

pub(crate) fn now() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .ok()
        .and_then(|v| u64::try_from(v.as_millis()).ok())
        .unwrap_or(0)
}
pub(crate) fn digest(receipt: &RolloutOperationReceipt) -> Result<ArtifactBlobDigest> {
    format!("sha256:{:x}", Sha256::digest(receipt.canonical_bytes()?))
        .parse()
        .map_err(|_| invalid("rollout-receipt-digest"))
}
fn identities(receipt: &RolloutOperationReceipt) -> AuditIdentities {
    let mut identities = AuditIdentities {
        rollout: Some(receipt.rollout_id.0.clone()),
        rollout_revision: Some(receipt.revision),
        rollout_step: Some(receipt.step),
        state_version: Some(receipt.state_version),
        route_generation: Some(receipt.route_generation),
        rollback_target_generation: receipt
            .rollback_target
            .as_ref()
            .map(|target| target.historical_route_generation),
        ..AuditIdentities::default()
    };
    if let Some(decision) = &receipt.canary_decision {
        identities.canary_window_epoch = Some(decision.window_epoch);
        identities.canary_evidence_digest = Some(decision.evidence_digest.clone());
        identities.policies.push(latent_audit::AuditPolicyIdentity {
            role: latent_audit::AuditPolicyRole::Delivery,
            scope: receipt.rollout_id.0.clone(),
            generation: 1,
            digest: decision.policy_digest.clone(),
        });
    }
    identities
}
pub(crate) fn actor(kind: ReleaseActorKind) -> AuditActorKind {
    match kind {
        ReleaseActorKind::User => AuditActorKind::User,
        ReleaseActorKind::Service => AuditActorKind::Service,
        ReleaseActorKind::Node => AuditActorKind::Node,
        ReleaseActorKind::Trigger => AuditActorKind::Trigger,
        ReleaseActorKind::Administrator => AuditActorKind::Administrator,
        ReleaseActorKind::Anonymous => AuditActorKind::Anonymous,
        ReleaseActorKind::Host => AuditActorKind::Host,
    }
}
pub(crate) fn attempt(
    receipt: &RolloutOperationReceipt,
    replay: bool,
) -> Result<AuditOperationAttempt> {
    Ok(AuditOperationAttempt {
        expected_rollback_target_generation: receipt
            .rollback_target
            .as_ref()
            .map(|target| target.historical_route_generation),
        scope: AuditScope::Tenant(receipt.tenant.clone()),
        actor: AuditActorIdentity {
            kind: actor(receipt.actor.kind),
            subject: receipt.actor.subject.clone(),
        },
        operation_id: receipt.operation_id.clone(),
        request_digest: receipt.request_digest.clone(),
        preview_receipt_digest: Some(digest(receipt)?),
        action: action(receipt),
        identities: identities(receipt),
        replay,
        expected_generation: None,
        expected_deployment_generation: None,
        expected_rollout_revision: Some(receipt.expected_revision),
        occurred_at_unix_millis: now(),
    })
}
pub(crate) fn matches(attempt: &AuditOperationAttempt, receipt: &RolloutOperationReceipt) -> bool {
    attempt.action == action(receipt)
        && attempt.scope == AuditScope::Tenant(receipt.tenant.clone())
        && attempt.operation_id == receipt.operation_id
        && attempt.request_digest == receipt.request_digest
        && attempt.preview_receipt_digest == digest(receipt).ok()
        && attempt.preview_receipt_digest.is_some()
        && attempt.actor.kind == actor(receipt.actor.kind)
        && attempt.actor.subject == receipt.actor.subject
        && attempt.identities == identities(receipt)
        && attempt.expected_rollout_revision == Some(receipt.expected_revision)
        && attempt.expected_rollback_target_generation
            == receipt
                .rollback_target
                .as_ref()
                .map(|target| target.historical_route_generation)
        && attempt.expected_generation.is_none()
        && attempt.expected_deployment_generation.is_none()
}
pub(crate) fn conclusion(
    attempt: &AuditOperationAttempt,
    receipt: Option<&RolloutOperationReceipt>,
) -> AuditOperationConclusion {
    let known = receipt.filter(|receipt| matches(attempt, receipt));
    AuditOperationConclusion {
        canary_decision: None,
        result: if known.is_some() {
            AuditOperationResult::Committed
        } else {
            AuditOperationResult::Unknown
        },
        reason: if known.is_some() {
            AuditReason::Committed
        } else {
            AuditReason::ReceiptUnavailable
        },
        receipt_digest: known.and_then(|receipt| digest(receipt).ok()),
        identities: attempt.identities.clone(),
        replay: attempt.replay,
        occurred_at_unix_millis: now(),
    }
}
pub(crate) const fn ack(sequence: u64, known: bool) -> ReleaseAuditAck {
    ReleaseAuditAck {
        status: if known {
            ReleaseAuditStatus::Durable
        } else {
            ReleaseAuditStatus::OutcomeUnknown
        },
        attempt_sequence: Some(sequence),
    }
}
pub(crate) fn observe(audit: &AuditHandle, receipt: &RolloutOperationReceipt) {
    use latent_audit::{AuditObservation, AuditOutcome, Phase2AuditEventKind as Kind};
    let kind = match receipt.action {
        RolloutAction::Start => Kind::RolloutStarted,
        RolloutAction::Advance | RolloutAction::Resume => Kind::RolloutStageChanged,
        RolloutAction::Promote => Kind::PromotionAccepted,
        RolloutAction::Rollback => Kind::RollbackAccepted,
        RolloutAction::Pause => Kind::RolloutPaused,
        RolloutAction::Abort => Kind::RolloutAborted,
    };
    let _ = audit.try_capture(&AuditObservation {
        scope: AuditScope::Tenant(receipt.tenant.clone()),
        actor: AuditActorIdentity {
            kind: actor(receipt.actor.kind),
            subject: receipt.actor.subject.clone(),
        },
        kind,
        outcome: AuditOutcome::Succeeded,
        identities: identities(receipt),
        reason: AuditReason::Committed,
        cache_kind: None,
        occurred_at_unix_millis: now(),
    });
}

/// Reconcile rollout attempts before the generic release fallback, including
/// nodes that retain rollout history while management RPCs are disabled.
/// Only an exact, durably confirmed committed receipt proves success.
pub async fn reconcile_rollout_audit(
    audit: &AuditHandle,
    repository: &DirectoryDeploymentRepository,
    expires: Instant,
) -> Result<()> {
    if Instant::now() >= expires {
        return Err(crate::deadline());
    }
    for pending in pending::read(audit, expires).await? {
        if !matches!(
            pending.attempt.action,
            AuditControlAction::Rollout
                | AuditControlAction::Promotion
                | AuditControlAction::Rollback
        ) {
            continue;
        }
        if Instant::now() >= expires {
            return Err(crate::deadline());
        }
        let lookup = match (&pending.attempt.scope, &pending.attempt.identities.rollout) {
            (AuditScope::Tenant(tenant), Some(id)) => repository.get_rollout_operation(
                tenant,
                &RolloutId(id.clone()),
                &pending.attempt.operation_id,
            )?,
            _ => RolloutOperationLookup::Unknown,
        };
        let receipt = match &lookup {
            RolloutOperationLookup::Found(receipt) => Some(receipt),
            _ => None,
        };
        let mut terminal = conclusion(&pending.attempt, receipt);
        if let Some(receipt) = receipt.filter(|receipt| matches(&pending.attempt, receipt)) {
            match canary::from_receipt(repository, receipt) {
                Ok(summary) => terminal.canary_decision = summary,
                Err(_) => terminal = conclusion(&pending.attempt, None),
            }
        }
        let wait = audit.reconcile(pending.sequence, terminal)?.wait();
        tokio::time::timeout_at(expires.into(), wait)
            .await
            .map_err(|_| crate::deadline())??;
        if Instant::now() >= expires {
            return Err(crate::deadline());
        }
    }
    Ok(())
}

fn action(receipt: &RolloutOperationReceipt) -> AuditControlAction {
    match receipt.action {
        RolloutAction::Promote => AuditControlAction::Promotion,
        RolloutAction::Rollback => AuditControlAction::Rollback,
        RolloutAction::Start
        | RolloutAction::Advance
        | RolloutAction::Pause
        | RolloutAction::Resume
        | RolloutAction::Abort => AuditControlAction::Rollout,
    }
}
