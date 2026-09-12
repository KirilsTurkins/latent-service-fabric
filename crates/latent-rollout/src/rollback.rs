//! Operator rollback uses no telemetry proof and cannot revive denied content.
mod rejection;
use crate::{
    canary::ObservationWindows,
    coordinator::Shared,
    model::maximum_ack,
    worker::{mutation, size, Job},
    MutationResult, Result, RolloutObservation,
};
use latent_artifacts::ReleaseAuditAck;
use latent_audit::AuditHandle;
use latent_control_store::{
    rollouts::{RolloutCommand, RolloutOperationReceipt, RolloutRequest},
    DirectoryDeploymentRepository,
};
use latent_core::PlatformError;

pub struct RollbackPreview<'a> {
    pub receipt: Option<&'a RolloutOperationReceipt>,
    pub failure: Option<&'a PlatformError>,
    pub replayed: bool,
    pub audit_ack: ReleaseAuditAck,
    pub observation: Option<RolloutObservation>,
}
pub(crate) struct RollbackInput {
    pub request: RolloutRequest,
    pub preflight: Box<dyn for<'a> FnOnce(RollbackPreview<'a>) -> Result<()> + Send>,
}
pub(crate) fn is_rollback(request: &RolloutRequest) -> bool {
    matches!(
        request,
        RolloutRequest::Change {
            command: RolloutCommand::Rollback { .. },
            ..
        }
    )
}
pub(crate) async fn run(
    repository: &DirectoryDeploymentRepository,
    audit: &AuditHandle,
    shared: &Shared,
    windows: &mut ObservationWindows,
    mut job: Job<RollbackInput, MutationResult>,
) {
    job.charge.activate();
    let result = execute(repository, audit, shared, windows, &mut job).await;
    job.finish(result);
}
async fn execute(
    repository: &DirectoryDeploymentRepository,
    audit: &AuditHandle,
    shared: &Shared,
    windows: &mut ObservationWindows,
    job: &mut Job<RollbackInput, MutationResult>,
) -> Result<MutationResult> {
    job.check(shared)?;
    let input = job.input.take().expect("owned rollback request");
    let request_digest = input.request.request_digest(repository.rollout_limits())?;
    let RolloutRequest::Change {
        context,
        id,
        command: RolloutCommand::Rollback { target_generation },
    } = &input.request
    else {
        return Err(crate::invalid("rollout-rollback-command-required"));
    };
    let (context, id, target_generation) = (context.clone(), id.clone(), *target_generation);
    let has_policy = repository
        .get_rollout(&context.tenant, &id)?
        .is_some_and(|status| status.canary_policy.is_some());
    let prepared = tokio::select! {
        value=repository.prepare_rollout(input.request)=>value,
        ()=job.control.cancelled()=>return Err(crate::cancelled()),
        ()=shared.shutdown.notified()=>return Err(crate::closed()),
        ()=tokio::time::sleep_until(job.expires.into())=>return Err(crate::deadline()),
    };
    job.check(shared)?;
    let prepared = match prepared {
        Ok(prepared) => prepared,
        Err(failure) => {
            return rejection::run(
                audit,
                shared,
                job,
                input.preflight,
                &context,
                &id,
                target_generation,
                request_digest,
                failure,
            )
            .await
        }
    };
    size::check(
        prepared.preview(),
        job.maximum
            .checked_sub(256)
            .ok_or_else(|| crate::capacity("rollout-response-budget"))?,
    )?;
    (input.preflight)(RollbackPreview {
        receipt: Some(prepared.preview()),
        failure: None,
        replayed: prepared.replayed(),
        audit_ack: maximum_ack(),
        observation: has_policy.then(RolloutObservation::maximum),
    })?;
    mutation::commit(
        repository, audit, shared, windows, job, prepared, has_policy,
    )
    .await
}
