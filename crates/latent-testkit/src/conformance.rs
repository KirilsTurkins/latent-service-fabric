//! Bounded Phase 1 evidence, independent of a concrete node or RPC driver.
//!
//! This profile establishes selected deterministic behavior. It deliberately
//! cannot certify completion of the full Phase 1 performance/resource gate.

mod model;
mod work;
mod writer;

pub use model::{
    ArtifactReference, CaseEvidence, ConformanceReport, DeferredEvidence, DriverEvidence,
    DriverWork, EvidenceStatus, FileIdentity, ProcessSample, ReportIdentity, ShutdownEvidence,
};
pub use work::{WorkCounter, WorkCounts};
pub use writer::{encode_bounded, ReportLimits};

pub const REPORT_SCHEMA: &str = "latent.phase1.conformance.v1";
pub const PROFILE: &str = "bounded-deterministic";
pub const MAXIMUM_INVOKE_ATTEMPTS: u64 = 64;
pub const MAXIMUM_COMMANDS: u64 = 256;
pub const PROCESS_MAXIMUM_INVOKE_ATTEMPTS: u64 = 36;
pub const PROCESS_MAXIMUM_COMMANDS: u64 = 192;
pub const ADAPTER_MAXIMUM_INVOKE_ATTEMPTS: u64 = 28;
pub const ADAPTER_MAXIMUM_COMMANDS: u64 = 64;
pub const REQUIRED_ADAPTER_INVOKE_ATTEMPTS: u64 = 22;
pub const CASE_MANIFEST: &str = include_str!("../../../benchmarks/phase1/cases.json");

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct EvidenceError(pub &'static str);

impl std::fmt::Display for EvidenceError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(self.0)
    }
}

impl std::error::Error for EvidenceError {}

/// Canonical decimal strings retain full unsigned 64-bit precision in JSON.
pub mod decimal {
    use serde::{Deserialize, Deserializer, Serializer};

    pub fn serialize<S: Serializer>(value: &u64, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.serialize_str(&value.to_string())
    }

    pub fn deserialize<'de, D: Deserializer<'de>>(deserializer: D) -> Result<u64, D::Error> {
        let value = String::deserialize(deserializer)?;
        let parsed = value.parse::<u64>().map_err(serde::de::Error::custom)?;
        if value != parsed.to_string() {
            return Err(serde::de::Error::custom("noncanonical unsigned decimal"));
        }
        Ok(parsed)
    }
}

#[cfg(test)]
mod tests;
