//! Conformance harness, invariant probes, and deterministic test utilities.

#![forbid(unsafe_code)]

pub mod deterministic;

pub use deterministic::{block_on, DeterministicIds, ManualClock, TempWorkspace};

use std::sync::Arc;

use latent_activation::{ActivationEnvelope, ActivationOutcome};
use latent_core::{BoxFuture, Metadata, PlatformError, PlatformErrorCode};
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

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct IdleResourceSnapshot {
    pub process_count: u64,
    pub thread_count: u64,
    pub task_count: u64,
    pub timer_count: u64,
    pub socket_count: u64,
    pub connection_count: u64,
    pub exporter_count: u64,
    pub cell_count: u64,
    pub service_resident_resource_count: u64,
    pub resident_memory_bytes: u64,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct IdleScalingObservation {
    pub baseline_registered_releases: u64,
    pub registered_releases: u64,
    pub before: IdleResourceSnapshot,
    pub after: IdleResourceSnapshot,
    pub resources_unchanged: bool,
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

/// Driver for the before/after dormant-release scaling experiment.
///
/// Registering a dormant release must update bounded routing/catalog metadata
/// without starting a process, thread, socket, or service-owned execution host.
pub trait IdleScalingDriver: Send + Sync {
    fn registered_releases(&self) -> u64;

    fn register_dormant_releases<'a>(
        &'a self,
        count: u64,
    ) -> BoxFuture<'a, Result<(), PlatformError>>;

    fn route_lookup_p99_micros(&self) -> u64 {
        0
    }
}

pub trait InvariantProbe: Send + Sync {
    fn node_inventory<'a>(&'a self) -> BoxFuture<'a, Result<NodeInventory, PlatformError>>;

    fn idle_scaling<'a>(
        &'a self,
        releases_to_register: u64,
    ) -> BoxFuture<'a, Result<IdleScalingObservation, PlatformError>>;

    fn telemetry<'a>(&'a self) -> BoxFuture<'a, Result<Vec<MetricPoint>, PlatformError>>;
}

/// Concrete local probe used by CLI tests and invariant suites. It reads only a
/// bounded inventory snapshot and the bounded structured local telemetry sink;
/// it never walks a service or release catalog.
pub struct LocalInvariantProbe {
    inventory: Arc<dyn InventoryReporter>,
    telemetry: Arc<StructuredLocalSink>,
    idle_scaling: Option<Arc<dyn IdleScalingDriver>>,
}

impl std::fmt::Debug for LocalInvariantProbe {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("LocalInvariantProbe")
            .field("telemetry", &self.telemetry.snapshot())
            .field("idle_scaling_driver", &self.idle_scaling.is_some())
            .finish_non_exhaustive()
    }
}

impl LocalInvariantProbe {
    #[must_use]
    pub fn new(inventory: Arc<dyn InventoryReporter>, telemetry: Arc<StructuredLocalSink>) -> Self {
        Self {
            inventory,
            telemetry,
            idle_scaling: None,
        }
    }

    #[must_use]
    pub fn with_idle_scaling_driver(
        inventory: Arc<dyn InventoryReporter>,
        telemetry: Arc<StructuredLocalSink>,
        idle_scaling: Arc<dyn IdleScalingDriver>,
    ) -> Self {
        Self {
            inventory,
            telemetry,
            idle_scaling: Some(idle_scaling),
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
        releases_to_register: u64,
    ) -> BoxFuture<'a, Result<IdleScalingObservation, PlatformError>> {
        Box::pin(async move {
            let driver = self.idle_scaling.as_ref().ok_or_else(|| {
                probe_error(
                    PlatformErrorCode::Unavailable,
                    "idle-scaling experiment requires a release-registration driver",
                )
            })?;
            if releases_to_register == 0 {
                return Err(probe_error(
                    PlatformErrorCode::InvalidArgument,
                    "idle-scaling experiment must register at least one dormant release",
                ));
            }

            let before_inventory = self.inventory.snapshot().await?;
            let before = resource_snapshot(&before_inventory);
            let baseline_registered_releases = driver.registered_releases();
            driver
                .register_dormant_releases(releases_to_register)
                .await?;
            let expected = baseline_registered_releases
                .checked_add(releases_to_register)
                .ok_or_else(|| {
                    probe_error(
                        PlatformErrorCode::ResourceExhausted,
                        "registered release count overflowed",
                    )
                })?;
            let registered_releases = driver.registered_releases();
            if registered_releases != expected {
                return Err(probe_error(
                    PlatformErrorCode::StateConflict,
                    "idle-scaling driver did not register the requested dormant releases",
                ));
            }

            let after_inventory = self.inventory.snapshot().await?;
            let after = resource_snapshot(&after_inventory);
            Ok(IdleScalingObservation {
                baseline_registered_releases,
                registered_releases,
                before,
                after,
                resources_unchanged: before == after,
                route_lookup_p99_micros: driver.route_lookup_p99_micros(),
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

fn resource_snapshot(inventory: &NodeInventory) -> IdleResourceSnapshot {
    IdleResourceSnapshot {
        process_count: topology_count(inventory, "process"),
        thread_count: topology_count(inventory, "thread"),
        task_count: topology_count(inventory, "task"),
        timer_count: topology_count(inventory, "timer"),
        socket_count: topology_count(inventory, "socket"),
        connection_count: topology_count(inventory, "connection"),
        exporter_count: named_topology_count(inventory, "telemetry-exporter"),
        cell_count: inventory
            .cell_capacity
            .iter()
            .map(|capacity| u64::from(capacity.total))
            .sum(),
        service_resident_resource_count: inventory
            .topology
            .entries
            .iter()
            .filter(|entry| entry.ownership == ResourceOwnership::ServiceResident)
            .map(|entry| entry.active_count)
            .sum(),
        resident_memory_bytes: inventory.cache_summary.resident_bytes,
    }
}

fn topology_count(inventory: &NodeInventory, kind: &str) -> u64 {
    inventory
        .topology
        .entries
        .iter()
        .filter(|entry| entry.kind == kind)
        .map(|entry| entry.active_count)
        .sum()
}

fn named_topology_count(inventory: &NodeInventory, name: &str) -> u64 {
    inventory
        .topology
        .entries
        .iter()
        .filter(|entry| entry.name == name)
        .map(|entry| entry.active_count)
        .sum()
}

fn probe_error(code: PlatformErrorCode, message: &str) -> PlatformError {
    PlatformError {
        code,
        message: message.to_owned(),
        retryable: false,
        details: Vec::new(),
    }
}

#[cfg(test)]
mod tests {
    use std::sync::{Mutex, MutexGuard};

    use latent_core::{NodeId, RouteGeneration};
    use latent_node::{
        CellClassCapacity, HealthStatus, NodeCacheSummary, NodeDescriptor, NodeHealthObservation,
        NodePressureObservation, NodeResourceTopology,
    };
    use latent_telemetry::LocalSinkConfig;

    use super::*;

    struct FixedInventory(NodeInventory);

    impl InventoryReporter for FixedInventory {
        fn snapshot<'a>(&'a self) -> BoxFuture<'a, Result<NodeInventory, PlatformError>> {
            let inventory = self.0.clone();
            Box::pin(async move { Ok(inventory) })
        }
    }

    #[derive(Default)]
    struct CoupledDormantNode {
        releases: Mutex<Vec<String>>,
        leak_service_resources: bool,
    }

    impl CoupledDormantNode {
        fn inventory(&self) -> NodeInventory {
            let releases = u64::try_from(self.lock_releases().len()).unwrap_or(u64::MAX);
            let mut inventory = sample_inventory();
            inventory.route_generation = RouteGeneration(releases);
            inventory
                .node
                .attributes
                .insert("registered_releases".to_owned(), releases.to_string());
            if self.leak_service_resources && releases > 0 {
                inventory
                    .topology
                    .entries
                    .push(latent_node::NodeTopologyEntry {
                        name: "dormant-service-task".to_owned(),
                        kind: "task".to_owned(),
                        ownership: ResourceOwnership::ServiceResident,
                        configured_count: releases,
                        active_count: releases,
                        attributes: Metadata::new(),
                    });
            }
            inventory
        }

        fn lock_releases(&self) -> MutexGuard<'_, Vec<String>> {
            self.releases
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner)
        }
    }

    impl InventoryReporter for CoupledDormantNode {
        fn snapshot<'a>(&'a self) -> BoxFuture<'a, Result<NodeInventory, PlatformError>> {
            let inventory = self.inventory();
            Box::pin(async move { Ok(inventory) })
        }
    }

    impl IdleScalingDriver for CoupledDormantNode {
        fn registered_releases(&self) -> u64 {
            u64::try_from(self.lock_releases().len()).unwrap_or(u64::MAX)
        }

        fn register_dormant_releases<'a>(
            &'a self,
            count: u64,
        ) -> BoxFuture<'a, Result<(), PlatformError>> {
            let result = (|| {
                let mut releases = self.lock_releases();
                let baseline = u64::try_from(releases.len()).map_err(|_| {
                    probe_error(
                        PlatformErrorCode::ResourceExhausted,
                        "release catalog length does not fit u64",
                    )
                })?;
                let additional = usize::try_from(count).map_err(|_| {
                    probe_error(
                        PlatformErrorCode::ResourceExhausted,
                        "requested release count does not fit the host address size",
                    )
                })?;
                releases.try_reserve(additional).map_err(|_| {
                    probe_error(
                        PlatformErrorCode::ResourceExhausted,
                        "release catalog capacity could not be reserved",
                    )
                })?;
                for offset in 0..count {
                    let index = baseline.checked_add(offset).ok_or_else(|| {
                        probe_error(
                            PlatformErrorCode::ResourceExhausted,
                            "release identifier overflowed",
                        )
                    })?;
                    releases.push(format!("dormant-release-{index}"));
                }
                Ok(())
            })();
            Box::pin(async move { result })
        }

        fn route_lookup_p99_micros(&self) -> u64 {
            7
        }
    }

    #[tokio::test]
    async fn idle_scaling_performs_a_coupled_before_after_registration() {
        let node = Arc::new(CoupledDormantNode::default());
        let inventory: Arc<dyn InventoryReporter> = node.clone();
        let driver: Arc<dyn IdleScalingDriver> = node.clone();
        let telemetry = Arc::new(
            StructuredLocalSink::new(LocalSinkConfig::default()).expect("valid local sink"),
        );
        let probe = LocalInvariantProbe::with_idle_scaling_driver(inventory, telemetry, driver);

        let observation = probe.idle_scaling(10_000).await.expect("experiment");
        assert_eq!(observation.baseline_registered_releases, 0);
        assert_eq!(observation.registered_releases, 10_000);
        assert_eq!(node.lock_releases().len(), 10_000);
        assert!(observation.resources_unchanged);
        assert_eq!(observation.before, observation.after);
        assert_eq!(observation.route_lookup_p99_micros, 7);
        let after = node.inventory();
        assert_eq!(after.route_generation, RouteGeneration(10_000));
        assert_eq!(
            after
                .node
                .attributes
                .get("registered_releases")
                .map(String::as_str),
            Some("10000")
        );
    }

    #[tokio::test]
    async fn idle_scaling_detects_service_resident_resource_growth() {
        let node = Arc::new(CoupledDormantNode {
            releases: Mutex::new(Vec::new()),
            leak_service_resources: true,
        });
        let inventory: Arc<dyn InventoryReporter> = node.clone();
        let driver: Arc<dyn IdleScalingDriver> = node;
        let telemetry = Arc::new(
            StructuredLocalSink::new(LocalSinkConfig::default()).expect("valid local sink"),
        );
        let probe = LocalInvariantProbe::with_idle_scaling_driver(inventory, telemetry, driver);

        let observation = probe.idle_scaling(10).await.expect("experiment");
        assert!(!observation.resources_unchanged);
        assert_eq!(observation.before.service_resident_resource_count, 0);
        assert_eq!(observation.after.service_resident_resource_count, 10);
        assert_eq!(observation.after.task_count, 10);
    }

    #[tokio::test]
    async fn idle_scaling_without_a_driver_fails_instead_of_copying_input() {
        let inventory = Arc::new(FixedInventory(sample_inventory()));
        let telemetry = Arc::new(
            StructuredLocalSink::new(LocalSinkConfig::default()).expect("valid local sink"),
        );
        let probe = LocalInvariantProbe::new(inventory, telemetry);
        let error = probe.idle_scaling(10).await.expect_err("missing driver");
        assert_eq!(error.code, PlatformErrorCode::Unavailable);
    }

    fn sample_inventory() -> NodeInventory {
        NodeInventory {
            node: NodeDescriptor {
                id: NodeId("node-test".to_owned()),
                architecture: "test".to_owned(),
                operating_system: "test".to_owned(),
                cpu_features: Vec::new(),
                trust_classes: Vec::new(),
                region: None,
                zone: None,
                endpoint: "local://test".to_owned(),
                identity: "test".to_owned(),
                attributes: Metadata::new(),
            },
            cell_capacity: vec![CellClassCapacity {
                class: "standard".to_owned(),
                total: 2,
                available: 2,
                active: 0,
                quarantined: 0,
                queue_depth: 0,
            }],
            memory_pressure_milli: 0,
            queue_depth: 0,
            route_generation: RouteGeneration(1),
            cache_entries: Vec::new(),
            observed_at_unix_millis: 1,
            cache_summary: NodeCacheSummary::default(),
            pressure: NodePressureObservation::default(),
            health: NodeHealthObservation {
                status: HealthStatus::Healthy,
                ready: true,
                healthy: true,
                reasons: Vec::new(),
                observed_at_unix_millis: 1,
            },
            topology: NodeResourceTopology::default(),
        }
    }
}
