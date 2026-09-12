use super::{size, Job, MutationInput, Shared};
use crate::{audit, model::maximum_ack, MutationPreview, MutationResult, Result};
use latent_audit::AuditHandle;
use latent_control_store::DirectoryDeploymentRepository;

pub(super) async fn run(
    repository: &DirectoryDeploymentRepository,
    audit_handle: &AuditHandle,
    shared: &Shared,
    mut job: Job<MutationInput, MutationResult>,
) {
    job.charge.activate();
    let result = execute(repository, audit_handle, shared, &mut job).await;
    job.finish(result);
}

async fn execute(
    repository: &DirectoryDeploymentRepository,
    audit_handle: &AuditHandle,
    shared: &Shared,
    job: &mut Job<MutationInput, MutationResult>,
) -> Result<MutationResult> {
    job.check(shared)?;
    let input = job.input.take().expect("owned rollout request");
    // Preparation has no publication side effects. Dropping it releases only
    // its own store reservation; any independently running source work owns its
    // existing source permits until actual completion.
    let prepared = tokio::select! {
        value = repository.prepare_rollout(input.request) => value?,
        () = job.control.cancelled() => return Err(crate::cancelled()),
        () = shared.shutdown.notified() => return Err(crate::closed()),
        () = tokio::time::sleep_until(job.expires.into()) => return Err(crate::deadline()),
    };
    job.check(shared)?;
    // Reserve room for the receipt plus acknowledgement/durability metadata
    // before durable audit acceptance. Adapter preflight adds its exact wire
    // framing and may only reject.
    let receipt_budget = job
        .maximum
        .checked_sub(256)
        .ok_or_else(|| crate::capacity("rollout-response-budget"))?;
    size::check(prepared.preview(), receipt_budget)?;
    (input.preflight)(MutationPreview {
        receipt: prepared.preview(),
        replayed: prepared.replayed(),
        audit_ack: maximum_ack(),
    })?;
    job.check(shared)?;
    let description = audit::attempt(prepared.preview(), prepared.replayed())?;
    let reservation = audit_handle.try_reserve_critical(&description)?;
    job.check(shared)?;
    // The worker retains all accepted ownership while the audit owner performs
    // real durable I/O, even if the waiting client disappears or times out.
    let mut attempt = reservation.begin().wait().await?;
    let sequence = attempt.sequence();
    job.control.set_ack(audit::ack(sequence, false));
    job.check(shared)?;
    attempt.mutation_started()?;
    // No cancellation/await between this marker and the synchronous commit.
    let result = repository.commit_rollout(prepared);
    let known = result.as_ref().ok().filter(|result| {
        result.durability.is_ok()
            && result.replayed == description.replay
            && audit::matches(&description, &result.receipt)
    });
    let terminal = audit::conclusion(&description, known.map(|result| &result.receipt));
    let durable_known = known.is_some();
    let persisted = attempt.finish(terminal).wait().await.is_ok();
    let acknowledgement = audit::ack(sequence, durable_known && persisted);
    job.control.set_ack(acknowledgement);
    let result = result?;
    if !audit::matches(&description, &result.receipt) || result.replayed != description.replay {
        return Err(crate::invalid("rollout-receipt-mismatch"));
    }
    // An accepted commit cannot be relabeled as an uncommitted cancellation.
    // The ticket's deadline still bounds client delivery, with Unknown metadata
    // available until the matching terminal audit record is acknowledged.
    if durable_known && !result.replayed {
        audit::observe(audit_handle, &result.receipt);
    }
    Ok(MutationResult {
        receipt: result.receipt,
        replayed: result.replayed,
        durability: result.durability.map_err(crate::bounded),
        audit_ack: acknowledgement,
    })
}
