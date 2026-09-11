use std::fs::{File, OpenOptions};
use std::io::{Read, Write};
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use super::Result;

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Plan {
    pub schema: String,
    pub profile: String,
    pub variant: String,
    pub case: String,
    pub mode: String,
    pub observation_hold_millis: u32,
}

#[derive(Debug, Serialize)]
pub(super) struct Settings {
    pub tenants: u32,
    pub measured_offers: u32,
    pub warmup_offers: u32,
    pub rate_per_second: u32,
    pub pending_capacity: u32,
    pub queue_capacity: u32,
    pub cells: u32,
    pub hold_millis: u32,
    pub original_budget_millis: u32,
    pub counters_enabled: bool,
}

impl Plan {
    pub fn settings(&self) -> Result<Settings> {
        if self.schema != "latent.optimization.scheduler-plan.v1"
            || !matches!(self.profile.as_str(), "smoke" | "full")
            || !matches!(self.variant.as_str(), "control" | "candidate")
            || !matches!(self.mode.as_str(), "normal" | "allocation")
            || self.observation_hold_millis != 100
            || (self.mode == "allocation" && self.case != "cancel-many")
        {
            return Err("invalid scheduler plan".into());
        }
        let full = self.profile == "full";
        let (tenants, measured_offers, rate_per_second) = match self.case.as_str() {
            "closed-one" => (1, if full { 128 } else { 16 }, 0),
            "saturated-one" => (1, if full { 2_000 } else { 200 }, 1_000),
            "saturated-many" => (32, if full { 2_000 } else { 200 }, 1_000),
            "reference-many" => (32, if full { 200 } else { 20 }, 100),
            "cancel-one" => (1, 68, 0),
            "cancel-many" => (8, 68, 0),
            _ => return Err("invalid scheduler case".into()),
        };
        let storm = self.storm();
        Ok(Settings {
            tenants,
            measured_offers,
            warmup_offers: if storm { 0 } else { 8 },
            rate_per_second,
            pending_capacity: if self.case == "closed-one" { 1 } else { 64 },
            queue_capacity: if storm { 64 } else { 32 },
            cells: 4,
            hold_millis: 10,
            original_budget_millis: 1_000,
            counters_enabled: storm && self.mode == "normal",
        })
    }

    pub fn storm(&self) -> bool {
        matches!(self.case.as_str(), "cancel-one" | "cancel-many")
    }
}

pub(super) struct Input {
    pub plan: Plan,
    pub identity: serde_json::Value,
    pub plan_sha256: String,
    pub identity_sha256: String,
    pub output: PathBuf,
}

impl Input {
    pub fn load() -> Result<Self> {
        let plan = read_env("LSF_SCHEDULER_PLAN", 16_384)?;
        let identity = read_env("LSF_SCHEDULER_IDENTITY", 131_072)?;
        let parsed: Plan = serde_json::from_slice(&plan)?;
        parsed.settings()?;
        let identity_value: serde_json::Value = serde_json::from_slice(&identity)?;
        if !identity_value.is_object() {
            return Err("scheduler identity must be an object".into());
        }
        let output =
            PathBuf::from(std::env::var_os("LSF_SCHEDULER_OUTPUT").ok_or("missing output")?);
        if !output.is_absolute() || !std::fs::symlink_metadata(&output)?.is_dir() {
            return Err("invalid scheduler output directory".into());
        }
        Ok(Self {
            plan: parsed,
            identity: identity_value,
            plan_sha256: sha256(&plan),
            identity_sha256: sha256(&identity),
            output,
        })
    }
}

fn read_env(name: &str, maximum: u64) -> Result<Vec<u8>> {
    let path = PathBuf::from(std::env::var_os(name).ok_or("missing scheduler input")?);
    if !path.is_absolute() || !std::fs::symlink_metadata(&path)?.is_file() {
        return Err("invalid scheduler input path".into());
    }
    let file = File::open(path)?;
    let size = file.metadata()?.len();
    if size > maximum {
        return Err("scheduler input bound".into());
    }
    let mut bytes = Vec::new();
    file.take(maximum + 1).read_to_end(&mut bytes)?;
    if u64::try_from(bytes.len())? != size {
        return Err("scheduler input changed".into());
    }
    Ok(bytes)
}

pub(super) fn write_new(path: &Path, bytes: &[u8]) -> Result<()> {
    if bytes.len() > 32 * 1024 * 1024 {
        return Err("scheduler raw output bound".into());
    }
    let mut output = OpenOptions::new().create_new(true).write(true).open(path)?;
    output.write_all(bytes)?;
    output.sync_all()?;
    Ok(())
}

pub(super) fn sha256(bytes: &[u8]) -> String {
    format!("sha256:{:x}", Sha256::digest(bytes))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn fixed_full_and_smoke_populations_include_every_warmup_and_storm_offer() {
        for (profile, expected) in [("full", 9_128), ("smoke", 1_344)] {
            let mut total = 0;
            for case in [
                "closed-one",
                "saturated-one",
                "saturated-many",
                "reference-many",
                "cancel-one",
                "cancel-many",
            ] {
                let plan = Plan {
                    schema: "latent.optimization.scheduler-plan.v1".to_owned(),
                    profile: profile.to_owned(),
                    variant: "control".to_owned(),
                    case: case.to_owned(),
                    mode: "normal".to_owned(),
                    observation_hold_millis: 100,
                };
                let settings = plan.settings().unwrap();
                total += 2 * (settings.measured_offers + settings.warmup_offers);
                assert_eq!(settings.cells, 4);
                assert_eq!(settings.original_budget_millis, 1_000);
                assert_eq!(settings.queue_capacity, if plan.storm() { 64 } else { 32 });
            }
            total += 2 * 68;
            assert_eq!(total, expected);
        }
    }

    #[test]
    fn allocation_is_only_the_fixed_many_tenant_storm() {
        let mut plan = Plan {
            schema: "latent.optimization.scheduler-plan.v1".to_owned(),
            profile: "full".to_owned(),
            variant: "candidate".to_owned(),
            case: "cancel-many".to_owned(),
            mode: "allocation".to_owned(),
            observation_hold_millis: 100,
        };
        let settings = plan.settings().unwrap();
        assert!(!settings.counters_enabled);
        assert_eq!(settings.tenants, 8);
        assert_eq!(settings.measured_offers, 68);
        plan.case = "cancel-one".to_owned();
        assert!(plan.settings().is_err());
    }
}
