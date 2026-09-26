use super::{mapping, unknown, ReleaseAuditAck, ReleaseAuditGuard};
use crate::{
    web::{WebMutationResult, WebOperationReceipt},
    ArtifactRepository, ReleaseLifecycleAction,
};
use latent_audit::{
    AuditActorIdentity, AuditHandle, AuditIdentities, AuditOperationAttempt,
    AuditOperationConclusion, AuditOperationResult,
};
use latent_core::PlatformError;

pub struct WebAuditGuard(ReleaseAuditGuard);

impl WebAuditGuard {
    #[must_use]
    pub fn new(audit: Option<&AuditHandle>, action: ReleaseLifecycleAction) -> Self {
        Self(ReleaseAuditGuard::new(audit, action))
    }

    pub fn preview(&mut self, preview: &WebMutationResult) -> Result<(), PlatformError> {
        if self.0.previewed || preview.receipt.action != self.0.action {
            return Err(super::invalid());
        }
        self.0.previewed = true;
        self.0.begin(attempt(&preview.receipt, preview.replay)?)
    }

    pub async fn finish(self, repository: &dyn ArtifactRepository) -> ReleaseAuditAck {
        self.0.finish(repository, None).await
    }
}

fn attempt(
    value: &WebOperationReceipt,
    replay: bool,
) -> Result<AuditOperationAttempt, PlatformError> {
    value.validate()?;
    let bytes = serde_json::to_vec(value).map_err(|_| super::invalid())?;
    if bytes.len() > 4096 {
        return Err(super::invalid());
    }
    Ok(AuditOperationAttempt {
        expected_state_version: None,
        expected_rollback_target_generation: None,
        scope: mapping::scope(&value.publication.scope),
        actor: AuditActorIdentity {
            kind: mapping::actor(value.actor.kind),
            subject: value.actor.subject.clone(),
        },
        operation_id: value.operation_id.clone(),
        request_digest: value.request_digest.clone(),
        action: mapping::action(value.action),
        identities: AuditIdentities {
            publication: Some(value.publication.id.clone()),
            lifecycle_generation: Some(value.resulting_generation),
            ..AuditIdentities::default()
        },
        expected_generation: Some(value.expected_generation),
        expected_deployment_generation: None,
        expected_rollout_revision: None,
        replay,
        preview_receipt_digest: Some(crate::package::artifact_blob_digest(&bytes)),
        occurred_at_unix_millis: mapping::now(),
    })
}

pub(super) async fn lookup(
    repository: &dyn ArtifactRepository,
    identity: &AuditOperationAttempt,
    replay: bool,
) -> Result<AuditOperationConclusion, PlatformError> {
    let Some(value) = repository
        .get_web_operation(
            &mapping::lifecycle_scope(&identity.scope),
            &identity.operation_id,
        )
        .await?
    else {
        return Ok(unknown());
    };
    let expected = attempt(&value, replay)?;
    if expected.scope != identity.scope
        || expected.actor != identity.actor
        || expected.operation_id != identity.operation_id
        || expected.request_digest != identity.request_digest
        || expected.action != identity.action
        || expected.identities != identity.identities
        || expected.expected_generation != identity.expected_generation
        || expected.preview_receipt_digest != identity.preview_receipt_digest
    {
        return Ok(unknown());
    }
    Ok(AuditOperationConclusion {
        canary_decision: None,
        result: AuditOperationResult::Committed,
        reason: mapping::reason(value.reason),
        receipt_digest: expected.preview_receipt_digest,
        identities: expected.identities,
        replay,
        occurred_at_unix_millis: mapping::now(),
    })
}
