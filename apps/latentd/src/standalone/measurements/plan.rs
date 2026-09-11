use std::time::Duration;

use serde::{Deserialize, Serialize};

use super::Result;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Profile {
    Smoke,
    Full,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Workload {
    Scale,
    Soak,
    Benchmark,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct MeasurementPlan {
    pub schema: String,
    pub profile: Profile,
    pub kind: Workload,
    pub repetition: u32,
    pub scale_counts: Vec<u32>,
    pub route_samples: u32,
    pub warmup_invocations: u32,
    pub measured_invocations: u32,
    pub batch_size: u32,
    pub concurrency: u32,
    pub benchmark_samples: u32,
    #[serde(with = "decimal")]
    pub maximum_run_seconds: u64,
    #[serde(with = "decimal")]
    pub maximum_output_bytes: u64,
}

impl MeasurementPlan {
    pub fn validate(&self) -> Result<()> {
        let (scales, route, warmup, measured, batch, benchmark, seconds, bytes) = match self.profile
        {
            Profile::Smoke => (vec![2, 4], 16, 4, 20, 20, 4, 90, 8 * 1024 * 1024),
            Profile::Full => (
                vec![100, 1000, 10_000, 100_000],
                10_000,
                1000,
                100_000,
                1000,
                400,
                21_600,
                128 * 1024 * 1024,
            ),
        };
        if self.schema != "latent.phase1.measurement-plan.v1"
            || !(1..=32).contains(&self.repetition)
            || self.scale_counts != scales
            || self.route_samples != route
            || self.warmup_invocations != warmup
            || self.measured_invocations != measured
            || self.batch_size != batch
            || self.concurrency != 2
            || self.benchmark_samples != benchmark
            || self.maximum_run_seconds != seconds
            || self.maximum_output_bytes != bytes
        {
            return Err(std::io::Error::other("invalid fixed measurement plan").into());
        }
        Ok(())
    }

    pub fn duration(&self) -> Duration {
        Duration::from_secs(self.maximum_run_seconds)
    }

    pub fn maximum_work(&self) -> (u64, u64) {
        match (self.profile, self.kind) {
            (Profile::Smoke, Workload::Benchmark) => (128, 4096),
            (Profile::Smoke, _) => (64, 512),
            (Profile::Full, _) => (200_000, 1_000_000),
        }
    }
}

mod decimal {
    use serde::{de::Error, Deserialize, Deserializer, Serializer};
    // Serde's with adapter requires the borrowed field signature.
    #[allow(clippy::trivially_copy_pass_by_ref)]
    pub fn serialize<S: Serializer>(value: &u64, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.serialize_str(&value.to_string())
    }
    pub fn deserialize<'de, D: Deserializer<'de>>(deserializer: D) -> Result<u64, D::Error> {
        let text = String::deserialize(deserializer)?;
        let value = text.parse::<u64>().map_err(D::Error::custom)?;
        if value.to_string() != text {
            return Err(D::Error::custom("noncanonical u64"));
        }
        Ok(value)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn full_measurements_cannot_be_replaced_with_smoke_counts() {
        let mut plan: MeasurementPlan = serde_json::from_value(serde_json::json!({
            "schema":"latent.phase1.measurement-plan.v1","profile":"smoke","kind":"scale","repetition":1,
            "scale_counts":[2,4],"route_samples":16,"warmup_invocations":4,"measured_invocations":20,
            "batch_size":20,"concurrency":2,"benchmark_samples":4,"maximum_run_seconds":"90",
            "maximum_output_bytes":"8388608"})).unwrap();
        plan.validate().unwrap();
        plan.profile = Profile::Full;
        assert!(plan.validate().is_err());
    }
}
