use crate::{CanaryEvaluationReport, Result};
use latent_audit::{AuditCanaryDecision, AuditCanaryReason, AuditCanaryVerdict};
use latent_control_store::{
    rollouts::{RolloutCanaryPolicy, RolloutOperationReceipt},
    DirectoryDeploymentRepository,
};
use latent_telemetry::{
    CanaryAssessment, CanaryDecisionReason, CanaryVerdict, CANARY_LATENCY_UPPER_MICROS,
};

pub(crate) fn from_report(
    report: &CanaryEvaluationReport,
    policy: RolloutCanaryPolicy,
) -> Option<AuditCanaryDecision> {
    report
        .assessment
        .map(|assessment| summary(assessment, policy))
}
pub(crate) fn from_receipt(
    repository: &DirectoryDeploymentRepository,
    receipt: &RolloutOperationReceipt,
) -> Result<Option<AuditCanaryDecision>> {
    let Some(decision) = receipt.canary_decision.as_ref() else {
        return Ok(None);
    };
    let policy = repository
        .get_rollout(&receipt.tenant, &receipt.rollout_id)?
        .and_then(|status| status.canary_policy)
        .ok_or_else(|| crate::invalid("rollout-canary-policy-unavailable"))?;
    if policy.digest()? != decision.policy_digest
        || policy.observation_millis != decision.observed_millis
    {
        return Err(crate::invalid("rollout-canary-policy-mismatch"));
    }
    let candidate = decision.candidate;
    let boundary = CANARY_LATENCY_UPPER_MICROS
        .iter()
        .position(|value| *value == policy.latency_threshold_micros)
        .ok_or_else(|| crate::invalid("rollout-canary-policy-mismatch"))?;
    let failures = candidate
        .selected
        .checked_sub(candidate.success)
        .ok_or_else(|| crate::invalid("rollout-canary-counters"))?;
    let slow = candidate.latency_buckets[boundary + 1..]
        .iter()
        .copied()
        .try_fold(0u64, u64::checked_add)
        .ok_or_else(|| crate::invalid("rollout-canary-counters"))?;
    Ok(Some(summary(
        CanaryAssessment {
            verdict: CanaryVerdict::Healthy,
            reason: CanaryDecisionReason::Healthy,
            selected: candidate.selected,
            admitted_terminal: candidate.admitted_terminal,
            successes: candidate.success,
            failures,
            slow,
        },
        policy,
    )))
}
fn summary(assessment: CanaryAssessment, policy: RolloutCanaryPolicy) -> AuditCanaryDecision {
    AuditCanaryDecision {
        verdict: verdict(assessment.verdict),
        reason: reason(assessment.reason),
        observation_millis: policy.observation_millis,
        minimum_candidate_samples: policy.minimum_candidate_samples,
        maximum_failure_basis_points: policy.maximum_failure_basis_points,
        latency_threshold_micros: policy.latency_threshold_micros,
        maximum_slow_basis_points: policy.maximum_slow_basis_points,
        selected: assessment.selected,
        admitted_terminal: assessment.admitted_terminal,
        successes: assessment.successes,
        failures: assessment.failures,
        slow: assessment.slow,
    }
}
fn verdict(value: CanaryVerdict) -> AuditCanaryVerdict {
    match value {
        CanaryVerdict::Collecting => AuditCanaryVerdict::Collecting,
        CanaryVerdict::Draining => AuditCanaryVerdict::Draining,
        CanaryVerdict::NoData => AuditCanaryVerdict::NoData,
        CanaryVerdict::Insufficient => AuditCanaryVerdict::Insufficient,
        CanaryVerdict::Incomplete => AuditCanaryVerdict::Incomplete,
        CanaryVerdict::Failed => AuditCanaryVerdict::Failed,
        CanaryVerdict::Healthy => AuditCanaryVerdict::Healthy,
    }
}
fn reason(value: CanaryDecisionReason) -> AuditCanaryReason {
    match value {
        CanaryDecisionReason::WindowOpen => AuditCanaryReason::WindowOpen,
        CanaryDecisionReason::WindowDraining => AuditCanaryReason::WindowDraining,
        CanaryDecisionReason::NoCandidateSamples => AuditCanaryReason::NoCandidateSamples,
        CanaryDecisionReason::MinimumCandidateSamples => AuditCanaryReason::MinimumCandidateSamples,
        CanaryDecisionReason::CaptureIncomplete => AuditCanaryReason::CaptureIncomplete,
        CanaryDecisionReason::WindowClosedEarly => AuditCanaryReason::WindowClosedEarly,
        CanaryDecisionReason::NoAdmittedCandidate => AuditCanaryReason::NoAdmittedCandidate,
        CanaryDecisionReason::NoSuccessfulCandidate => AuditCanaryReason::NoSuccessfulCandidate,
        CanaryDecisionReason::FailureRateExceeded => AuditCanaryReason::FailureRateExceeded,
        CanaryDecisionReason::SlowRateExceeded => AuditCanaryReason::SlowRateExceeded,
        CanaryDecisionReason::MissingCandidate => AuditCanaryReason::MissingCandidate,
        CanaryDecisionReason::Healthy => AuditCanaryReason::Healthy,
    }
}
