use std::time::Duration;

use serde::{Deserialize, Serialize};

use super::{Profile, Result};

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Plan {
    pub schema: String,
    pub profile: Profile,
    pub repetition: u32,
    pub warmup_samples: u32,
    pub measured_samples: u32,
    pub maximum_run_seconds: String,
    pub maximum_output_bytes: String,
}

impl Plan {
    pub fn validate(&self) -> Result<()> {
        let (warmup, measured, seconds) = match self.profile {
            Profile::Smoke => (2, 4, "120"),
            Profile::Full => (40, 400, "600"),
        };
        if self.schema != "latent.phase1.paired-plan.v1"
            || !(1..=7).contains(&self.repetition)
            || self.warmup_samples != warmup
            || self.measured_samples != measured
            || self.maximum_run_seconds != seconds
            || self.maximum_output_bytes != "16777216"
        {
            return Err("invalid fixed comparison plan".into());
        }
        Ok(())
    }

    pub fn count(&self) -> u32 {
        self.warmup_samples + self.measured_samples
    }

    pub fn duration(&self) -> Duration {
        Duration::from_secs(match self.profile {
            Profile::Smoke => 120,
            Profile::Full => 600,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn smoke_counts_and_noncanonical_bounds_cannot_claim_full_evidence() {
        let mut plan: Plan = serde_json::from_value(serde_json::json!({
            "schema":"latent.phase1.paired-plan.v1","profile":"smoke","repetition":1,
            "warmup_samples":2,"measured_samples":4,"maximum_run_seconds":"120",
            "maximum_output_bytes":"16777216"
        }))
        .unwrap();
        plan.validate().unwrap();
        assert_eq!(plan.count(), 6);
        plan.profile = Profile::Full;
        assert!(plan.validate().is_err());
        plan.profile = Profile::Smoke;
        plan.maximum_run_seconds = "0120".into();
        assert!(plan.validate().is_err());
    }
}
