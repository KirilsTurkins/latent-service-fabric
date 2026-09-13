use crate::durable::{invalid, Result};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum AuditCanaryVerdict {
    Collecting,
    Draining,
    NoData,
    Insufficient,
    Incomplete,
    Failed,
    Healthy,
}
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum AuditCanaryReason {
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
/// Historical arithmetic and declared criteria. This value is never evidence
/// that can be supplied to a rollout publication method.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct AuditCanaryDecision {
    pub verdict: AuditCanaryVerdict,
    pub reason: AuditCanaryReason,
    pub observation_millis: u64,
    pub minimum_candidate_samples: u64,
    pub maximum_failure_basis_points: u16,
    pub latency_threshold_micros: u64,
    pub maximum_slow_basis_points: u16,
    pub selected: u64,
    pub admitted_terminal: u64,
    pub successes: u64,
    pub failures: u64,
    pub slow: u64,
}
impl AuditCanaryDecision {
    pub(crate) fn validate(&self) -> Result<()> {
        if !(1..=3_600_000).contains(&self.observation_millis)
            || !(1..=1_000_000).contains(&self.minimum_candidate_samples)
            || self.maximum_failure_basis_points >= 10_000
            || self.maximum_slow_basis_points > 10_000
            || ![
                100, 1000, 5000, 10_000, 50_000, 100_000, 1_000_000, 10_000_000,
            ]
            .contains(&self.latency_threshold_micros)
            || [
                self.selected,
                self.admitted_terminal,
                self.successes,
                self.failures,
                self.slow,
            ]
            .into_iter()
            .any(|value| value > 1_000_000)
            || ((self.verdict == AuditCanaryVerdict::Healthy)
                != (self.reason == AuditCanaryReason::Healthy))
        {
            return Err(invalid());
        }
        if self.verdict == AuditCanaryVerdict::Healthy
            && (self.selected < self.minimum_candidate_samples
                || self.admitted_terminal == 0
                || self.admitted_terminal > self.selected
                || self.successes == 0
                || self.successes > self.admitted_terminal
                || self.successes + self.failures != self.selected
                || self.slow > self.selected
                || u128::from(self.failures) * 10_000
                    > u128::from(self.selected) * u128::from(self.maximum_failure_basis_points)
                || u128::from(self.slow) * 10_000
                    > u128::from(self.selected) * u128::from(self.maximum_slow_basis_points))
        {
            return Err(invalid());
        }
        Ok(())
    }
}
