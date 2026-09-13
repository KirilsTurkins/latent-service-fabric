use crate::management::{proto, ManagementLimits, RequestBudget};
use latent_control_store::rollouts::{RolloutCanaryCounters, RolloutCanaryDecision};
use latent_rollout::CanaryEvaluationReport;
use latent_telemetry::{CanaryAssessment, CanaryDecisionReason, CanaryVerdict};
use tonic::Status;

pub(super) fn charge(
    value: &CanaryEvaluationReport,
    limits: &ManagementLimits,
) -> Result<(), Status> {
    let mut budget = RequestBudget::for_response::<proto::EvaluateRolloutResponse>(limits)?;
    budget.allocation::<proto::CanaryEvaluationReport>(1)?;
    budget.string(&value.rollout_id.0, 128)?;
    budget.string(&value.candidate_revision.0, 256)?;
    budget.allocation::<u8>(71)?;
    budget.allocation::<proto::RolloutObservation>(1)?;
    budget.allocation::<proto::CanaryAssessment>(usize::from(value.assessment.is_some()))?;
    budget.sequence(&value.revisions, 2)?;
    budget.allocation::<proto::CanaryRevisionReport>(value.revisions.len())?;
    for row in &value.revisions {
        budget.string(&row.binding.revision.0, 256)?;
        budget.string(&row.binding.component.0, 71)?;
        budget.allocation::<u8>(usize::from(row.binding.package.is_some()) * 71)?;
        budget.allocation::<proto::RolloutCanaryCounters>(1)?;
        budget.allocation::<u64>(9)?;
    }
    Ok(())
}

pub(in crate::management::rollouts) fn charge_decision(
    budget: &mut RequestBudget,
) -> Result<(), Status> {
    budget.allocation::<proto::RolloutCanaryDecision>(1)?;
    budget.allocation::<u8>(3 * 71)?;
    budget.allocation::<proto::RolloutCanaryCounters>(2)?;
    budget.allocation::<u64>(18)
}

pub(in crate::management::rollouts) fn decision(
    value: RolloutCanaryDecision,
) -> proto::RolloutCanaryDecision {
    proto::RolloutCanaryDecision {
        format_version: value.format_version,
        policy_digest: value.policy_digest.into_string(),
        control_digest: value.control_digest.into_string(),
        evidence_digest: value.evidence_digest.into_string(),
        window_epoch: value.window_epoch,
        observed_millis: value.observed_millis,
        candidate: Some(counters(value.candidate)),
        baseline: Some(counters(value.baseline)),
    }
}

fn counters(value: RolloutCanaryCounters) -> proto::RolloutCanaryCounters {
    proto::RolloutCanaryCounters {
        selected: value.selected,
        admitted: value.admitted,
        admitted_terminal: value.admitted_terminal,
        success: value.success,
        domain_error: value.domain_error,
        platform_error: value.platform_error,
        deadline_exceeded: value.deadline_exceeded,
        cancelled: value.cancelled,
        latency_buckets: value.latency_buckets.to_vec(),
    }
}

pub(super) fn wire(value: CanaryEvaluationReport) -> proto::CanaryEvaluationReport {
    proto::CanaryEvaluationReport {
        rollout_id: value.rollout_id.0,
        revision: value.revision,
        step: value.step,
        route_generation: value.route_generation.0,
        policy_digest: value.policy_digest.into_string(),
        window_epoch: value.window_epoch,
        candidate_revision: value.candidate_revision.0,
        duration_millis: value.duration_millis,
        observation: Some(super::observation(value.observation)),
        assessment: value.assessment.map(assessment),
        starts: value.starts,
        selected: value.selected,
        admitted: value.admitted,
        terminal: value.terminal,
        live: value.live,
        unattributed: value.unattributed,
        abandoned: value.abandoned,
        revisions: value
            .revisions
            .into_iter()
            .map(|row| proto::CanaryRevisionReport {
                revision: row.binding.revision.0,
                component_digest: row.binding.component.0,
                package_digest: row
                    .binding
                    .package
                    .map(latent_core::PackageDigest::into_string),
                counters: Some(proto::RolloutCanaryCounters {
                    selected: row.outcomes.selected,
                    admitted: row.outcomes.admitted,
                    admitted_terminal: row.outcomes.admitted_terminal,
                    success: row.outcomes.outcomes.success,
                    domain_error: row.outcomes.outcomes.domain_error,
                    platform_error: row.outcomes.outcomes.platform_error,
                    deadline_exceeded: row.outcomes.outcomes.deadline_exceeded,
                    cancelled: row.outcomes.outcomes.cancelled,
                    latency_buckets: row.outcomes.latency_buckets.to_vec(),
                }),
            })
            .collect(),
    }
}

fn assessment(value: CanaryAssessment) -> proto::CanaryAssessment {
    use proto::CanaryDecisionReason as Reason;
    use proto::CanaryVerdict as Verdict;
    proto::CanaryAssessment {
        verdict: match value.verdict {
            CanaryVerdict::Collecting => Verdict::Collecting,
            CanaryVerdict::Draining => Verdict::Draining,
            CanaryVerdict::NoData => Verdict::NoData,
            CanaryVerdict::Insufficient => Verdict::Insufficient,
            CanaryVerdict::Incomplete => Verdict::Incomplete,
            CanaryVerdict::Failed => Verdict::Failed,
            CanaryVerdict::Healthy => Verdict::Healthy,
        } as i32,
        reason: match value.reason {
            CanaryDecisionReason::WindowOpen => Reason::WindowOpen,
            CanaryDecisionReason::WindowDraining => Reason::WindowDraining,
            CanaryDecisionReason::NoCandidateSamples => Reason::NoCandidateSamples,
            CanaryDecisionReason::MinimumCandidateSamples => Reason::MinimumCandidateSamples,
            CanaryDecisionReason::CaptureIncomplete => Reason::CaptureIncomplete,
            CanaryDecisionReason::WindowClosedEarly => Reason::WindowClosedEarly,
            CanaryDecisionReason::NoAdmittedCandidate => Reason::NoAdmittedCandidate,
            CanaryDecisionReason::NoSuccessfulCandidate => Reason::NoSuccessfulCandidate,
            CanaryDecisionReason::FailureRateExceeded => Reason::FailureRateExceeded,
            CanaryDecisionReason::SlowRateExceeded => Reason::SlowRateExceeded,
            CanaryDecisionReason::MissingCandidate => Reason::MissingCandidate,
            CanaryDecisionReason::Healthy => Reason::Healthy,
        } as i32,
        selected: value.selected,
        admitted_terminal: value.admitted_terminal,
        successes: value.successes,
        failures: value.failures,
        slow: value.slow,
    }
}
