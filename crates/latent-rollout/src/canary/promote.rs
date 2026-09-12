mod rejection;
use super::{evaluate, ObservationWindows};
use crate::{
    coordinator::Shared,
    model::maximum_ack,
    worker::{mutation, size, Job},
    CanaryEvaluationReport, MutationResult, PromotionPreview, Result, RolloutObservation,
};
use latent_audit::AuditHandle;
use latent_control_store::{rollouts::RolloutRequest, DirectoryDeploymentRepository};

pub(crate) struct PromotionInput {
    pub request: RolloutRequest,
    pub preflight: Box<dyn for<'a> FnOnce(PromotionPreview<'a>) -> Result<()> + Send>,
}
pub(crate) async fn run(
    repository: &DirectoryDeploymentRepository,
    audit: &AuditHandle,
    shared: &Shared,
    windows: &mut ObservationWindows,
    mut job: Job<PromotionInput, MutationResult>,
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
    job: &mut Job<PromotionInput, MutationResult>,
) -> Result<MutationResult> {
    job.check(shared)?;
    let input = job.input.take().expect("owned promotion request");
    let request_digest = input.request.request_digest(repository.rollout_limits())?;
    let (context, id) = match &input.request {
        RolloutRequest::Change { context, id, .. } => (context.clone(), id.clone()),
        RolloutRequest::Start { .. } => {
            return Err(crate::invalid("rollout-promotion-command-required"))
        }
    };
    let mut decision: Option<CanaryEvaluationReport> = None;
    let mut audit_decision = None;
    // Failure to obtain current live evidence does not defeat exact retained
    // replay. Only the store may decide whether None is sufficient for replay.
    let proof = repository
        .rollout_canary_cohort(&context.tenant, &id, context.operation.expected_revision)
        .and_then(|cohort| windows.ensure(repository, cohort))
        .and_then(|observed| {
            decision = evaluate::report(observed).ok();
            audit_decision = decision.as_ref().and_then(|report| {
                crate::audit::canary::from_report(report, *observed.cohort.policy())
            });
            observed.window.try_seal()
        })
        .ok();
    let prepared = tokio::select! {
        value=repository.prepare_canary_promotion(input.request,proof)=>value,
        ()=job.control.cancelled()=>return Err(crate::cancelled()),
        ()=shared.shutdown.notified()=>return Err(crate::closed()),
        ()=tokio::time::sleep_until(job.expires.into())=>return Err(crate::deadline()),
    };
    job.check(shared)?;
    if let Some(report) = &decision {
        evaluate::bounded_report(report, job.maximum)?;
    }
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
                request_digest,
                decision.as_ref(),
                audit_decision,
                failure,
            )
            .await;
        }
    };
    size::check(
        prepared.preview(),
        job.maximum
            .checked_sub(256)
            .ok_or_else(|| crate::capacity("rollout-response-budget"))?,
    )?;
    (input.preflight)(PromotionPreview {
        receipt: Some(prepared.preview()),
        decision: decision.as_ref(),
        failure: None,
        replayed: prepared.replayed(),
        audit_ack: maximum_ack(),
        observation: Some(RolloutObservation::maximum()),
    })?;
    mutation::commit(repository, audit, shared, windows, job, prepared, true).await
}
