//! Explicit audit composition for trusted release control adapters.
//!
//! Call `preview` only AFTER the complete response preflight succeeds, on the
//! bounded catalog control worker, outside lifecycle/authority fences. The
//! directory catalog itself remains usable by explicitly unaudited embeddings.
//! No method here belongs in an activation currentness or invocation path.

mod mapping;
mod verification;
pub use verification::AuditedAdmissionAuthority;

use latent_audit::{
    AuditAttempt, AuditControlAction, AuditHandle, AuditIdentities, AuditOperationAttempt,
    AuditOperationConclusion, AuditOperationResult, AuditReason,
};
use latent_core::{PlatformError, PlatformErrorCode};

use crate::{
    ArtifactRepository, ReleaseLifecycleAction, ReleaseOperationLookup, ReleaseOperationPreview,
    ReleaseOperationReceipt,
};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ReleaseAuditStatus {
    Disabled,
    Durable,
    OutcomeUnknown,
    AuditUnavailable,
}

/// Audit status is separate from the real catalog disposition. In particular,
/// `OutcomeUnknown` never changes a committed mutation into a rejection.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ReleaseAuditAck {
    pub status: ReleaseAuditStatus,
    pub attempt_sequence: Option<u64>,
}

/// One affine attempt; dropping a caller never refunds worker-owned outcome
/// capacity. Explicit host adapters use the same guard as managed RPCs.
pub struct ReleaseAuditGuard {
    audit: Option<AuditHandle>,
    action: ReleaseLifecycleAction,
    attempt: Option<AuditAttempt>,
    identity: Option<AuditOperationAttempt>,
    ack: ReleaseAuditAck,
    replay: bool,
    previewed: bool,
}

impl ReleaseAuditGuard {
    #[must_use]
    pub fn new(audit: Option<&AuditHandle>, action: ReleaseLifecycleAction) -> Self {
        Self {
            audit: audit.cloned(),
            action,
            attempt: None,
            identity: None,
            ack: ReleaseAuditAck {
                status: if audit.is_some() {
                    ReleaseAuditStatus::AuditUnavailable
                } else {
                    ReleaseAuditStatus::Disabled
                },
                attempt_sequence: None,
            },
            replay: false,
            previewed: false,
        }
    }

    /// Synchronously waits for the durable attempt on the existing bounded
    /// control worker. The audit worker never calls back into the catalog.
    pub fn preview(&mut self, preview: ReleaseOperationPreview<'_>) -> Result<(), PlatformError> {
        if self.previewed || preview.receipt.action != self.action {
            return Err(invalid());
        }
        self.previewed = true;
        let Some(audit) = &self.audit else {
            return Ok(());
        };
        crate::lifecycle::validate_audit_receipt(preview.receipt)?;
        let identity = mapping::attempt(preview.receipt, preview.replay)?;
        let accepted = audit
            .try_reserve_critical(&identity)
            .and_then(|reservation| reservation.begin().blocking_wait());
        let mut attempt = match accepted {
            Ok(value) => value,
            Err(failure)
                if self.action == ReleaseLifecycleAction::Revoke
                    && matches!(
                        failure.code,
                        PlatformErrorCode::ResourceExhausted | PlatformErrorCode::Unavailable
                    ) =>
            {
                // Emergency revocation still requires its ordinary durable
                // lifecycle transaction. This records only the audit gap.
                audit.note_unavailable();
                return Ok(());
            }
            Err(failure) => return Err(failure),
        };
        self.ack.attempt_sequence = Some(attempt.sequence());
        self.ack.status = ReleaseAuditStatus::OutcomeUnknown;
        attempt.mutation_started()?;
        self.attempt = Some(attempt);
        self.identity = Some(identity);
        self.replay = preview.replay;
        Ok(())
    }

    #[must_use]
    pub const fn acknowledgement(&self) -> ReleaseAuditAck {
        self.ack
    }

    /// Pass the actual successful result; on errors pass None so only an exact
    /// retained operation receipt may establish the final disposition.
    pub async fn finish(
        mut self,
        repository: &dyn ArtifactRepository,
        actual: Option<&ReleaseOperationReceipt>,
    ) -> ReleaseAuditAck {
        let Some(attempt) = self.attempt.take() else {
            return self.ack;
        };
        let identity = self.identity.as_ref().expect("accepted audit identity");
        let conclusion =
            if let Some(receipt) = actual.filter(|value| mapping::matches(identity, value)) {
                mapping::conclusion(receipt, self.replay).unwrap_or_else(|_| unknown())
            } else {
                lookup(repository, identity, self.replay)
                    .await
                    .unwrap_or_else(|_| unknown())
            };
        let known = conclusion.result != AuditOperationResult::Unknown;
        if attempt.finish(conclusion).wait().await.is_ok() && known {
            self.ack.status = ReleaseAuditStatus::Durable;
        }
        self.ack
    }
}

/// Called before accepting audited mutations after catalog recovery. The
/// bounded lifecycle ring cannot prove outcomes after receipt eviction. A
/// deployment without an operation receipt also recovers as explicitly unknown.
pub async fn reconcile_release_audit(
    audit: &AuditHandle,
    repository: &dyn ArtifactRepository,
) -> Result<(), PlatformError> {
    for pending in audit.pending_attempts()? {
        let conclusion = if matches!(
            pending.attempt.action,
            AuditControlAction::Publish
                | AuditControlAction::Revoke
                | AuditControlAction::Retire
                | AuditControlAction::RenewEvidence
        ) {
            lookup(repository, &pending.attempt, pending.attempt.replay).await?
        } else {
            unknown()
        };
        audit
            .reconcile(pending.sequence, conclusion)?
            .wait()
            .await?;
    }
    Ok(())
}

async fn lookup(
    repository: &dyn ArtifactRepository,
    identity: &AuditOperationAttempt,
    replay: bool,
) -> Result<AuditOperationConclusion, PlatformError> {
    let scope = mapping::lifecycle_scope(&identity.scope);
    match repository
        .get_release_operation(&scope, &identity.operation_id)
        .await?
    {
        ReleaseOperationLookup::Found(receipt) if mapping::matches(identity, &receipt) => {
            mapping::conclusion(&receipt, replay)
        }
        ReleaseOperationLookup::Uncertain => Err(PlatformError {
            code: PlatformErrorCode::Unavailable,
            message: "audit-lifecycle-outcome-uncertain".to_owned(),
            retryable: false,
            details: Vec::new(),
        }),
        ReleaseOperationLookup::Found(_) | ReleaseOperationLookup::Unknown => Ok(unknown()),
    }
}

fn unknown() -> AuditOperationConclusion {
    AuditOperationConclusion {
        result: AuditOperationResult::Unknown,
        reason: AuditReason::ReceiptUnavailable,
        receipt_digest: None,
        identities: AuditIdentities::default(),
        replay: false,
        occurred_at_unix_millis: mapping::now(),
    }
}

fn invalid() -> PlatformError {
    PlatformError {
        code: PlatformErrorCode::InvalidArgument,
        message: "audit-release-preview-invalid".to_owned(),
        retryable: false,
        details: Vec::new(),
    }
}
