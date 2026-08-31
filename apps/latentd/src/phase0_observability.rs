use std::sync::Arc;
use std::time::{SystemTime, UNIX_EPOCH};

use latent_activation::{ActivationEnvelope, ActivationOutcome};
use latent_core::{Metadata, NodeId, PlatformError, RouteGeneration};
use latent_node::{
    CacheInventorySource, HealthStatus, InventoryReporter, MutableNodeHealthSource,
    NodeCacheSummary, NodeDescriptor, NodeHealthObservation, NodePressureObservation,
    NodeResourceTopology, NodeTopologyEntry, NodeTopologySource, ResourceOwnership,
    StandaloneInventoryConfig, StandaloneInventoryReporter, StaticMemoryPressureSource,
    StaticRouteGenerationSource,
};
use latent_scheduler::{CellClass, CellPool, FixedCellPool};
use latent_telemetry::{
    ActivationObserver, GuestLogObserver, GuestLogRecord, LocalSinkConfig, LogSeverity,
    SharedActivationObserver, SharedActivationObserverConfig, StructuredLocalSink, TelemetryHandle,
    TelemetryPipelineConfig, TelemetryRuntime,
};
use latent_wasmtime::{
    CapturedLog, Phase0WasmtimeBackend, PreparedCacheSnapshot, RuntimeResourceSnapshot,
    ECHO_DOMAIN_ERROR_MEDIA_TYPE,
};

use crate::phase0_composition::Phase0RuntimeWorkerMonitor;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Phase0ObservabilityConfig {
    pub telemetry: TelemetryPipelineConfig,
    pub local_sink: LocalSinkConfig,
    pub maximum_cache_descriptors: usize,
    pub maximum_topology_entries: usize,
    pub route_generation: RouteGeneration,
}

impl Default for Phase0ObservabilityConfig {
    fn default() -> Self {
        Self {
            telemetry: TelemetryPipelineConfig::default(),
            local_sink: LocalSinkConfig::default(),
            maximum_cache_descriptors: 8,
            maximum_topology_entries: 64,
            route_generation: RouteGeneration(0),
        }
    }
}

pub struct Phase0NodeObservability {
    local_sink: Arc<StructuredLocalSink>,
    telemetry: TelemetryHandle,
    observer: Arc<SharedActivationObserver>,
    inventory: Arc<StandaloneInventoryReporter>,
    runtime: Option<TelemetryRuntime>,
}

impl std::fmt::Debug for Phase0NodeObservability {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("Phase0NodeObservability")
            .field("telemetry", &self.telemetry.snapshot())
            .field("observer", &self.observer.snapshot())
            .field("local_sink", &self.local_sink.snapshot())
            .finish_non_exhaustive()
    }
}

impl Phase0NodeObservability {
    pub fn start(
        config: Phase0ObservabilityConfig,
        node_id: NodeId,
        pool: Arc<FixedCellPool>,
        backend: Arc<Phase0WasmtimeBackend>,
        workers: Phase0RuntimeWorkerMonitor,
    ) -> Result<Self, PlatformError> {
        let local_sink = Arc::new(StructuredLocalSink::new(config.local_sink)?);
        let sink: Arc<dyn latent_telemetry::TelemetrySink> = local_sink.clone();
        let (telemetry, runtime) = TelemetryRuntime::spawn(config.telemetry, sink)?;
        let observer = Arc::new(SharedActivationObserver::new(
            telemetry.clone(),
            SharedActivationObserverConfig {
                domain_error_media_types: vec![ECHO_DOMAIN_ERROR_MEDIA_TYPE.to_owned()],
                ..SharedActivationObserverConfig::default()
            },
        )?);
        let descriptor = NodeDescriptor {
            id: node_id,
            architecture: std::env::consts::ARCH.to_owned(),
            operating_system: std::env::consts::OS.to_owned(),
            cpu_features: Vec::new(),
            trust_classes: vec!["phase0-local".to_owned()],
            region: None,
            zone: None,
            endpoint: "local://latentd-phase0".to_owned(),
            identity: "phase0-local-node".to_owned(),
            attributes: Metadata::from([
                ("phase".to_owned(), "0".to_owned()),
                ("production_ready".to_owned(), "false".to_owned()),
            ]),
        };
        let cache: Arc<dyn CacheInventorySource> = Arc::new(Phase0CacheInventorySource {
            backend: backend.clone(),
        });
        let dynamic_topology: Arc<dyn NodeTopologySource> = Arc::new(Phase0TopologySource {
            backend,
            workers: workers.clone(),
        });
        let routes = Arc::new(StaticRouteGenerationSource::new(config.route_generation));
        let pressure = Arc::new(StaticMemoryPressureSource::new(
            NodePressureObservation::default(),
        ));
        let health = Arc::new(MutableNodeHealthSource::new(NodeHealthObservation {
            status: HealthStatus::Healthy,
            ready: true,
            healthy: true,
            reasons: Vec::new(),
            observed_at_unix_millis: now_unix_millis(),
        }));
        let fixed_topology = fixed_topology(&pool, &workers);
        let pool_source: Arc<dyn CellPool> = pool;
        let inventory = Arc::new(StandaloneInventoryReporter::new(
            StandaloneInventoryConfig {
                cell_classes: vec![CellClass::Standard],
                maximum_cache_descriptors: config.maximum_cache_descriptors,
                maximum_topology_entries: config.maximum_topology_entries,
            },
            descriptor,
            pool_source,
            routes,
            cache,
            pressure,
            health,
            fixed_topology,
            dynamic_topology,
        )?);
        Ok(Self {
            local_sink,
            telemetry,
            observer,
            inventory,
            runtime: Some(runtime),
        })
    }

    #[must_use]
    pub fn telemetry(&self) -> TelemetryHandle {
        self.telemetry.clone()
    }

    #[must_use]
    pub fn observer(&self) -> Arc<SharedActivationObserver> {
        self.observer.clone()
    }

    #[must_use]
    pub fn local_sink(&self) -> Arc<StructuredLocalSink> {
        self.local_sink.clone()
    }

    #[must_use]
    pub fn inventory_reporter(&self) -> Arc<StandaloneInventoryReporter> {
        self.inventory.clone()
    }

    pub fn on_received(&self, envelope: &ActivationEnvelope) {
        self.observer.on_received(envelope);
    }

    pub fn forward_guest_logs(&self, logs: &[CapturedLog]) {
        let observed_at = now_unix_millis();
        for log in logs {
            self.observer.on_guest_log(GuestLogRecord {
                activation_id: log.activation_id.clone(),
                severity: severity(&log.level),
                body: log.message.clone(),
                fields: log.fields.clone(),
                observed_at_unix_millis: observed_at,
            });
        }
    }

    pub fn on_completed(&self, envelope: &ActivationEnvelope, outcome: &ActivationOutcome) {
        self.observer.on_completed(envelope, outcome);
    }

    pub async fn inventory(&self) -> Result<latent_node::NodeInventory, PlatformError> {
        self.inventory.snapshot().await
    }

    pub async fn flush(&self) -> Result<(), PlatformError> {
        self.telemetry.flush().await
    }

    pub async fn shutdown(mut self) -> Result<(), PlatformError> {
        self.telemetry.flush().await?;
        if let Some(runtime) = self.runtime.take() {
            runtime.shutdown().await?;
        }
        Ok(())
    }

    pub fn abort(mut self) {
        if let Some(runtime) = self.runtime.take() {
            runtime.abort();
        }
    }
}

#[derive(Debug)]
struct Phase0CacheInventorySource {
    backend: Arc<Phase0WasmtimeBackend>,
}

impl CacheInventorySource for Phase0CacheInventorySource {
    fn snapshot(&self, _maximum_descriptors: usize) -> NodeCacheSummary {
        let PreparedCacheSnapshot {
            entries,
            source_bytes,
            maximum_entries,
            maximum_source_bytes,
        } = self.backend.cache_snapshot();
        NodeCacheSummary {
            entries: u64::try_from(entries).unwrap_or(u64::MAX),
            resident_bytes: u64::try_from(source_bytes).unwrap_or(u64::MAX),
            maximum_entries: u64::try_from(maximum_entries).unwrap_or(u64::MAX),
            maximum_bytes: u64::try_from(maximum_source_bytes).unwrap_or(u64::MAX),
            hits: 0,
            misses: 0,
            evictions: 0,
            descriptors: Vec::new(),
        }
    }
}

#[derive(Debug)]
struct Phase0TopologySource {
    backend: Arc<Phase0WasmtimeBackend>,
    workers: Phase0RuntimeWorkerMonitor,
}

impl NodeTopologySource for Phase0TopologySource {
    fn topology(&self) -> NodeResourceTopology {
        let RuntimeResourceSnapshot {
            active_invocations,
            live_stores,
            live_host_states,
            live_component_instances,
            live_temporary_buffers,
            live_cancellation_probes,
            stores_created: _,
        } = self.backend.resource_snapshot();
        NodeResourceTopology {
            entries: vec![
                activation_resource("active-invocations", "execution-host", active_invocations),
                activation_resource("wasmtime-stores", "runtime-store", live_stores),
                activation_resource("host-states", "host-state", live_host_states),
                activation_resource(
                    "component-instances",
                    "component-instance",
                    live_component_instances,
                ),
                activation_resource("temporary-buffers", "memory-buffer", live_temporary_buffers),
                activation_resource(
                    "cancellation-probes",
                    "cancellation-probe",
                    live_cancellation_probes,
                ),
                NodeTopologyEntry {
                    name: "runtime-workers-observed".to_owned(),
                    kind: "thread".to_owned(),
                    ownership: ResourceOwnership::NodeFixed,
                    configured_count: u64::try_from(self.workers.active_workers())
                        .unwrap_or(u64::MAX),
                    active_count: u64::try_from(self.workers.active_workers()).unwrap_or(u64::MAX),
                    attributes: Metadata::new(),
                },
            ],
        }
    }
}

fn fixed_topology(
    pool: &FixedCellPool,
    workers: &Phase0RuntimeWorkerMonitor,
) -> NodeResourceTopology {
    NodeResourceTopology {
        entries: vec![
            NodeTopologyEntry {
                name: "tokio-runtime-workers".to_owned(),
                kind: "thread".to_owned(),
                ownership: ResourceOwnership::NodeFixed,
                configured_count: u64::try_from(workers.active_workers()).unwrap_or(u64::MAX),
                active_count: u64::try_from(workers.active_workers()).unwrap_or(u64::MAX),
                attributes: Metadata::new(),
            },
            NodeTopologyEntry {
                name: "telemetry-exporter".to_owned(),
                kind: "task".to_owned(),
                ownership: ResourceOwnership::NodeFixed,
                configured_count: 1,
                active_count: 1,
                attributes: Metadata::from([("scope".to_owned(), "node".to_owned())]),
            },
            NodeTopologyEntry {
                name: "wasmtime-epoch-helper".to_owned(),
                kind: "thread".to_owned(),
                ownership: ResourceOwnership::NodeFixed,
                configured_count: 1,
                active_count: 1,
                attributes: Metadata::from([("scope".to_owned(), "node".to_owned())]),
            },
            NodeTopologyEntry {
                name: "generic-execution-cells".to_owned(),
                kind: "execution-host".to_owned(),
                ownership: ResourceOwnership::NodeFixed,
                configured_count: u64::from(pool.capacity(CellClass::Standard)),
                active_count: u64::from(
                    pool.capacity(CellClass::Standard)
                        .saturating_sub(pool.available(CellClass::Standard)),
                ),
                attributes: Metadata::from([("service_specific".to_owned(), "false".to_owned())]),
            },
            NodeTopologyEntry {
                name: "dormant-service-processes".to_owned(),
                kind: "process".to_owned(),
                ownership: ResourceOwnership::ServiceResident,
                configured_count: 0,
                active_count: 0,
                attributes: Metadata::new(),
            },
            NodeTopologyEntry {
                name: "dormant-service-threads".to_owned(),
                kind: "thread".to_owned(),
                ownership: ResourceOwnership::ServiceResident,
                configured_count: 0,
                active_count: 0,
                attributes: Metadata::new(),
            },
            NodeTopologyEntry {
                name: "dormant-service-sockets".to_owned(),
                kind: "socket".to_owned(),
                ownership: ResourceOwnership::ServiceResident,
                configured_count: 0,
                active_count: 0,
                attributes: Metadata::new(),
            },
        ],
    }
}

fn activation_resource(name: &str, kind: &str, active_count: u64) -> NodeTopologyEntry {
    NodeTopologyEntry {
        name: name.to_owned(),
        kind: kind.to_owned(),
        ownership: ResourceOwnership::ActivationScoped,
        configured_count: 0,
        active_count,
        attributes: Metadata::new(),
    }
}

fn severity(level: &str) -> LogSeverity {
    match level {
        "trace" => LogSeverity::Trace,
        "debug" => LogSeverity::Debug,
        "warn" => LogSeverity::Warn,
        "error" => LogSeverity::Error,
        _ => LogSeverity::Info,
    }
}

fn now_unix_millis() -> u64 {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis();
    u64::try_from(millis).unwrap_or(u64::MAX)
}
