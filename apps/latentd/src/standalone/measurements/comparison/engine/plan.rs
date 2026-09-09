use super::Result;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::path::Path;

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub(super) struct Engine {
    pub allocator: String,
    pub optimization: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Plan {
    pub schema: String,
    pub profile: String,
    pub repetition: u32,
    pub sequence_ordinal: u32,
    pub variant: String,
    pub engine_profile_id: String,
    pub requested_engine: Option<Engine>,
}
impl Plan {
    pub fn validate(&self) -> Result<()> {
        let maximum = match self.profile.as_str() {
            "smoke" => 1,
            "full" => 7,
            _ => return Err("engine profile".into()),
        };
        if self.schema != "latent.optimization.engine-plan.v1"
            || !(1..=maximum).contains(&self.repetition)
            || self.sequence_ordinal >= 5
        {
            return Err("engine plan identity".into());
        }
        let mut population = [
            ("control", "D0"),
            ("candidate", "D0"),
            ("candidate", "P0"),
            ("candidate", "D1"),
            ("candidate", "P1"),
        ];
        population.rotate_left(usize::try_from((self.repetition - 1) % 5)?);
        if self.repetition.is_multiple_of(2) {
            population.reverse();
        }
        if population[usize::try_from(self.sequence_ordinal)?]
            != (self.variant.as_str(), self.engine_profile_id.as_str())
        {
            return Err("engine population order".into());
        }
        let expected = if self.variant == "control" {
            None
        } else {
            Some(Engine {
                allocator: if self.engine_profile_id.starts_with('P') {
                    "pooling"
                } else {
                    "on-demand"
                }
                .into(),
                optimization: if self.engine_profile_id.ends_with('1') {
                    "speed-and-size"
                } else {
                    "speed"
                }
                .into(),
            })
        };
        if self.requested_engine != expected {
            return Err("engine requested policy".into());
        }
        Ok(())
    }
    pub fn full(&self) -> bool {
        self.profile == "full"
    }
    pub fn offers(&self) -> u64 {
        if self.full() {
            794
        } else {
            52
        }
    }
    pub fn commands(&self) -> u64 {
        self.offers() * 2 + 21
    }
    pub fn phases(&self) -> [(&'static str, usize, u32, u32, u32); 4] {
        if self.full() {
            [
                ("echo", 0, 40, 400, 1),
                ("compute", 1, 4, 128, 1),
                ("memory", 6, 2, 64, 1),
                ("concurrent-echo", 0, 4, 128, 4),
            ]
        } else {
            [
                ("echo", 0, 2, 4, 1),
                ("compute", 1, 1, 4, 1),
                ("memory", 6, 1, 4, 1),
                ("concurrent-echo", 0, 4, 8, 4),
            ]
        }
    }
    pub fn configuration(&self, directory: &Path) -> Value {
        let mut value = json!({"formatVersion":1,"dataDirectory":directory.join("data"),"nodeId":"engine-comparison",
            "bind":"127.0.0.1:0","workers":{"runtime":2,"control":4},
            "cells":[{"class":"standard","capacity":4,"queueCapacity":64,"maximumMemoryBytes":67_108_864}],
            "execution":{"maximumCpuFuel":10_000_000_000_u64,"maximumWallTimeMillis":5000,"maximumLogBytes":16384},
            "catalogs":{"releaseEntries":16,"releaseIndexBytes":16_777_216,"deployments":16,"deploymentStateBytes":16_777_216},
            "cache":{"entries":8,"sourceBytes":134_217_728,"metadataBytes":67_108_864,"compiledImageBytes":536_870_912,"preparations":4,"compilerWorkers":2},
            "retention":{"terminalEntries":1024,"terminalTtlMillis":60000,"bytes":536_870_912},
            "telemetry":{"queueEntries":256,"retainedEntries":128,"retainedBytes":1_048_576},"shutdownGraceMillis":1000,
            "credentials":[
                {"token":"engine-credential-a-0000000000000000","subject":"engine-subject-a","tenant":"engine-a","role":"operator"},
                {"token":"engine-credential-b-0000000000000000","subject":"engine-subject-b","tenant":"engine-b","role":"operator"}]});
        if let Some(engine) = &self.requested_engine {
            value["engine"] = json!(engine);
        }
        value
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn fixed_populations_and_only_control_default_omit_engine() {
        for profile in ["smoke", "full"] {
            let mut count = 0;
            for repetition in 1..=if profile == "full" { 7 } else { 1 } {
                for sequence_ordinal in 0..5 {
                    for (variant, id) in [
                        ("control", "D0"),
                        ("candidate", "D0"),
                        ("candidate", "P0"),
                        ("candidate", "D1"),
                        ("candidate", "P1"),
                    ] {
                        let requested_engine = (variant == "candidate").then(|| Engine {
                            allocator: if id.starts_with('P') {
                                "pooling"
                            } else {
                                "on-demand"
                            }
                            .into(),
                            optimization: if id.ends_with('1') {
                                "speed-and-size"
                            } else {
                                "speed"
                            }
                            .into(),
                        });
                        let plan = Plan {
                            schema: "latent.optimization.engine-plan.v1".into(),
                            profile: profile.into(),
                            repetition,
                            sequence_ordinal,
                            variant: variant.into(),
                            engine_profile_id: id.into(),
                            requested_engine,
                        };
                        if plan.validate().is_ok() {
                            count += 1;
                            assert_eq!(
                                plan.phases()
                                    .iter()
                                    .map(|(_, _, w, m, _)| u64::from(w + m))
                                    .sum::<u64>()
                                    + 24,
                                plan.offers()
                            );
                            assert_eq!(plan.commands(), if profile == "full" { 1609 } else { 125 });
                            assert_eq!(
                                plan.configuration(Path::new("owned"))
                                    .get("engine")
                                    .is_none(),
                                variant == "control"
                            );
                        }
                    }
                }
            }
            assert_eq!(count, if profile == "full" { 35 } else { 5 });
        }
    }
}
