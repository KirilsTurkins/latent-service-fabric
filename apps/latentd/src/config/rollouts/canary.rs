//! Observation resource limits; policies remain explicit on each rollout.
use latent_core::PlatformError;
use latent_telemetry::Phase2CanaryOutcomeWindowConfig;
use serde::{Deserialize, Deserializer};

#[derive(Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CanaryConfig {
    #[serde(default = "windows")]
    windows: usize,
    #[serde(default = "samples")]
    samples_per_window: usize,
    #[serde(default = "total")]
    total_samples: usize,
    #[serde(default = "live")]
    live_samples: usize,
    #[serde(default = "snapshots")]
    snapshot_owners: usize,
}

const fn windows() -> usize {
    16
}
const fn samples() -> usize {
    10_000
}
const fn total() -> usize {
    100_000
}
const fn live() -> usize {
    4096
}
const fn snapshots() -> usize {
    4
}

pub(super) fn present<'de, D: Deserializer<'de>>(
    decoder: D,
) -> Result<Option<CanaryConfig>, D::Error> {
    CanaryConfig::deserialize(decoder).map(Some)
}

impl CanaryConfig {
    pub(super) fn derive(&self) -> Result<Phase2CanaryOutcomeWindowConfig, PlatformError> {
        if !(1..=64).contains(&self.windows)
            || !(1..=1_000_000).contains(&self.samples_per_window)
            || !(1..=16_000_000).contains(&self.total_samples)
            || self.total_samples < self.samples_per_window
            || !(1..=65_536).contains(&self.live_samples)
            || !(1..=16).contains(&self.snapshot_owners)
        {
            return Err(super::super::invalid("rollout canary observation limits"));
        }
        Ok(Phase2CanaryOutcomeWindowConfig {
            maximum_series: self.windows,
            maximum_samples_per_series: self.samples_per_window,
            maximum_total_samples: self.total_samples,
            maximum_live_samples: self.live_samples,
            maximum_snapshot_owners: self.snapshot_owners,
            maximum_identity_bytes: 256,
        })
    }
}
