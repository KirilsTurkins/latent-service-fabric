//! Exact integer criteria over bounded host observations. Reports are diagnostics;
//! only a sealed window from the configured owner can enter a catalog promotion.
use latent_core::{PlatformError, PlatformErrorCode, RevisionId};

use super::{
    error, CanaryCoverage, CanaryRevisionBinding, CanaryRevisionSnapshot,
    CANARY_LATENCY_UPPER_MICROS,
};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct CanaryThresholds {
    pub minimum_candidate_samples: u64,
    pub maximum_failure_basis_points: u16,
    pub latency_threshold_micros: u64,
    pub maximum_slow_basis_points: u16,
}

impl CanaryThresholds {
    pub fn validate(self) -> Result<Self, PlatformError> {
        if self.minimum_candidate_samples == 0
            || self.minimum_candidate_samples > 1_000_000
            || self.maximum_failure_basis_points >= 10_000
            || self.maximum_slow_basis_points > 10_000
            || !CANARY_LATENCY_UPPER_MICROS.contains(&self.latency_threshold_micros)
        {
            return Err(error(
                PlatformErrorCode::InvalidArgument,
                "invalid-canary-thresholds",
            ));
        }
        Ok(self)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CanaryVerdict {
    Collecting,
    Draining,
    NoData,
    Insufficient,
    Incomplete,
    Failed,
    Healthy,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CanaryDecisionReason {
    WindowOpen,
    WindowDraining,
    NoCandidateSamples,
    MinimumCandidateSamples,
    CaptureIncomplete,
    WindowClosedEarly,
    NoAdmittedCandidate,
    NoSuccessfulCandidate,
    FailureRateExceeded,
    SlowRateExceeded,
    MissingCandidate,
    Healthy,
}

impl CanaryDecisionReason {
    #[must_use]
    pub const fn metric_label(self) -> &'static str {
        match self {
            Self::WindowOpen => "window-open",
            Self::WindowDraining => "window-draining",
            Self::NoCandidateSamples => "no-candidate-samples",
            Self::MinimumCandidateSamples => "minimum-candidate-samples",
            Self::CaptureIncomplete => "capture-incomplete",
            Self::WindowClosedEarly => "window-closed-early",
            Self::NoAdmittedCandidate => "no-admitted-candidate",
            Self::NoSuccessfulCandidate => "no-successful-candidate",
            Self::FailureRateExceeded => "failure-rate-exceeded",
            Self::SlowRateExceeded => "slow-rate-exceeded",
            Self::MissingCandidate => "missing-candidate",
            Self::Healthy => "healthy",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct CanaryAssessment {
    pub verdict: CanaryVerdict,
    pub reason: CanaryDecisionReason,
    /// All selected candidate terminal outcomes, including admission rejection.
    pub selected: u64,
    pub admitted_terminal: u64,
    pub successes: u64,
    pub failures: u64,
    pub slow: u64,
}

pub(super) fn assess(
    revisions: &[CanaryRevisionBinding],
    counters: &[CanaryRevisionSnapshot],
    candidate: &RevisionId,
    thresholds: CanaryThresholds,
    coverage: CanaryCoverage,
    early_closed: bool,
) -> Result<CanaryAssessment, PlatformError> {
    let thresholds = thresholds.validate()?;
    let mut result = CanaryAssessment {
        verdict: CanaryVerdict::Incomplete,
        reason: CanaryDecisionReason::MissingCandidate,
        selected: 0,
        admitted_terminal: 0,
        successes: 0,
        failures: 0,
        slow: 0,
    };
    let Some(index) = revisions
        .iter()
        .position(|binding| binding.revision == *candidate)
    else {
        return Ok(result);
    };
    let Some(value) = counters.get(index) else {
        return Ok(result);
    };
    let outcomes = value.outcomes;
    let terminal = [
        outcomes.success,
        outcomes.domain_error,
        outcomes.platform_error,
        outcomes.deadline_exceeded,
        outcomes.cancelled,
    ]
    .into_iter()
    .try_fold(0u64, u64::checked_add);
    let bucket = CANARY_LATENCY_UPPER_MICROS
        .iter()
        .position(|edge| *edge == thresholds.latency_threshold_micros)
        .expect("validated latency boundary");
    let total_latency = value
        .latency_buckets
        .into_iter()
        .try_fold(0u64, u64::checked_add);
    let slow = value.latency_buckets[bucket + 1..]
        .iter()
        .copied()
        .try_fold(0u64, u64::checked_add);
    result.selected = value.selected;
    result.admitted_terminal = value.admitted_terminal;
    result.successes = outcomes.success;
    result.failures = terminal
        .and_then(|total| total.checked_sub(outcomes.success))
        .unwrap_or(0);
    result.slow = slow.unwrap_or(0);
    let (verdict, reason) = if early_closed {
        (
            CanaryVerdict::Incomplete,
            CanaryDecisionReason::WindowClosedEarly,
        )
    } else if terminal.is_none()
        || slow.is_none()
        || total_latency != terminal
        || value.admitted_terminal > value.admitted
        || value.admitted > value.selected
        || outcomes.success > value.admitted_terminal
        || terminal.is_some_and(|total| total > value.selected)
    {
        (
            CanaryVerdict::Incomplete,
            CanaryDecisionReason::CaptureIncomplete,
        )
    } else {
        classify(coverage, thresholds, &result, terminal.unwrap_or(0))
    };
    result.verdict = verdict;
    result.reason = reason;
    Ok(result)
}

fn classify(
    coverage: CanaryCoverage,
    thresholds: CanaryThresholds,
    value: &CanaryAssessment,
    terminal: u64,
) -> (CanaryVerdict, CanaryDecisionReason) {
    use CanaryDecisionReason as Reason;
    use CanaryVerdict as Verdict;
    match coverage {
        CanaryCoverage::Open => return (Verdict::Collecting, Reason::WindowOpen),
        CanaryCoverage::Draining => return (Verdict::Draining, Reason::WindowDraining),
        CanaryCoverage::Incomplete => return (Verdict::Incomplete, Reason::CaptureIncomplete),
        CanaryCoverage::NoSamples | CanaryCoverage::Insufficient | CanaryCoverage::CompleteData => {
        }
    }
    if terminal != value.selected {
        (Verdict::Incomplete, Reason::CaptureIncomplete)
    } else if terminal == 0 {
        (Verdict::NoData, Reason::NoCandidateSamples)
    } else if terminal < thresholds.minimum_candidate_samples {
        (Verdict::Insufficient, Reason::MinimumCandidateSamples)
    } else if value.admitted_terminal == 0 {
        (Verdict::Failed, Reason::NoAdmittedCandidate)
    } else if value.successes == 0 {
        (Verdict::Failed, Reason::NoSuccessfulCandidate)
    } else if !within(
        value.failures,
        terminal,
        thresholds.maximum_failure_basis_points,
    ) {
        (Verdict::Failed, Reason::FailureRateExceeded)
    } else if !within(value.slow, terminal, thresholds.maximum_slow_basis_points) {
        (Verdict::Failed, Reason::SlowRateExceeded)
    } else {
        (Verdict::Healthy, Reason::Healthy)
    }
}

fn within(numerator: u64, denominator: u64, basis_points: u16) -> bool {
    u128::from(numerator) * 10_000 <= u128::from(denominator) * u128::from(basis_points)
}
