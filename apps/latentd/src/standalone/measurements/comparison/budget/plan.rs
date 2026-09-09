use std::path::Path;

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

use super::{cold, Result};

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Plan {
    pub schema: String,
    pub profile: String,
    pub repetition: u32,
}

impl Plan {
    pub fn validate(&self) -> Result<()> {
        if self.schema != "latent.optimization.budget-lifecycle-plan.v1"
            || !matches!(self.profile.as_str(), "smoke" | "full")
            || !(1..=if self.profile == "full" { 7 } else { 1 }).contains(&self.repetition)
        {
            return Err("invalid fixed budget lifecycle plan".into());
        }
        Ok(())
    }

    pub fn configuration(&self, path: &Path) -> Value {
        let mut config = cold::plan::Plan {
            schema: "latent.optimization.cold-plan.v1".into(),
            profile: self.profile.clone(),
            repetition: self.repetition,
            compiler_workers: Some(2),
        }
        .configuration(path);
        config["nodeId"] = json!("budget-lifecycle");
        config["cache"]["entries"] = json!(4);
        config["retention"]["terminalEntries"] = json!(64);
        config["credentials"][0]["tenant"] = json!("tests");
        config
    }
}
