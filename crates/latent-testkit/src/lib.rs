//! Conformance harness, invariant probes, and deterministic test utilities.

#![forbid(unsafe_code)]

pub mod deterministic;

pub use deterministic::{block_on, DeterministicIds, ManualClock, TempWorkspace};

use latent_activation::{ActivationEnvelope, ActivationOutcome};
use latent_core::{BoxFuture, Metadata, PlatformError};
use latent_executor::ExecutionBackend;
use latent_node::NodeInventory;
use latent_telemetry::MetricPoint;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ConformanceCase {
    pub id: String,
    pub description: String,
    pub tags: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ConformanceResult {
    pub case: ConformanceCase,
    pub passed: bool,
    pub diagnostics: Vec<String>,
    pub attributes: Metadata,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct IdleScalingObservation {
    pub registered_releases: u64,
    pub process_count: u64,
    pub thread_count: u64,
    pub socket_count: u64,
    pub cell_count: u64,
    pub resident_memory_bytes: u64,
    pub route_lookup_p99_micros: u64,
}

pub trait BackendHarness: Send + Sync {
    fn backend(&self) -> &dyn ExecutionBackend;

    fn invoke<'a>(
        &'a self,
        envelope: ActivationEnvelope,
    ) -> BoxFuture<'a, ActivationOutcome>;
}

pub trait ConformanceSuite: Send + Sync {
    fn cases(&self) -> Vec<ConformanceCase>;

    fn run<'a>(
        &'a self,
        harness: &'a dyn BackendHarness,
        case: &'a ConformanceCase,
    ) -> BoxFuture<'a, ConformanceResult>;
}

pub trait InvariantProbe: Send + Sync {
    fn node_inventory<'a>(&'a self) -> BoxFuture<'a, Result<NodeInventory, PlatformError>>;

    fn idle_scaling<'a>(
        &'a self,
        registered_releases: u64,
    ) -> BoxFuture<'a, Result<IdleScalingObservation, PlatformError>>;

    fn telemetry<'a>(&'a self) -> BoxFuture<'a, Result<Vec<MetricPoint>, PlatformError>>;
}
