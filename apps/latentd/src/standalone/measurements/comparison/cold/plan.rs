use std::path::Path;
use std::time::Duration;

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

use super::Result;

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(in crate::standalone::measurements::comparison) struct Plan {
    pub schema: String,
    pub profile: String,
    pub repetition: u32,
    pub compiler_workers: Option<u32>,
}

impl Plan {
    pub fn validate(&self) -> Result<()> {
        if self.schema != "latent.optimization.cold-plan.v1"
            || !matches!(self.profile.as_str(), "smoke" | "full")
            || !(1..=if self.full() { 7 } else { 1 }).contains(&self.repetition)
            || !matches!(self.compiler_workers, None | Some(2))
        {
            return Err("invalid fixed cold measurement plan".into());
        }
        Ok(())
    }

    pub fn full(&self) -> bool {
        self.profile == "full"
    }
    pub fn warmup(&self) -> u32 {
        if self.full() {
            40
        } else {
            2
        }
    }
    pub fn baseline(&self) -> u32 {
        if self.full() {
            400
        } else {
            4
        }
    }
    pub fn stream(&self) -> u32 {
        if self.full() {
            128
        } else {
            16
        }
    }
    pub fn healthy(&self) -> u32 {
        if self.full() {
            8
        } else {
            2
        }
    }
    pub fn attempts(&self) -> u64 {
        if self.full() {
            853
        } else {
            77
        }
    }
    pub fn commands(&self) -> u64 {
        2 * self.attempts() + 23
    }
    pub fn duration(&self) -> Duration {
        Duration::from_secs(if self.full() { 300 } else { 120 })
    }
    pub fn cold_offset(&self) -> Duration {
        Duration::from_millis(if self.full() { 16 } else { 4 })
    }

    pub fn configuration(&self, directory: &Path) -> Value {
        let mut value = json!({"formatVersion":1,"dataDirectory":directory.join("data"),"nodeId":"cold-comparison",
            "bind":"127.0.0.1:0","workers":{"runtime":2,"control":4},
            "cells":[{"class":"standard","capacity":4,"queueCapacity":64,"maximumMemoryBytes":67_108_864}],
            "execution":{"maximumCpuFuel":10_000_000_000_u64,"maximumWallTimeMillis":5000,"maximumLogBytes":16384},
            "catalogs":{"releaseEntries":16,"releaseIndexBytes":16_777_216,"deployments":16,"deploymentStateBytes":16_777_216},
            "cache":{"entries":8,"sourceBytes":134_217_728,"metadataBytes":67_108_864,"compiledImageBytes":536_870_912,"preparations":4},
            "retention":{"terminalEntries":2048,"terminalTtlMillis":60_000,"bytes":536_870_912},
            "telemetry":{"queueEntries":256,"retainedEntries":128,"retainedBytes":1_048_576},"shutdownGraceMillis":1000,
            "credentials":[{"token":"comparison-examples-000000000000000","subject":"comparison-examples","tenant":"examples","role":"operator"}]});
        if let Some(workers) = self.compiler_workers {
            value["cache"]["compilerWorkers"] = json!(workers);
        }
        value
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn populations_count_every_offer_and_control_without_hidden_retries() {
        for profile in ["smoke", "full"] {
            let plan = Plan {
                schema: "latent.optimization.cold-plan.v1".into(),
                profile: profile.into(),
                repetition: 1,
                compiler_workers: None,
            };
            plan.validate().unwrap();
            assert_eq!(
                u64::from(
                    plan.warmup()
                        + plan.baseline()
                        + 3 * plan.stream()
                        + 8
                        + 5
                        + 8
                        + plan.healthy()
                ),
                plan.attempts()
            );
            assert_eq!(plan.commands(), if plan.full() { 1729 } else { 177 });
            let config = plan.configuration(Path::new("fixture"));
            assert!(config["cache"].get("compilerWorkers").is_none());
            assert_eq!(config["cache"]["preparations"], 4);
            assert_eq!(config["workers"]["control"], 4);
        }
    }
}
