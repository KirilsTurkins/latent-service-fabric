//! Durable criteria and historical summaries; none of these values is a grant.
use super::{codec, corrupt, invalid, Result};
use latent_core::ArtifactBlobDigest;
use latent_manifest::__serde::{Deserialize, Deserializer, Serialize};
use latent_telemetry::phase2_canary::{CanaryRevisionSnapshot, CanaryThresholds};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(
    crate = "latent_manifest::__serde",
    rename_all = "camelCase",
    deny_unknown_fields
)]
pub struct RolloutCanaryPolicy {
    pub format_version: u32,
    pub observation_millis: u64,
    pub minimum_candidate_samples: u64,
    pub maximum_failure_basis_points: u16,
    pub latency_threshold_micros: u64,
    pub maximum_slow_basis_points: u16,
}
impl RolloutCanaryPolicy {
    pub fn validate(&self) -> Result<()> {
        if self.format_version != 1 || !(1..=3_600_000).contains(&self.observation_millis) {
            return Err(invalid());
        }
        self.thresholds().validate()?;
        Ok(())
    }
    #[must_use]
    pub const fn thresholds(&self) -> CanaryThresholds {
        CanaryThresholds {
            minimum_candidate_samples: self.minimum_candidate_samples,
            maximum_failure_basis_points: self.maximum_failure_basis_points,
            latency_threshold_micros: self.latency_threshold_micros,
            maximum_slow_basis_points: self.maximum_slow_basis_points,
        }
    }
    pub fn digest(&self) -> Result<ArtifactBlobDigest> {
        self.validate()?;
        Ok(codec::hash(&codec::encode(self, 1024)?))
    }
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(
    crate = "latent_manifest::__serde",
    rename_all = "camelCase",
    deny_unknown_fields
)]
pub struct RolloutCanaryCounters {
    pub selected: u64,
    pub admitted: u64,
    pub admitted_terminal: u64,
    pub success: u64,
    pub domain_error: u64,
    pub platform_error: u64,
    pub deadline_exceeded: u64,
    pub cancelled: u64,
    pub latency_buckets: [u64; 9],
}
impl From<CanaryRevisionSnapshot> for RolloutCanaryCounters {
    fn from(value: CanaryRevisionSnapshot) -> Self {
        Self {
            selected: value.selected,
            admitted: value.admitted,
            admitted_terminal: value.admitted_terminal,
            success: value.outcomes.success,
            domain_error: value.outcomes.domain_error,
            platform_error: value.outcomes.platform_error,
            deadline_exceeded: value.outcomes.deadline_exceeded,
            cancelled: value.outcomes.cancelled,
            latency_buckets: value.latency_buckets,
        }
    }
}
impl RolloutCanaryCounters {
    fn validate(&self) -> Result<()> {
        let terminal = [
            self.success,
            self.domain_error,
            self.platform_error,
            self.deadline_exceeded,
            self.cancelled,
        ]
        .into_iter()
        .try_fold(0u64, u64::checked_add)
        .ok_or_else(corrupt)?;
        let latency = self
            .latency_buckets
            .into_iter()
            .try_fold(0u64, u64::checked_add)
            .ok_or_else(corrupt)?;
        if terminal != self.selected
            || latency != terminal
            || self.admitted != self.admitted_terminal
            || self.admitted > self.selected
            || self.selected > 1_000_000
        {
            return Err(corrupt());
        }
        Ok(())
    }
}
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(
    crate = "latent_manifest::__serde",
    rename_all = "camelCase",
    deny_unknown_fields
)]
pub struct RolloutCanaryDecision {
    pub format_version: u32,
    #[serde(with = "codec::text")]
    pub policy_digest: ArtifactBlobDigest,
    #[serde(with = "codec::text")]
    pub control_digest: ArtifactBlobDigest,
    #[serde(with = "codec::text")]
    pub evidence_digest: ArtifactBlobDigest,
    pub window_epoch: u64,
    pub observed_millis: u64,
    pub candidate: RolloutCanaryCounters,
    pub baseline: RolloutCanaryCounters,
}
impl RolloutCanaryDecision {
    pub(crate) fn evidence_hash(&self) -> Result<ArtifactBlobDigest> {
        let mut value = latent_manifest::__serde_json::to_value(self).map_err(|_| corrupt())?;
        value
            .as_object_mut()
            .ok_or_else(corrupt)?
            .remove("evidenceDigest");
        Ok(codec::hash(&codec::encode(
            &value,
            super::MAX_RECEIPT_BYTES,
        )?))
    }
    pub(crate) fn validate(&self, policy: &RolloutCanaryPolicy) -> Result<()> {
        self.candidate.validate()?;
        self.baseline.validate()?;
        if self.format_version != 1
            || self.window_epoch == 0
            || self.observed_millis != policy.observation_millis
            || self.policy_digest != policy.digest()?
            || self.evidence_digest != self.evidence_hash()?
            || self.candidate.selected < policy.minimum_candidate_samples
            || self.candidate.admitted_terminal == 0
            || self.candidate.success == 0
        {
            return Err(corrupt());
        }
        let failures = self.candidate.selected - self.candidate.success;
        let boundary = latent_telemetry::phase2_canary::CANARY_LATENCY_UPPER_MICROS
            .iter()
            .position(|value| *value == policy.latency_threshold_micros)
            .ok_or_else(corrupt)?;
        let slow: u64 = self.candidate.latency_buckets[boundary + 1..].iter().sum();
        if u128::from(failures) * 10_000
            > u128::from(self.candidate.selected) * u128::from(policy.maximum_failure_basis_points)
            || u128::from(slow) * 10_000
                > u128::from(self.candidate.selected) * u128::from(policy.maximum_slow_basis_points)
        {
            return Err(corrupt());
        }
        Ok(())
    }
}
pub(super) fn optional<'de, D, T>(deserializer: D) -> std::result::Result<Option<T>, D::Error>
where
    D: Deserializer<'de>,
    T: Deserialize<'de>,
{
    T::deserialize(deserializer).map(Some)
}
