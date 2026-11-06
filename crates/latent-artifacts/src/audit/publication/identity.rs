use super::{
    invalid, PublicationMaintenanceReceipt as Receipt, PublicationMaintenanceRequest as Request,
    PublicationMaintenanceResult,
};
use crate::{LifecycleScope, PublicationRetentionAction, ReleaseActor};
use latent_audit::{
    AuditActorIdentity, AuditControlAction as Action, AuditIdentities, AuditOperationAttempt,
    AuditOperationConclusion, AuditOperationResult, AuditReason,
};
use latent_core::{ArtifactBlobDigest, PlatformError};
use serde::Serialize;
use sha2::{Digest, Sha256};
use std::io::{self, Write};

pub(super) fn owns(action: Action) -> bool {
    matches!(
        action,
        Action::PublicationPin
            | Action::PublicationUnpin
            | Action::PublicationDelete
            | Action::PublicationReclaim
    )
}

pub(super) fn request(receipt: &Receipt) -> Request {
    match receipt {
        Receipt::Retention(v) => Request::Retention(v.request.clone()),
        Receipt::Deletion(v) => Request::Deletion(v.request.clone()),
        Receipt::Reclamation(v) => Request::Reclamation(v.request.clone()),
    }
}

pub(super) fn attempt(
    requested: &Request,
    result: &PublicationMaintenanceResult,
) -> Result<AuditOperationAttempt, PlatformError> {
    if request(&result.receipt) != *requested {
        return Err(invalid());
    }
    let (scope, actor, operation_id, action): (&LifecycleScope, &ReleaseActor, &str, Action) =
        match requested {
            Request::Retention(v) => {
                v.validate()?;
                (
                    &v.scope,
                    &v.actor,
                    &v.operation_id,
                    match v.action {
                        PublicationRetentionAction::Pin => Action::PublicationPin,
                        PublicationRetentionAction::Unpin => Action::PublicationUnpin,
                    },
                )
            }
            Request::Deletion(v) => {
                v.validate()?;
                (
                    &v.scope,
                    &v.actor,
                    &v.operation_id,
                    Action::PublicationDelete,
                )
            }
            Request::Reclamation(v) => {
                v.validate()?;
                (
                    &v.deletion.scope,
                    &v.deletion.actor,
                    &v.deletion.operation_id,
                    Action::PublicationReclaim,
                )
            }
        };
    Ok(AuditOperationAttempt {
        scope: super::super::mapping::scope(scope),
        actor: AuditActorIdentity {
            kind: super::super::mapping::actor(actor.kind),
            subject: actor.subject.clone(),
        },
        operation_id: operation_id.to_owned(),
        action,
        // These canonical, domain-separated bounded digests bind the complete
        // sorted batch, scope, actor, every generation, fence and work limit.
        // No fake single-target or component identity represents a batch.
        request_digest: hash(b"lsf-publication-maintenance-request-v1\0", requested)?,
        preview_receipt_digest: Some(hash(
            b"lsf-publication-maintenance-receipt-v1\0",
            &result.receipt,
        )?),
        identities: AuditIdentities::default(),
        expected_generation: None,
        expected_deployment_generation: None,
        expected_rollout_revision: None,
        expected_state_version: None,
        expected_rollback_target_generation: None,
        replay: result.replay,
        occurred_at_unix_millis: super::super::mapping::now(),
    })
}

pub(super) fn committed(identity: &AuditOperationAttempt) -> AuditOperationConclusion {
    AuditOperationConclusion {
        result: AuditOperationResult::Committed,
        reason: AuditReason::Committed,
        receipt_digest: identity.preview_receipt_digest.clone(),
        identities: AuditIdentities::default(),
        replay: identity.replay,
        canary_decision: None,
        occurred_at_unix_millis: super::super::mapping::now(),
    }
}
pub(super) fn unknown() -> AuditOperationConclusion {
    super::super::unknown()
}

// Hash directly into a fixed-size state. Even a malformed oversized host value
// cannot allocate an unbounded temporary JSON buffer during audit preflight.
fn hash(domain: &[u8], value: &impl Serialize) -> Result<ArtifactBlobDigest, PlatformError> {
    struct BoundedHash {
        hash: Sha256,
        remaining: usize,
    }
    impl Write for BoundedHash {
        fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
            self.remaining = self
                .remaining
                .checked_sub(bytes.len())
                .ok_or_else(|| io::Error::other("publication audit bound"))?;
            self.hash.update(bytes);
            Ok(bytes.len())
        }
        fn flush(&mut self) -> io::Result<()> {
            Ok(())
        }
    }
    let mut writer = BoundedHash {
        hash: Sha256::new(),
        remaining: 64 * 1024,
    };
    writer.hash.update(domain);
    serde_json::to_writer(&mut writer, value).map_err(|_| invalid())?;
    crate::content_hash::format_digest(writer.hash.finalize().into())
        .0
        .parse()
        .map_err(|_| invalid())
}
