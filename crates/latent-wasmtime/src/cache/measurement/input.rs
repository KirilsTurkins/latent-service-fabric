use std::fs::{File, OpenOptions};
use std::io::{Read, Write};
use std::path::{Path, PathBuf};

use serde::Deserialize;
use sha2::{Digest, Sha256};

use crate::cache::PreparedCacheSnapshot;

const TRACE_SEED: u64 = 0x4c53_4643_4143_4845;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Plan {
    schema: String,
    profile: String,
    repetition: usize,
    variant: String,
    mode: String,
    pub(super) capacity: usize,
    pattern: String,
    pub(super) warmup_hits: usize,
    pub(super) measured_hits: usize,
    trace_seed: String,
    maximum_output_bytes: String,
    observation_hold_millis: usize,
}

impl Plan {
    fn validate(&self) -> Result<(), Box<dyn std::error::Error>> {
        let (warmup, measured, pairs) = match self.profile.as_str() {
            "smoke" => (16, 256, 1),
            "full" => (128, 16_384, 7),
            _ => return Err("invalid lookup profile".into()),
        };
        if self.schema != "latent.optimization.cache-lookup-plan.v1"
            || !matches!(self.variant.as_str(), "control" | "candidate")
            || !matches!(self.mode.as_str(), "normal" | "allocation")
            || !matches!(self.pattern.as_str(), "mru-hot" | "seeded-uniform")
            || ![4, 64, 4096].contains(&self.capacity)
            || self.repetition == 0
            || self.repetition > pairs
            || self.warmup_hits != warmup
            || self.measured_hits != measured
            || self.trace_seed != TRACE_SEED.to_string()
            || self.maximum_output_bytes != "8388608"
            || self.observation_hold_millis != 100
        {
            return Err("invalid fixed lookup plan".into());
        }
        Ok(())
    }

    pub(super) fn trace(&self, count: usize) -> Vec<u16> {
        let mut state = TRACE_SEED;
        (0..count)
            .map(|_| {
                if self.pattern == "mru-hot" {
                    u16::try_from(self.capacity - 1).expect("validated capacity")
                } else {
                    state ^= state << 13;
                    state ^= state >> 7;
                    state ^= state << 17;
                    u16::try_from(state & (self.capacity as u64 - 1)).expect("validated capacity")
                }
            })
            .collect()
    }
}

pub(super) struct Input {
    pub(super) plan: Plan,
    pub(super) plan_sha256: String,
    pub(super) identity_sha256: String,
    pub(super) output: PathBuf,
}

impl Input {
    pub(super) fn load() -> Result<Self, Box<dyn std::error::Error>> {
        let plan_bytes = read(
            &PathBuf::from(std::env::var_os("LSF_CACHE_LOOKUP_PLAN").ok_or("missing lookup plan")?),
            16_384,
        )?;
        let identity_bytes = read(
            &PathBuf::from(
                std::env::var_os("LSF_CACHE_LOOKUP_IDENTITY").ok_or("missing lookup identity")?,
            ),
            131_072,
        )?;
        let plan: Plan = serde_json::from_slice(&plan_bytes)?;
        plan.validate()?;
        if !serde_json::from_slice::<serde_json::Value>(&identity_bytes)?.is_object() {
            return Err("lookup identity is not an object".into());
        }
        let output = PathBuf::from(
            std::env::var_os("LSF_CACHE_LOOKUP_OUTPUT").ok_or("missing lookup output")?,
        );
        if !output.is_absolute() || !std::fs::symlink_metadata(&output)?.is_dir() {
            return Err("invalid lookup output directory".into());
        }
        Ok(Self {
            plan,
            plan_sha256: sha256(&plan_bytes),
            identity_sha256: sha256(&identity_bytes),
            output,
        })
    }
}

fn read(path: &Path, maximum: u64) -> Result<Vec<u8>, Box<dyn std::error::Error>> {
    if !path.is_absolute() || !std::fs::symlink_metadata(path)?.is_file() {
        return Err("invalid lookup input type or path".into());
    }
    let file = File::open(path)?;
    let metadata = file.metadata()?;
    if !metadata.is_file() || metadata.len() > maximum {
        return Err("lookup input exceeds bound".into());
    }
    let mut bytes = Vec::new();
    file.take(maximum + 1).read_to_end(&mut bytes)?;
    if bytes.len() as u64 != metadata.len() || bytes.len() as u64 > maximum {
        return Err("lookup input size changed".into());
    }
    Ok(bytes)
}

pub(super) fn write_new(path: &Path, bytes: &[u8]) -> std::io::Result<()> {
    let mut file = OpenOptions::new().write(true).create_new(true).open(path)?;
    file.write_all(bytes)?;
    file.sync_all()
}

pub(super) fn sha256(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

pub(super) fn verify_occupancy(
    snapshot: &PreparedCacheSnapshot,
    capacity: usize,
) -> Result<(), Box<dyn std::error::Error>> {
    if snapshot.entries != capacity
        || snapshot.maximum_entries != capacity
        || snapshot.source_bytes != capacity * 2
        || snapshot.maximum_source_bytes != capacity * 2
        || snapshot.metadata_bytes != capacity * 3
        || snapshot.maximum_metadata_bytes != capacity * 3
        || snapshot.compiled_image_bytes != capacity * 4
        || snapshot.maximum_compiled_image_bytes != capacity * 4
        || snapshot.preparing != 0
        || snapshot.maximum_concurrent_preparations != 1
        || snapshot.preparing_source_bytes != 0
        || snapshot.preparing_metadata_bytes != 0
        || snapshot.misses != capacity as u64
        || snapshot.evictions != 0
        || snapshot.invalidations != 0
    {
        return Err("cache lookup occupancy changed".into());
    }
    Ok(())
}
