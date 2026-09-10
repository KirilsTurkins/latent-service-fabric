use std::path::Path;

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

use super::Result;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Plan {
    pub schema: String,
    pub profile: String,
    pub repetition: u32,
    pub variant: String,
    pub shape: String,
    pub mode: String,
    pub sequence_ordinal: u32,
    pub case: Option<String>,
}

pub(super) const CASES: [&str; 4] = [
    "default-success",
    "named-success",
    "route-miss",
    "export-miss",
];

impl Plan {
    pub fn validate(&self) -> Result<()> {
        if self.schema != "latent.optimization.catalog-plan.v1"
            || !matches!(self.profile.as_str(), "smoke" | "full")
            || !matches!(self.variant.as_str(), "control" | "candidate")
            || !matches!(self.shape.as_str(), "distinct" | "shared")
            || !matches!(self.mode.as_str(), "initial" | "reopen" | "allocation")
            || !(1..=if self.full() { 1 } else { 3 }).contains(&self.repetition)
            || self.sequence_ordinal >= if self.full() { 24 } else { 40 }
            || (self.mode == "allocation") != self.case.is_some()
            || self
                .case
                .as_ref()
                .is_some_and(|case| !CASES.contains(&case.as_str()))
            || (self.mode == "allocation" && self.repetition != 1)
        {
            return Err("invalid fixed catalog plan".into());
        }
        Ok(())
    }

    pub fn full(&self) -> bool {
        self.profile == "full"
    }

    pub fn scales(&self) -> &'static [u32] {
        if self.full() {
            &[100, 1_000, 10_000, 100_000]
        } else {
            &[2, 4, 16]
        }
    }

    pub fn count(&self) -> u32 {
        if self.mode == "allocation" {
            16
        } else {
            *self.scales().last().unwrap()
        }
    }

    pub fn samples(&self, case: &str) -> u32 {
        match (self.full(), case) {
            (true, "default-success" | "named-success") => 5_000,
            (true, _) => 1_000,
            (false, "default-success" | "named-success") => 32,
            (false, _) => 64,
        }
    }

    pub fn allocation_samples(&self) -> u32 {
        if self.full() {
            256
        } else {
            64
        }
    }

    pub fn commands(&self) -> u64 {
        match self.mode.as_str() {
            "initial" => {
                if self.full() {
                    148_013
                } else {
                    604
                }
            }
            "reopen" => 7,
            "allocation" => 34 + u64::from(self.allocation_samples()),
            _ => unreachable!("validated plan"),
        }
    }

    pub fn seconds(&self) -> u64 {
        match (self.full(), self.mode.as_str()) {
            (_, "allocation") => 180,
            (true, "initial") => 3_600,
            (true, "reopen") => 1_800,
            _ => 90,
        }
    }

    pub fn population(&self) -> Value {
        let (publications, applies, resolves, pins, policies) = match self.mode.as_str() {
            "initial" => (
                self.count(),
                u32::try_from(self.scales().len()).expect("at most four scales") + 1,
                if self.full() { 48_003 } else { 579 },
                2,
                3,
            ),
            "reopen" => (0, 0, 4, 1, 2),
            "allocation" => (16, 1, 17 + self.allocation_samples(), 0, 0),
            _ => unreachable!("validated plan"),
        };
        json!({"commands":self.commands().to_string(),"invokes":"0",
            "publications":publications.to_string(),"applies":applies.to_string(),
            "resolves":resolves.to_string(),"pins":pins.to_string(),"policies":policies.to_string()})
    }

    pub fn configuration(&self, directory: &Path) -> Value {
        let maximum = self.count().max(16);
        json!({"formatVersion":1,"dataDirectory":directory.join("data"),"nodeId":"catalog-comparison",
            "bind":"127.0.0.1:0","workers":{"runtime":2,"control":1},
            "cells":[{"class":"standard","capacity":2,"queueCapacity":3,"maximumMemoryBytes":67_108_864}],
            "execution":{"maximumCpuFuel":10_000_000_000_u64,"maximumWallTimeMillis":5000,"maximumLogBytes":16384},
            "catalogs":{"releaseEntries":maximum,"releaseIndexBytes":1_073_741_824_u64,
                "deployments":maximum,"deploymentStateBytes":1_073_741_824_u64},
            "cache":{"entries":4,"sourceBytes":67_108_864,"metadataBytes":16_777_216,"compiledImageBytes":268_435_456,"preparations":1},
            "retention":{"terminalEntries":64,"terminalTtlMillis":60_000,"bytes":20_971_520},
            "telemetry":{"queueEntries":256,"retainedEntries":128,"retainedBytes":1_048_576},"shutdownGraceMillis":500,
            "credentials":[{"token":"catalog-examples-00000000000000000000","subject":"catalog-examples","tenant":"examples","role":"operator"}]})
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn closed_catalog_populations_match_every_counted_api_boundary() {
        let mut plan = Plan {
            schema: "latent.optimization.catalog-plan.v1".into(),
            profile: "full".into(),
            repetition: 1,
            variant: "control".into(),
            shape: "distinct".into(),
            mode: "initial".into(),
            sequence_ordinal: 1,
            case: None,
        };
        for profile in ["smoke", "full"] {
            plan.profile = profile.into();
            for mode in ["initial", "reopen", "allocation"] {
                plan.mode = mode.into();
                plan.case = (mode == "allocation").then(|| CASES[0].to_owned());
                plan.validate().unwrap();
                let values = plan.population();
                let sum: u64 = ["publications", "applies", "resolves", "pins", "policies"]
                    .iter()
                    .map(|key| values[key].as_str().unwrap().parse::<u64>().unwrap())
                    .sum();
                assert_eq!(sum, plan.commands());
            }
        }
        plan.profile = "full".into();
        plan.repetition = 2;
        assert!(plan.validate().is_err());
    }
}
