use latent_audit::{
    AuditActorIdentity, AuditActorKind, AuditControlAction, AuditIdentities, AuditOperationAttempt,
    AuditOperationConclusion, AuditOperationResult, AuditPolicyIdentity, AuditPolicyRole,
    AuditReason, AuditScope,
};
use latent_core::{ArtifactBlobDigest, PlatformError};
use sha2::{Digest, Sha256};
use std::time::{SystemTime, UNIX_EPOCH};

use crate::{
    LifecycleScope, ReleaseActorKind, ReleaseLifecycleAction, ReleaseLifecycleReason,
    ReleaseOperationDisposition, ReleaseOperationReceipt,
};

pub(super) fn attempt(
    value: &ReleaseOperationReceipt,
    replay: bool,
) -> Result<AuditOperationAttempt, PlatformError> {
    let preview_receipt_digest = Some(receipt_digest(value)?);
    Ok(AuditOperationAttempt {
        scope: scope(&value.scope),
        actor: AuditActorIdentity {
            kind: actor(value.actor.kind),
            subject: value.actor.subject.clone(),
        },
        operation_id: value.operation_id.clone(),
        request_digest: value.request_digest.clone(),
        action: action(value.action),
        identities: identities(value),
        expected_generation: value.expected_generation,
        expected_deployment_generation: None,
        expected_rollout_revision: None,
        replay,
        preview_receipt_digest,
        occurred_at_unix_millis: now(),
    })
}

pub(super) fn conclusion(
    value: &ReleaseOperationReceipt,
    replay: bool,
) -> Result<AuditOperationConclusion, PlatformError> {
    let digest = receipt_digest(value)?;
    Ok(AuditOperationConclusion {
        result: match value.disposition {
            ReleaseOperationDisposition::Committed => AuditOperationResult::Committed,
            ReleaseOperationDisposition::Rejected => AuditOperationResult::Rejected,
        },
        reason: reason(value.reason),
        receipt_digest: Some(digest),
        identities: identities(value),
        replay,
        occurred_at_unix_millis: now(),
    })
}

fn receipt_digest(value: &ReleaseOperationReceipt) -> Result<ArtifactBlobDigest, PlatformError> {
    crate::lifecycle::validate_audit_receipt(value)?;
    // Validation bounds every field and canonical encoding to the existing
    // 8 KiB cap. The same binding covers preview, actual result and recovery.
    let bytes = serde_json::to_vec(value).map_err(|_| super::invalid())?;
    Ok(
        crate::content_hash::format_digest(Sha256::digest(&bytes).into())
            .0
            .parse()
            .expect("canonical receipt digest"),
    )
}

fn identities(value: &ReleaseOperationReceipt) -> AuditIdentities {
    AuditIdentities {
        package: value
            .record
            .as_ref()
            .and_then(|record| record.package.clone()),
        component: value.component_digest.clone(),
        received_manifest_digest: value.package_manifest_digest.clone(),
        evidence_revision_digest: value
            .record
            .as_ref()
            .and_then(|record| record.evidence_revision_digest.clone()),
        lifecycle_generation: value.record.as_ref().map(|record| record.generation),
        policies: value
            .policy
            .as_ref()
            .map(|policy| AuditPolicyIdentity {
                role: AuditPolicyRole::Admission,
                scope: policy.scope.clone(),
                generation: policy.generation,
                digest: policy.digest.clone(),
            })
            .into_iter()
            .collect(),
        ..Default::default()
    }
}

pub(super) fn matches(attempt: &AuditOperationAttempt, receipt: &ReleaseOperationReceipt) -> bool {
    let Ok(digest) = receipt_digest(receipt) else {
        return false;
    };
    attempt.preview_receipt_digest.as_ref() == Some(&digest)
        && attempt.scope == scope(&receipt.scope)
        && attempt.operation_id == receipt.operation_id
        && attempt.request_digest == receipt.request_digest
        && attempt.action == action(receipt.action)
        && attempt.actor.kind == actor(receipt.actor.kind)
        && attempt.actor.subject == receipt.actor.subject
        && attempt.expected_generation == receipt.expected_generation
}

fn scope(value: &LifecycleScope) -> AuditScope {
    match value {
        LifecycleScope::Tenant(tenant) => AuditScope::Tenant(tenant.clone()),
        LifecycleScope::LocalUnscoped => AuditScope::Node,
    }
}

pub(super) fn lifecycle_scope(value: &AuditScope) -> LifecycleScope {
    match value {
        AuditScope::Tenant(tenant) => LifecycleScope::Tenant(tenant.clone()),
        AuditScope::Node => LifecycleScope::LocalUnscoped,
    }
}

fn actor(value: ReleaseActorKind) -> AuditActorKind {
    match value {
        ReleaseActorKind::User => AuditActorKind::User,
        ReleaseActorKind::Service => AuditActorKind::Service,
        ReleaseActorKind::Node => AuditActorKind::Node,
        ReleaseActorKind::Trigger => AuditActorKind::Trigger,
        ReleaseActorKind::Administrator => AuditActorKind::Administrator,
        ReleaseActorKind::Anonymous => AuditActorKind::Anonymous,
        ReleaseActorKind::Host => AuditActorKind::Host,
    }
}

fn action(value: ReleaseLifecycleAction) -> AuditControlAction {
    match value {
        ReleaseLifecycleAction::Publish => AuditControlAction::Publish,
        ReleaseLifecycleAction::Revoke => AuditControlAction::Revoke,
        ReleaseLifecycleAction::Retire => AuditControlAction::Retire,
        ReleaseLifecycleAction::RenewEvidence => AuditControlAction::RenewEvidence,
    }
}

fn reason(value: ReleaseLifecycleReason) -> AuditReason {
    match value {
        ReleaseLifecycleReason::Admitted => AuditReason::Admitted,
        ReleaseLifecycleReason::EvidenceRenewed => AuditReason::EvidenceRenewed,
        ReleaseLifecycleReason::OperatorRevocation
        | ReleaseLifecycleReason::SecurityIncident
        | ReleaseLifecycleReason::CorruptContent
        | ReleaseLifecycleReason::ReleaseRevoked => AuditReason::Revoked,
        ReleaseLifecycleReason::Superseded
        | ReleaseLifecycleReason::EndOfSupport
        | ReleaseLifecycleReason::OperatorRetirement
        | ReleaseLifecycleReason::ReleaseRetired => AuditReason::Retired,
        ReleaseLifecycleReason::GenerationConflict => AuditReason::GenerationConflict,
        ReleaseLifecycleReason::PolicyDenied | ReleaseLifecycleReason::EvidenceRejected => {
            AuditReason::PolicyDenied
        }
        ReleaseLifecycleReason::IntegrityMismatch => AuditReason::IntegrityMismatch,
        ReleaseLifecycleReason::IncompatibleContract => AuditReason::Unsupported,
        ReleaseLifecycleReason::InvalidPackage | ReleaseLifecycleReason::ContentConflict => {
            AuditReason::Rejected
        }
    }
}

pub(super) fn now() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .ok()
        .and_then(|duration| u64::try_from(duration.as_millis()).ok())
        .unwrap_or(0)
}
