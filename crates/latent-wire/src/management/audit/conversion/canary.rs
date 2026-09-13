use crate::management::proto;
use latent_audit::{AuditCanaryDecision, AuditCanaryReason, AuditCanaryVerdict};

pub(super) fn decision(value: AuditCanaryDecision) -> proto::AuditCanaryDecision {
    proto::AuditCanaryDecision {
        verdict: verdict(value.verdict),
        reason: reason(value.reason),
        observation_millis: value.observation_millis,
        minimum_candidate_samples: value.minimum_candidate_samples,
        maximum_failure_basis_points: u32::from(value.maximum_failure_basis_points),
        latency_threshold_micros: value.latency_threshold_micros,
        maximum_slow_basis_points: u32::from(value.maximum_slow_basis_points),
        selected: value.selected,
        admitted_terminal: value.admitted_terminal,
        successes: value.successes,
        failures: value.failures,
        slow: value.slow,
    }
}

fn verdict(value: AuditCanaryVerdict) -> i32 {
    use proto::AuditCanaryVerdict as Wire;
    (match value {
        AuditCanaryVerdict::Collecting => Wire::Collecting,
        AuditCanaryVerdict::Draining => Wire::Draining,
        AuditCanaryVerdict::NoData => Wire::NoData,
        AuditCanaryVerdict::Insufficient => Wire::Insufficient,
        AuditCanaryVerdict::Incomplete => Wire::Incomplete,
        AuditCanaryVerdict::Failed => Wire::Failed,
        AuditCanaryVerdict::Healthy => Wire::Healthy,
    }) as i32
}

fn reason(value: AuditCanaryReason) -> i32 {
    use proto::AuditCanaryReason as Wire;
    (match value {
        AuditCanaryReason::WindowOpen => Wire::WindowOpen,
        AuditCanaryReason::WindowDraining => Wire::WindowDraining,
        AuditCanaryReason::NoCandidateSamples => Wire::NoCandidateSamples,
        AuditCanaryReason::MinimumCandidateSamples => Wire::MinimumCandidateSamples,
        AuditCanaryReason::CaptureIncomplete => Wire::CaptureIncomplete,
        AuditCanaryReason::WindowClosedEarly => Wire::WindowClosedEarly,
        AuditCanaryReason::NoAdmittedCandidate => Wire::NoAdmittedCandidate,
        AuditCanaryReason::NoSuccessfulCandidate => Wire::NoSuccessfulCandidate,
        AuditCanaryReason::FailureRateExceeded => Wire::FailureRateExceeded,
        AuditCanaryReason::SlowRateExceeded => Wire::SlowRateExceeded,
        AuditCanaryReason::MissingCandidate => Wire::MissingCandidate,
        AuditCanaryReason::Healthy => Wire::Healthy,
    }) as i32
}
