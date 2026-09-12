use super::{windows::Observed, ObservationWindows};
use crate::{
    coordinator::Shared, worker::Job, CanaryEvaluationReport, CanaryEvaluationRequest,
    CanaryRevisionReport, Result, RolloutObservation, RolloutObservationState,
};
use latent_control_store::{rollouts::RolloutCanaryCohort, DirectoryDeploymentRepository};

pub(crate) fn run(
    repository: &DirectoryDeploymentRepository,
    shared: &Shared,
    windows: &mut ObservationWindows,
    mut job: Job<CanaryEvaluationRequest, CanaryEvaluationReport>,
) {
    job.charge.activate();
    let result = (|| {
        job.check(shared)?;
        let request = job.input.take().expect("owned evaluation");
        let cohort = repository.rollout_canary_cohort(
            &request.tenant,
            &request.id,
            request.expected_revision,
        )?;
        let report = if repository.canary_hub().is_none() {
            empty(&cohort)?
        } else {
            report(windows.ensure(repository, cohort)?)?
        };
        bounded_report(&report, job.maximum)?;
        job.check(shared)?;
        Ok(report)
    })();
    job.finish(result);
}
pub(super) fn empty(cohort: &RolloutCanaryCohort) -> Result<CanaryEvaluationReport> {
    let spec = cohort.window_spec();
    Ok(CanaryEvaluationReport {
        rollout_id: latent_control_store::rollouts::RolloutId(spec.identity.rollout_id.clone()),
        revision: cohort.revision(),
        step: u32::try_from(spec.identity.step)
            .map_err(|_| crate::invalid("rollout-canary-step"))?,
        route_generation: spec.identity.generation,
        policy_digest: cohort.policy().digest()?,
        window_epoch: None,
        candidate_revision: cohort.candidate_revision().clone(),
        duration_millis: cohort.policy().observation_millis,
        observation: RolloutObservation::unavailable(),
        assessment: None,
        starts: 0,
        selected: 0,
        admitted: 0,
        terminal: 0,
        live: 0,
        unattributed: 0,
        abandoned: 0,
        revisions: Vec::new(),
    })
}
pub(super) fn report(observed: &Observed) -> Result<CanaryEvaluationReport> {
    let snapshot = observed.window.snapshot(1)?;
    let mut report = empty(&observed.cohort)?;
    report.window_epoch = Some(snapshot.epoch());
    report.observation = RolloutObservation {
        state: if snapshot.elapsed() < snapshot.duration() {
            RolloutObservationState::Collecting
        } else {
            RolloutObservationState::AwaitingEvaluation
        },
        window_epoch: report.window_epoch,
    };
    report.assessment = Some(snapshot.assess_candidate(
        observed.cohort.candidate_revision(),
        observed.cohort.policy().thresholds(),
    )?);
    report.starts = snapshot.starts() as u64;
    report.selected = snapshot.selected();
    report.admitted = snapshot.admitted();
    report.terminal = snapshot.terminal();
    report.live = snapshot.live() as u64;
    report.unattributed = snapshot.unattributed();
    report.abandoned = snapshot.abandoned();
    report.revisions = snapshot
        .revisions()
        .iter()
        .cloned()
        .zip(snapshot.revision_outcomes().iter().copied())
        .map(|(binding, outcomes)| CanaryRevisionReport { binding, outcomes })
        .collect();
    Ok(report)
}
pub(super) fn bounded_report(report: &CanaryEvaluationReport, maximum: usize) -> Result<()> {
    // Fixed scalar/counter envelope plus worst-case JSON escaping of every
    // bounded string. The wire adapter additionally checks its exact encoding.
    let mut bytes = 2048
        + 6 * (report.rollout_id.0.len()
            + report.candidate_revision.0.len()
            + report.policy_digest.as_str().len());
    for entry in &report.revisions {
        bytes += 1024
            + 6 * (entry.binding.revision.0.len()
                + entry.binding.component.0.len()
                + entry
                    .binding
                    .package
                    .as_ref()
                    .map_or(0, |value| value.as_str().len()));
    }
    if bytes > maximum {
        return Err(crate::capacity("rollout-response-budget"));
    }
    Ok(())
}
