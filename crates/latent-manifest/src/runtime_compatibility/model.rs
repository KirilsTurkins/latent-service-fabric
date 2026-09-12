use latent_core::PlatformError;
use serde::{Deserialize, Serialize};

use super::{exhausted, invalid, version};

/// A deliberately finite native feature vocabulary, not a complete AOT key.
pub const CPU_FEATURES: &[&str] = &[
    "x86_64.sse2",
    "x86_64.cmpxchg16b",
    "x86_64.sse3",
    "x86_64.ssse3",
    "x86_64.sse4.1",
    "x86_64.sse4.2",
    "x86_64.popcnt",
    "x86_64.avx",
    "x86_64.avx2",
    "x86_64.fma",
    "x86_64.bmi1",
    "x86_64.bmi2",
    "x86_64.avx512bitalg",
    "x86_64.avx512dq",
    "x86_64.avx512f",
    "x86_64.avx512vl",
    "x86_64.avx512vbmi",
    "x86_64.lzcnt",
    "aarch64.lse",
    "aarch64.paca",
    "aarch64.fp16",
    "aarch64.dotprod",
];

/// Required engine and minimum semantic version.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RuntimeRequirement {
    pub engine: String,
    pub minimum_version: String,
}

/// Additional host requirements. Empty lists impose no corresponding constraint.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct RuntimeRequirements {
    pub runtime: Option<RuntimeRequirement>,
    pub target_triples: Vec<String>,
    pub cpu_features: Vec<String>,
}

impl RuntimeRequirements {
    /// Validates logical counts and caller-owned spare capacities before cloning.
    pub fn validate(&self) -> Result<(), PlatformError> {
        list(&self.target_triples, 8)?;
        list(&self.cpu_features, 32)?;
        if let Some(runtime) = &self.runtime {
            text(&runtime.engine)?;
            text(&runtime.minimum_version)?;
            if runtime.engine != "wasmtime" {
                return Err(invalid());
            }
            version(&runtime.minimum_version)?;
        }
        for value in &self.target_triples {
            if !target(value) {
                return Err(invalid());
            }
        }
        for value in &self.cpu_features {
            if !CPU_FEATURES.contains(&value.as_str()) {
                return Err(invalid());
            }
        }
        Ok(())
    }

    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.runtime.is_none() && self.target_triples.is_empty() && self.cpu_features.is_empty()
    }

    /// Conservative storage charge, including spare capacity of typed inputs.
    #[must_use]
    pub fn retained_bytes(&self) -> usize {
        let lists = [&self.target_triples, &self.cpu_features];
        let mut count = std::mem::size_of::<Self>();
        for values in lists {
            count = count.saturating_add(
                values
                    .capacity()
                    .saturating_mul(std::mem::size_of::<String>()),
            );
            for value in values {
                count = count.saturating_add(value.capacity());
            }
        }
        if let Some(runtime) = &self.runtime {
            count = count
                .saturating_add(runtime.engine.capacity())
                .saturating_add(runtime.minimum_version.capacity());
        }
        count
    }
}

pub(crate) fn target(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'_' | b'.' | b'-'))
        && value.split('-').count() >= 3
        && value.split('-').all(|part| !part.is_empty())
}

fn text(value: &String) -> Result<(), PlatformError> {
    if value.len() > 128 || value.capacity() > 256 {
        return Err(exhausted());
    }
    Ok(())
}

fn list(values: &Vec<String>, maximum: usize) -> Result<(), PlatformError> {
    if values.len() > maximum || values.capacity() > maximum {
        return Err(exhausted());
    }
    for (index, value) in values.iter().enumerate() {
        text(value)?;
        if values[..index].contains(value) {
            return Err(invalid());
        }
    }
    Ok(())
}
