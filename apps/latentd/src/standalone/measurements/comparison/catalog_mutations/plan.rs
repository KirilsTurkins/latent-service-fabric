use std::path::Path;

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

use super::Result;

pub(super) const OPERATIONS: [&str; 8] = [
    "publications",
    "seed_batches",
    "applies",
    "deletes",
    "gets",
    "resolves",
    "policies",
    "pins",
];

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Plan {
    pub schema: String,
    pub profile: String,
    pub repetition: u32,
    pub variant: String,
    pub shape: String,
    pub populated_size: u32,
    pub mode: String,
    pub sequence_ordinal: u32,
}

impl Plan {
    pub fn validate(&self) -> Result<()> {
        if self.schema != "latent.optimization.catalog-mutation-plan.v1"
            || !matches!(self.profile.as_str(), "smoke" | "full")
            || self.repetition != 1
            || !matches!(self.variant.as_str(), "control" | "candidate")
            || !matches!(self.shape.as_str(), "distinct" | "shared")
            || !matches!(
                self.mode.as_str(),
                "initial" | "reopen" | "allocation" | "allocation-reopen"
            )
        {
            return Err("catalog mutation plan selection".into());
        }
        let sizes: &[u32] = if self.profile == "full" {
            &[100, 1000, 10000]
        } else {
            &[4]
        };
        let position = if self.profiled() {
            if self.populated_size != if self.profile == "full" { 8 } else { 4 } {
                return Err("catalog mutation profile population".into());
            }
            0
        } else {
            sizes
                .iter()
                .position(|size| *size == self.populated_size)
                .ok_or("catalog mutation normal population")?
        };
        let shape = usize::from(self.shape == "shared");
        let first = if (position + shape).is_multiple_of(2) {
            "control"
        } else {
            "candidate"
        };
        let ordinal = if self.profiled() { sizes.len() * 8 } else { 0 }
            + position * 8
            + shape * 4
            + usize::from(self.variant != first) * 2
            + usize::from(self.reopen());
        if usize::try_from(self.sequence_ordinal)? != ordinal {
            return Err("catalog mutation sequence ordinal".into());
        }
        Ok(())
    }

    pub fn profiled(&self) -> bool {
        self.mode.starts_with("allocation")
    }
    pub fn reopen(&self) -> bool {
        self.mode.ends_with("reopen")
    }
    pub fn seconds(&self) -> u64 {
        if self.profiled() {
            180
        } else if self.profile == "smoke" {
            90
        } else if self.reopen() {
            1800
        } else {
            3600
        }
    }
    pub fn group(&self) -> String {
        format!(
            "{}-{:05}-{}-{}-r{:02}",
            if self.profiled() {
                "allocation"
            } else {
                "normal"
            },
            self.populated_size,
            self.shape,
            self.variant,
            self.repetition
        )
    }
    pub fn counts(&self) -> [u64; 8] {
        if self.reopen() {
            [0, 0, 0, 0, 1, 2, 2, 1]
        } else {
            [
                u64::from(self.populated_size),
                1,
                3,
                1,
                4,
                12,
                10 + u64::from(self.shape == "shared"),
                5,
            ]
        }
    }
    pub fn commands(&self) -> u64 {
        self.counts().iter().sum()
    }
    pub fn population(&self) -> Value {
        let mut value = Value::Object(
            OPERATIONS
                .into_iter()
                .zip(self.counts())
                .map(|(name, n)| (name.to_owned(), json!(n.to_string())))
                .collect(),
        );
        for (name, n) in [
            ("commands", self.commands()),
            ("invokes", 0),
            ("measured_mutations", if self.reopen() { 0 } else { 4 }),
            ("reopen_observations", u64::from(self.reopen())),
            ("warmup_calls", 0),
            ("preflight_calls", 0),
        ] {
            value[name] = json!(n.to_string());
        }
        value
    }
    pub fn configuration(&self, directory: &Path) -> Value {
        json!({"formatVersion":1,"dataDirectory":directory.join("data"),"nodeId":"catalog-mutation-comparison",
            "bind":"127.0.0.1:0","workers":{"runtime":2,"control":1},
            "cells":[{"class":"standard","capacity":2,"queueCapacity":3,"maximumMemoryBytes":67_108_864}],
            "execution":{"maximumCpuFuel":10_000_000_000_u64,"maximumWallTimeMillis":5000,"maximumLogBytes":16384},
            "catalogs":{"releaseEntries":self.populated_size.max(16),"releaseIndexBytes":1_073_741_824_u64,
                "deployments":self.populated_size.max(16),"deploymentStateBytes":1_073_741_824_u64},
            "cache":{"entries":4,"sourceBytes":67_108_864,"metadataBytes":16_777_216,"compiledImageBytes":268_435_456,"preparations":1},
            "retention":{"terminalEntries":64,"terminalTtlMillis":60_000,"bytes":20_971_520},
            "telemetry":{"queueEntries":256,"retainedEntries":128,"retainedBytes":1_048_576},"shutdownGraceMillis":500,
            "credentials":[{"token":"catalog-examples-00000000000000000000","subject":"catalog-examples","tenant":"examples","role":"operator"}]})
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn plan(
        profile: &str,
        size: u32,
        shape: &str,
        variant: &str,
        mode: &str,
        ordinal: u32,
    ) -> Plan {
        Plan {
            schema: "latent.optimization.catalog-mutation-plan.v1".to_owned(),
            profile: profile.to_owned(),
            repetition: 1,
            variant: variant.to_owned(),
            shape: shape.to_owned(),
            populated_size: size,
            mode: mode.to_owned(),
            sequence_ordinal: ordinal,
        }
    }

    #[test]
    fn fixed_populations_count_every_current_policy_pin_and_fresh_reopen() {
        for (profile, sizes, expected_normal, expected_total) in [
            ("smoke", &[4][..], 186, 372),
            ("full", &[100, 1000, 10000][..], 44_910, 45_112),
        ] {
            let mut ordinal = 0;
            let mut normal = 0;
            let mut total = 0;
            let allocation = if profile == "full" { 8 } else { 4 };
            for (populations, modes) in [
                (sizes, ["initial", "reopen"]),
                (&[allocation][..], ["allocation", "allocation-reopen"]),
            ] {
                for (index, size) in populations.iter().enumerate() {
                    for (shape_index, shape) in ["distinct", "shared"].into_iter().enumerate() {
                        let arms = if (index + shape_index).is_multiple_of(2) {
                            ["control", "candidate"]
                        } else {
                            ["candidate", "control"]
                        };
                        for arm in arms {
                            for mode in modes {
                                let value = plan(profile, *size, shape, arm, mode, ordinal);
                                value.validate().unwrap();
                                assert_eq!(value.counts()[7], if value.reopen() { 1 } else { 5 });
                                if !value.profiled() {
                                    normal += value.commands();
                                }
                                total += value.commands();
                                ordinal += 1;
                            }
                        }
                    }
                }
            }
            assert_eq!((normal, total), (expected_normal, expected_total));
            assert_eq!(ordinal, if profile == "full" { 32 } else { 16 });
        }
    }

    #[test]
    fn wrong_size_order_mode_and_historical_plan_fields_are_rejected() {
        let mut value = plan("smoke", 4, "distinct", "control", "initial", 0);
        value.validate().unwrap();
        value.sequence_ordinal = 1;
        assert!(value.validate().is_err());
        value.sequence_ordinal = 0;
        value.populated_size = 100;
        assert!(value.validate().is_err());
        value.populated_size = 4;
        value.mode = "allocation".to_owned();
        assert!(value.validate().is_err());
        value.mode = "initial".to_owned();
        let mut encoded = serde_json::to_value(value).unwrap();
        encoded["case"] = Value::Null;
        assert!(serde_json::from_value::<Plan>(encoded).is_err());
    }
}
