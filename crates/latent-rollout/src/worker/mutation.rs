use super::{size, Job, MutationInput, Shared};
use crate::{audit, model::maximum_ack, MutationPreview, MutationResult, Result};
use latent_audit::AuditHandle;
use latent_control_store::DirectoryDeploymentRepository;

pub(super) async fn run(
    repository: &DirectoryDeploymentRepository,
    audit_handle: &AuditHandle,
    shared: &Shared,
    windows: &mut crate::canary::ObservationWindows,
    mut job: Job<MutationInput, MutationResult>,
) {
    job.charge.activate();
    let result = execute(repository, audit_handle, shared, windows, &mut job).await;
    job.finish(result);
}

async fn execute(
    repository: &DirectoryDeploymentRepository,
    audit_handle: &AuditHandle,
    shared: &Shared,
    windows: &mut crate::canary::ObservationWindows,
    job: &mut Job<MutationInput, MutationResult>,
) -> Result<MutationResult> {
    job.check(shared)?;
    let input = job.input.take().expect("owned rollout request");
    let has_policy = match &input.request {
        latent_control_store::rollouts::RolloutRequest::Start { spec, .. } => {
            spec.canary_policy.is_some()
        }
        latent_control_store::rollouts::RolloutRequest::Change { context, id, .. } => repository
            .get_rollout(&context.tenant, id)?
            .is_some_and(|status| status.canary_policy.is_some()),
    };
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
        observation: has_policy.then(crate::RolloutObservation::maximum),
    })?;
    commit(
        repository,
        audit_handle,
        shared,
        windows,
        job,
        prepared,
        has_policy,
    )
    .await
}

pub(crate) async fn commit<I>(
    repository: &DirectoryDeploymentRepository,
    audit_handle: &AuditHandle,
    shared: &Shared,
    windows: &mut crate::canary::ObservationWindows,
    job: &mut Job<I, MutationResult>,
    prepared: latent_control_store::rollouts::PreparedRolloutMutation,
    has_policy: bool,
) -> Result<MutationResult> {
    job.check(shared)?;
    let description = audit::attempt(prepared.preview(), prepared.replayed())?;
    let canary_decision = audit::canary::from_receipt(repository, prepared.preview())?;
    if canary_decision.is_some() {
        let mut terminal = audit::conclusion(&description, Some(prepared.preview()));
        terminal.canary_decision = canary_decision;
        audit_handle.preflight_conclusion(&description, &terminal)?;
    }
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
    let mut terminal = audit::conclusion(&description, known.map(|result| &result.receipt));
    if known.is_some() {
        terminal.canary_decision = canary_decision;
    }
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
    let observation = if !has_policy {
        None
    } else if result.durability.is_ok() {
        windows.after_mutation(repository, &result.receipt, result.replayed)
    } else {
        // A sync-uncertain commit cannot begin authoritative observation.
        windows.remove(&result.receipt.tenant, &result.receipt.rollout_id);
        Some(crate::RolloutObservation::unavailable())
    };
    Ok(MutationResult {
        receipt: result.receipt,
        replayed: result.replayed,
        durability: result.durability.map_err(crate::bounded),
        audit_ack: acknowledgement,
        observation,
    })
}
