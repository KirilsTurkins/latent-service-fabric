use std::path::Path;
use std::time::Duration;

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
        if self.schema != "latent.optimization.cache-behavior-plan.v1"
            || !matches!(self.profile.as_str(), "smoke" | "full")
            || !(1..=if self.full() { 7 } else { 1 }).contains(&self.repetition)
        {
            return Err("invalid fixed cache behavior plan".into());
        }
        Ok(())
    }
    pub fn full(&self) -> bool {
        self.profile == "full"
    }
    pub fn cold(&self) -> cold::plan::Plan {
        cold::plan::Plan {
            schema: "latent.optimization.cold-plan.v1".into(),
            profile: self.profile.clone(),
            repetition: self.repetition,
            compiler_workers: Some(2),
        }
    }
    pub fn attempts(&self) -> u64 {
        if self.full() {
            802
        } else {
            80
        }
    }
    pub fn commands(&self) -> u64 {
        2 * self.attempts() + 13
    }
    pub fn round_robin(&self) -> u32 {
        if self.full() {
            100
        } else {
            10
        }
    }
    pub fn locality(&self) -> u32 {
        if self.full() {
            100
        } else {
            20
        }
    }
    pub fn duration(&self) -> Duration {
        Duration::from_secs(300)
    }
    pub fn configuration(&self, path: &Path) -> Value {
        let mut config = self.cold().configuration(path);
        config["nodeId"] = json!("cache-comparison");
        config["cache"]["entries"] = json!(4);
        config
    }
}
