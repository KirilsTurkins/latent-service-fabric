//! Conformance harness, invariant probes, and deterministic test utilities.

#![forbid(unsafe_code)]

pub mod deterministic;

pub use deterministic::{block_on, DeterministicIds, ManualClock, TempWorkspace};

use std::sync::Arc;

use latent_activation::{ActivationEnvelope, ActivationOutcome};
use latent_core::{BoxFuture, Metadata, PlatformError};
use latent_executor::ExecutionBackend;
use latent_node::{InventoryReporter, NodeInventory, ResourceOwnership};
use latent_telemetry::{MetricPoint, StructuredLocalSink, TelemetryRecord};

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

    fn invoke<'a>(&'a self, envelope: ActivationEnvelope) -> BoxFuture<'a, ActivationOutcome>;
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

/// Concrete local probe used by CLI tests and invariant suites. It reads only a
/// bounded inventory snapshot and the bounded structured local telemetry sink;
/// it never walks a service or release catalog.
pub struct LocalInvariantProbe {
    inventory: Arc<dyn InventoryReporter>,
    telemetry: Arc<StructuredLocalSink>,
}

impl std::fmt::Debug for LocalInvariantProbe {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("LocalInvariantProbe")
            .field("telemetry", &self.telemetry.snapshot())
            .finish_non_exhaustive()
    }
}

impl LocalInvariantProbe {
    #[must_use]
    pub fn new(inventory: Arc<dyn InventoryReporter>, telemetry: Arc<StructuredLocalSink>) -> Self {
        Self {
            inventory,
            telemetry,
        }
    }

    #[must_use]
    pub fn telemetry_records(&self) -> Vec<TelemetryRecord> {
        self.telemetry.records()
    }
}

impl InvariantProbe for LocalInvariantProbe {
    fn node_inventory<'a>(&'a self) -> BoxFuture<'a, Result<NodeInventory, PlatformError>> {
        self.inventory.snapshot()
    }

    fn idle_scaling<'a>(
        &'a self,
        registered_releases: u64,
    ) -> BoxFuture<'a, Result<IdleScalingObservation, PlatformError>> {
        Box::pin(async move {
            let inventory = self.inventory.snapshot().await?;
            let process_count = topology_count(&inventory, "process");
            let thread_count = topology_count(&inventory, "thread");
            let socket_count = topology_count(&inventory, "socket");
            let cell_count = inventory
                .cell_capacity
                .iter()
                .map(|capacity| u64::from(capacity.total))
                .sum();
            Ok(IdleScalingObservation {
                registered_releases,
                process_count,
                thread_count,
                socket_count,
                cell_count,
                resident_memory_bytes: inventory.cache_summary.resident_bytes,
                // Route lookup latency is supplied by the routing benchmark,
                // not inferred from an inventory scan.
                route_lookup_p99_micros: 0,
            })
        })
    }

    fn telemetry<'a>(&'a self) -> BoxFuture<'a, Result<Vec<MetricPoint>, PlatformError>> {
        let metrics = self
            .telemetry
            .records()
            .into_iter()
            .filter_map(|record| match record {
                TelemetryRecord::Metric(point) => Some(point),
                TelemetryRecord::Log(_) | TelemetryRecord::Span(_) => None,
            })
            .collect();
        Box::pin(async move { Ok(metrics) })
    }
}

fn topology_count(inventory: &NodeInventory, kind: &str) -> u64 {
    inventory
        .topology
        .entries
        .iter()
        .filter(|entry| {
            entry.kind == kind
                && matches!(
                    entry.ownership,
                    ResourceOwnership::NodeFixed | ResourceOwnership::ActivationScoped
                )
        })
        .map(|entry| entry.active_count)
        .sum()
}
