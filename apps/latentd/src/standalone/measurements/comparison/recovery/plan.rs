use super::{cold, Result};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::path::Path;

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Plan {
    pub schema: String,
    pub profile: String,
    pub repetition: u32,
}

impl Plan {
    pub fn validate(&self) -> Result<()> {
        if self.schema != "latent.optimization.recovery-plan.v1"
            || !matches!(self.profile.as_str(), "smoke" | "full")
            || self.repetition != 1
        {
            return Err("invalid fixed recovery plan".into());
        }
        Ok(())
    }

    pub fn configuration(&self, path: &Path) -> Value {
        let mut config = cold::plan::Plan {
            schema: "latent.optimization.cold-plan.v1".into(),
            profile: self.profile.clone(),
            repetition: 1,
            compiler_workers: Some(2),
        }
        .configuration(path);
        config["nodeId"] = json!("transport-recovery");
        config["cache"]["entries"] = json!(4);
        config["retention"]["terminalEntries"] = json!(128);
        config["credentials"][0]["tenant"] = json!("tests");
        config
    }
}

#[derive(Clone, Copy)]
pub(super) struct Case {
    pub name: &'static str,
    pub budget: u64,
    pub function: &'static str,
    pub round: u32,
}

pub(super) fn cases() -> Vec<Case> {
    let mut rows = Vec::with_capacity(61);
    rows.push(Case {
        name: "prewarm",
        budget: 1000,
        function: "identify",
        round: 0,
    });
    for round in 0..3 {
        for budget in [1, 2, 5, 10] {
            for name in ["expiry", "disconnect"] {
                rows.push(Case {
                    name,
                    budget,
                    function: "spin",
                    round,
                });
                rows.push(Case {
                    name: "recovery",
                    budget: 1000,
                    function: "identify",
                    round,
                });
            }
        }
    }
    for round in 0..5 {
        rows.push(Case {
            name: "running-disconnect",
            budget: 1000,
            function: "spin",
            round,
        });
        rows.push(Case {
            name: "recovery",
            budget: 1000,
            function: "identify",
            round,
        });
    }
    rows.push(Case {
        name: "positive-cancel",
        budget: 1000,
        function: "spin",
        round: 0,
    });
    rows.push(Case {
        name: "recovery",
        budget: 1000,
        function: "identify",
        round: 0,
    });
    rows
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn fixed_population_repeats_every_short_boundary_and_exceeds_cell_capacity() {
        let rows = cases();
        assert_eq!(rows.len(), 61);
        for budget in [1, 2, 5, 10] {
            for name in ["expiry", "disconnect"] {
                assert_eq!(
                    rows.iter()
                        .filter(|row| row.name == name && row.budget == budget)
                        .count(),
                    3
                );
            }
        }
        assert_eq!(
            rows.iter()
                .filter(|row| row.name == "running-disconnect")
                .count(),
            5
        );
        assert_eq!(rows.iter().filter(|row| row.name == "recovery").count(), 30);
        assert_eq!(rows[59].name, "positive-cancel");
        assert!(rows
            .iter()
            .enumerate()
            .filter(|(_, row)| row.function == "spin")
            .all(|(index, _)| rows[index + 1].name == "recovery"));
    }
}
