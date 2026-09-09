use std::fs::{File, OpenOptions};
use std::io::{Read, Write};
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use super::ProbeResult;

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Plan {
    pub schema: String,
    pub profile: String,
    pub repetition: usize,
    pub variant: String,
    pub mode: String,
    pub family: String,
    pub warmup_iterations: usize,
    pub measured_iterations: usize,
    pub observation_hold_millis: usize,
    pub maximum_output_bytes: String,
}

impl Plan {
    fn validate(&self) -> ProbeResult<()> {
        let (warmup, repetitions) = match self.profile.as_str() {
            "smoke" => (2, 1),
            "full" => (20, 7),
            _ => return Err("invalid codec profile".into()),
        };
        if self.schema != "latent.optimization.codec-plan.v1"
            || !matches!(self.variant.as_str(), "control" | "candidate")
            || !matches!(self.mode.as_str(), "normal" | "allocation")
            || !matches!(
                self.family.as_str(),
                "scalar-params"
                    | "byte-list"
                    | "nested-record"
                    | "string-64k"
                    | "string-near-limit"
                    | "escaped-unicode"
            )
            || !(1..=repetitions).contains(&self.repetition)
            || self.warmup_iterations != warmup
            || !(4..=4096).contains(&self.measured_iterations)
            || self.observation_hold_millis != 100
            || self.maximum_output_bytes != "8388608"
        {
            return Err("invalid fixed codec plan".into());
        }
        Ok(())
    }

    pub fn validate_work(&self, input: usize, expected: usize) -> ProbeResult<()> {
        let measured = if self.profile == "smoke" {
            4
        } else {
            (8 * 1024 * 1024 / input.max(expected).max(1)).clamp(4, 4096)
        };
        if self.measured_iterations != measured {
            return Err("codec plan differs from fixed byte-work bound".into());
        }
        Ok(())
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
    pub fn load() -> ProbeResult<Self> {
        let plan = read_env("LSF_CODEC_PLAN", 16_384)?;
        let identity = read_env("LSF_CODEC_IDENTITY", 131_072)?;
        let parsed: Plan = serde_json::from_slice(&plan)?;
        parsed.validate()?;
        let parsed_identity: serde_json::Value = serde_json::from_slice(&identity)?;
        if !parsed_identity.is_object() {
            return Err("codec identity must be an object".into());
        }
        let output =
            PathBuf::from(std::env::var_os("LSF_CODEC_OUTPUT").ok_or("missing codec output")?);
        if !output.is_absolute() || !std::fs::symlink_metadata(&output)?.is_dir() {
            return Err("invalid codec output directory".into());
        }
        Ok(Self {
            plan: parsed,
            identity: parsed_identity,
            plan_sha256: sha256(&plan),
            identity_sha256: sha256(&identity),
            output,
        })
    }
}

fn read_env(name: &str, maximum: u64) -> ProbeResult<Vec<u8>> {
    let path = PathBuf::from(std::env::var_os(name).ok_or("missing codec input")?);
    if !path.is_absolute() || !std::fs::symlink_metadata(&path)?.is_file() {
        return Err("invalid codec input file".into());
    }
    let file = File::open(path)?;
    let metadata = file.metadata()?;
    if !metadata.is_file() || metadata.len() > maximum {
        return Err("codec input exceeds bound".into());
    }
    let mut bytes = Vec::new();
    file.take(maximum + 1).read_to_end(&mut bytes)?;
    if bytes.len() as u64 != metadata.len() || bytes.len() as u64 > maximum {
        return Err("codec input size changed".into());
    }
    Ok(bytes)
}

pub(super) fn write_new(path: &Path, bytes: &[u8]) -> ProbeResult<()> {
    if bytes.len() > 8 * 1024 * 1024 {
        return Err("codec output exceeds bound".into());
    }
    let mut file = OpenOptions::new().write(true).create_new(true).open(path)?;
    file.write_all(bytes)?;
    file.sync_all()?;
    Ok(())
}

pub(super) fn sha256(bytes: &[u8]) -> String {
    format!("sha256:{:x}", Sha256::digest(bytes))
}

pub(super) fn file_ref(path: &str, bytes: &[u8]) -> serde_json::Value {
    serde_json::json!({"path": path, "sha256": sha256(bytes), "bytes": bytes.len().to_string()})
}
