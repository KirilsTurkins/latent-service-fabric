//! One shared terminal path for preflighted semantic control rejections.
use super::Job;
use crate::{audit, coordinator::Shared, MutationResult, Result};
use latent_audit::{AuditHandle, AuditOperationAttempt, AuditOperationConclusion};
use latent_core::PlatformError;

pub(crate) async fn finish<I>(
    audit_handle: &AuditHandle,
    shared: &Shared,
    job: &mut Job<I, MutationResult>,
    attempt: AuditOperationAttempt,
    terminal: AuditOperationConclusion,
    failure: PlatformError,
) -> Result<MutationResult> {
    audit_handle.preflight_conclusion(&attempt, &terminal)?;
    job.check(shared)?;
    let reservation = audit_handle.try_reserve_critical(&attempt)?;
    job.check(shared)?;
    let attempt = reservation.begin().wait().await?;
    let sequence = attempt.sequence();
    job.control.set_ack(audit::ack(sequence, false));
    // The known rejection stays true if a client cancels during accepted audit
    // I/O. Keep the real job and response reservation through terminal completion.
    let persisted = attempt.finish(terminal).wait().await.is_ok();
    job.control.set_ack(audit::ack(sequence, persisted));
    Err(failure)
}
