//! Identical deterministic logic for the native and Wasm comparison arms.
//!
//! Invocation payloads and results are canonical LSF WIT-value JSON arrays.
//! These functions perform no logging, clocks, IO, or retained-state access.

#![forbid(unsafe_code)]

mod framing;
#[cfg(test)]
mod tests;

use serde::{Deserialize, Serialize};

pub use framing::invoke;

pub const CONTRACT: &str = "optimization:benchmark/workloads@0.1.0";
pub const WORLD: &str = "optimization:benchmark/service@0.1.0";
pub const MEDIA_TYPE: &str = "application/vnd.latent.wit-values.v1+json";
pub const MAX_PAYLOAD_BYTES: usize = 1024 * 1024;
pub const MAX_TEXT_BYTES: usize = 1024 * 1024;
pub const MAX_COLLECTION_ITEMS: usize = 4096;
pub const MAX_COMPUTE_ROUNDS: u32 = 1_000_000;

/// Field order matches the WIT record and its canonical output encoding.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TransformValue {
    pub label: String,
    pub bytes: Vec<u8>,
    pub values: Vec<u32>,
}

/// Fixed public reasons; errors never include input bytes.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum WorkloadError {
    TextLimit,
    CollectionLimit,
    RoundLimit,
}

impl std::fmt::Display for WorkloadError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(match self {
            Self::TextLimit => "optimization-text-limit",
            Self::CollectionLimit => "optimization-collection-limit",
            Self::RoundLimit => "optimization-round-limit",
        })
    }
}

impl std::error::Error for WorkloadError {}

/// Returns the supplied string, including an empty string, unchanged.
pub fn echo(message: String) -> Result<String, WorkloadError> {
    if message.len() > MAX_TEXT_BYTES {
        return Err(WorkloadError::TextLimit);
    }
    Ok(message)
}

/// A data-dependent wrapping recurrence with an explicit finite round bound.
pub fn compute(seed: u32, rounds: u32) -> Result<u32, WorkloadError> {
    if rounds > MAX_COMPUTE_ROUNDS {
        return Err(WorkloadError::RoundLimit);
    }
    let mut value = seed;
    for round in 0..rounds {
        value = value
            .wrapping_add(round ^ 0x9e37_79b9)
            .rotate_left(5)
            .wrapping_mul(1_664_525)
            .wrapping_add(1_013_904_223);
        value ^= value.rotate_right(13);
    }
    Ok(value)
}

/// Reverses bytes and transforms each integer without changing collection sizes.
/// The label is deliberately preserved byte for byte, including Unicode.
pub fn transform(mut value: TransformValue) -> Result<TransformValue, WorkloadError> {
    if value.label.len() > MAX_TEXT_BYTES {
        return Err(WorkloadError::TextLimit);
    }
    if value.bytes.len() > MAX_COLLECTION_ITEMS || value.values.len() > MAX_COLLECTION_ITEMS {
        return Err(WorkloadError::CollectionLimit);
    }
    value.bytes.reverse();
    for (index, item) in value.values.iter_mut().enumerate() {
        let offset = u32::try_from(index).expect("collection bound fits u32");
        *item = item.wrapping_mul(3).wrapping_add(offset).rotate_left(7);
    }
    Ok(value)
}
