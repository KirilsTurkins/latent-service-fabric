use super::{
    denied, error, now, AuditHandle, AuditOperationConclusion, AuditOperationResult,
    AuditProviderOutcome, AuditReason, Instant, PlatformError, PlatformErrorCode,
};

/// Startup reconciles only recovered capability attempts. A previous process
/// may have reached its provider, so absence of a terminal record means Unknown.
/// No provider is opened or retried and no policy grant is reconstructed.
pub async fn reconcile_capability_audit(
    audit: &AuditHandle,
    deadline: Instant,
) -> Result<(), PlatformError> {
    for pending in audit.pending_attempts()? {
        if pending.attempt.action != latent_audit::AuditControlAction::CapabilityCall {
            continue;
        }
        if Instant::now() >= deadline {
            return Err(error(
                PlatformErrorCode::DeadlineExceeded,
                "capability-audit-recovery-deadline",
            ));
        }
        let mut identities = pending.attempt.identities;
        identities
            .capability
            .as_mut()
            .ok_or_else(denied)?
            .provider_outcome = Some(AuditProviderOutcome::Unknown);
        let conclusion = AuditOperationConclusion {
            canary_decision: None,
            result: AuditOperationResult::Unknown,
            reason: AuditReason::MutationUncertain,
            receipt_digest: None,
            identities,
            replay: false,
            occurred_at_unix_millis: now(),
        };
        let ticket = audit.reconcile(pending.sequence, conclusion)?;
        tokio::time::timeout_at(deadline.into(), ticket.wait())
            .await
            .map_err(|_| {
                error(
                    PlatformErrorCode::DeadlineExceeded,
                    "capability-audit-recovery-deadline",
                )
            })??;
    }
    Ok(())
}
