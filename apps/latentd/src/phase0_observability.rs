//! Shared bounded telemetry and live node inventory for the retained Phase 0 node.
//!
//! The composition deliberately owns one exporter worker for the node. Runtime,
//! cell, cache, and activation state are read from retained live sources; no
//! service catalog is scanned and no dormant service receives resident state.

#![allow(clippy::cast_precision_loss)]

use std::sync::{Arc, Mutex, MutexGuard};
use std::time::{SystemTime, UNIX_EPOCH};

use latent_activation::ActivationManager;
use latent_core::{
    ActivationId, Metadata, NodeId, PlatformError, PlatformErrorCode, RouteGeneration,
};
use latent_node::{
    CacheInventorySource, GuestLogSource, HealthStatus, InventoryReporter, MemoryPressureSource,
    NodeCacheSummary, NodeDescriptor, NodeHealthObservation, NodeHealthSource,
    NodePressureObservation, NodeResourceTopology, NodeTopologyEntry, NodeTopologySource,
    ObservedActivationManager, ObservedCellPool, ObservedExecutionBackend, ResourceOwnership,
    RouteGenerationSource, StandaloneInventoryConfig, StandaloneInventoryReporter,
    StaticRouteGenerationSource,
};
use latent_scheduler::{CellClass, CellPool, FixedCellPool};
use latent_telemetry::{
    ActivationObserver, GuestLogObserver, GuestLogRecord, LocalSinkConfig, LogSeverity, MetricKind,
    MetricPoint, SharedActivationObserver, SharedActivationObserverConfig, StructuredLocalSink,
    TelemetryHandle, TelemetryPipelineConfig, TelemetryPipelineSnapshot, TelemetryRuntime,
};
use latent_wasmtime::{
    BoundedLogSink, CapturedLog, Phase0WasmtimeBackend, PreparedCacheSnapshot,
    RuntimeResourceSnapshot,
};

use crate::phase0_composition::Phase0RuntimeWorkerMonitor;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Phase0ObservabilityConfig {
    pub telemetry: TelemetryPipelineConfig,
    pub local_sink: LocalSinkConfig,
    pub maximum_cache_descriptors: usize,
    pub maximum_topology_entries: usize,
    pub route_generation: RouteGeneration,
    pub runtime_worker_capacity: usize,
    pub pool_queue_capacity: u32,
}

impl Default for Phase0ObservabilityConfig {
    fn default() -> Self {
        Self {
            telemetry: TelemetryPipelineConfig::default(),
            local_sink: LocalSinkConfig::default(),
            maximum_cache_descriptors: 8,
            maximum_topology_entries: 64,
            route_generation: RouteGeneration(0),
            runtime_worker_capacity: 1,
            pool_queue_capacity: 16,
        }
    }
}

pub struct Phase0NodeObservability {
    local_sink: Arc<StructuredLocalSink>,
    telemetry: TelemetryHandle,
    observer: Arc<SharedActivationObserver>,
    inventory: Arc<StandaloneInventoryReporter>,
    routes: Arc<StaticRouteGenerationSource>,
    observed_pool: Arc<ObservedCellPool<FixedCellPool>>,
    observed_backend: Arc<ObservedExecutionBackend<Phase0WasmtimeBackend>>,
    guest_logs: Arc<Phase0GuestLogSource>,
    backend: Arc<Phase0WasmtimeBackend>,
    runtime: Mutex<Option<TelemetryRuntime>>,
}

impl std::fmt::Debug for Phase0NodeObservability {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("Phase0NodeObservability")
            .field("telemetry", &self.telemetry.snapshot())
            .field("observer", &self.observer.snapshot())
            .field("local_sink", &self.local_sink.snapshot())
            .field("route_generation", &self.routes.current_generation())
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
    ) -> Result<Arc<Self>, PlatformError> {
        if config.maximum_cache_descriptors == 0
            || config.maximum_topology_entries == 0
            || config.runtime_worker_capacity == 0
            || config.pool_queue_capacity == 0
        {
            return Err(phase0_observability_error(
                PlatformErrorCode::InvalidArgument,
                "Phase 0 observability bounds must be non-zero",
            ));
        }
        let local_sink = Arc::new(StructuredLocalSink::new(config.local_sink)?);
        let sink: Arc<dyn latent_telemetry::TelemetrySink> = local_sink.clone();
        let (telemetry, runtime) = TelemetryRuntime::spawn(config.telemetry, sink)?;
        let observer = Arc::new(SharedActivationObserver::new(
            telemetry.clone(),
            SharedActivationObserverConfig::default(),
        )?);

        let activation_observer: Arc<dyn ActivationObserver> = observer.clone();
        let observed_pool = Arc::new(ObservedCellPool::new(
            pool.clone(),
            activation_observer.clone(),
            telemetry.clone(),
        ));
        let observed_backend = Arc::new(ObservedExecutionBackend::new(
            backend.clone(),
            activation_observer,
            telemetry.clone(),
        ));
        let guest_logs = Arc::new(Phase0GuestLogSource {
            sink: backend.log_sink(),
        });
        let routes = Arc::new(StaticRouteGenerationSource::new(config.route_generation));

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
        let pressure: Arc<dyn MemoryPressureSource> = Arc::new(Phase0LivePressureSource {
            pool: pool.clone(),
            backend: backend.clone(),
            telemetry: telemetry.clone(),
            pool_queue_capacity: config.pool_queue_capacity,
        });
        let health: Arc<dyn NodeHealthSource> = Arc::new(Phase0LiveHealthSource {
            pool: pool.clone(),
            telemetry: telemetry.clone(),
        });
        let fixed_topology: Arc<dyn NodeTopologySource> = Arc::new(Phase0FixedTopologySource {
            pool,
            workers,
            telemetry: telemetry.clone(),
            configured_runtime_workers: config.runtime_worker_capacity,
        });
        let dynamic_topology: Arc<dyn NodeTopologySource> =
            Arc::new(Phase0ActivationTopologySource {
                backend: backend.clone(),
            });
        let pool_source: Arc<dyn CellPool> = observed_pool.clone();
        let route_source: Arc<dyn latent_node::RouteGenerationSource> = routes.clone();
        let inventory = Arc::new(StandaloneInventoryReporter::new_with_topology_sources(
            StandaloneInventoryConfig {
                cell_classes: vec![CellClass::Standard],
                maximum_cache_descriptors: config.maximum_cache_descriptors,
                maximum_topology_entries: config.maximum_topology_entries,
            },
            descriptor,
            pool_source,
            route_source,
            cache,
            pressure,
            health,
            fixed_topology,
            dynamic_topology,
        )?);

        let observability = Arc::new(Self {
            local_sink,
            telemetry,
            observer,
            inventory,
            routes,
            observed_pool,
            observed_backend,
            guest_logs,
            backend,
            runtime: Mutex::new(Some(runtime)),
        });
        observability.emit_inventory_metrics()?;
        Ok(observability)
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
    pub fn observed_pool(&self) -> Arc<ObservedCellPool<FixedCellPool>> {
        self.observed_pool.clone()
    }

    #[must_use]
    pub fn observed_backend(&self) -> Arc<ObservedExecutionBackend<Phase0WasmtimeBackend>> {
        self.observed_backend.clone()
    }

    #[must_use]
    pub fn observe_manager<M>(&self, manager: Arc<M>) -> Arc<ObservedActivationManager<M>>
    where
        M: ActivationManager + 'static,
    {
        let activation_observer: Arc<dyn ActivationObserver> = self.observer.clone();
        let guest_log_observer: Arc<dyn GuestLogObserver> = self.observer.clone();
        let guest_logs: Arc<dyn GuestLogSource> = self.guest_logs.clone();
        Arc::new(ObservedActivationManager::with_guest_logs(
            manager,
            activation_observer,
            guest_log_observer,
            guest_logs,
        ))
    }

    #[must_use]
    pub fn local_sink(&self) -> Arc<StructuredLocalSink> {
        self.local_sink.clone()
    }

    #[must_use]
    pub fn inventory_reporter(&self) -> Arc<StandaloneInventoryReporter> {
        self.inventory.clone()
    }

    pub fn set_route_generation(&self, generation: RouteGeneration) -> Result<(), PlatformError> {
        self.routes.set(generation);
        emit_metric(
            &self.telemetry,
            "latent.route.generation",
            MetricKind::Gauge,
            generation.0 as f64,
            "1",
            Metadata::new(),
            now_unix_millis(),
        )
    }

    pub async fn inventory(&self) -> Result<latent_node::NodeInventory, PlatformError> {
        self.emit_inventory_metrics()?;
        self.inventory.snapshot().await
    }

    pub async fn flush(&self) -> Result<(), PlatformError> {
        self.telemetry.flush().await
    }

    pub async fn shutdown(&self) -> Result<(), PlatformError> {
        let flush_result = self.telemetry.flush().await;
        let runtime = self.take_runtime();
        let shutdown_result = match runtime {
            Some(runtime) => runtime.shutdown().await,
            None => Ok(()),
        };
        flush_result.and(shutdown_result)
    }

    pub fn abort(&self) {
        if let Some(runtime) = self.take_runtime() {
            runtime.abort();
        }
    }

    fn emit_inventory_metrics(&self) -> Result<(), PlatformError> {
        let points = inventory_metric_points(
            self.routes.current_generation(),
            &self.backend.cache_snapshot(),
            self.telemetry.snapshot(),
            now_unix_millis(),
        );
        let mut first_error = None;
        for point in points {
            collect_error(
                &mut first_error,
                self.telemetry.try_emit_metric(point).map(|_| ()),
            );
        }
        first_error.map_or(Ok(()), Err)
    }

    fn take_runtime(&self) -> Option<TelemetryRuntime> {
        self.lock_runtime().take()
    }

    fn lock_runtime(&self) -> MutexGuard<'_, Option<TelemetryRuntime>> {
        self.runtime
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
    }
}

impl Drop for Phase0NodeObservability {
    fn drop(&mut self) {
        let runtime = self
            .runtime
            .get_mut()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .take();
        if let Some(runtime) = runtime {
            runtime.abort();
        }
    }
}

#[derive(Debug)]
struct Phase0GuestLogSource {
    sink: BoundedLogSink,
}

impl GuestLogSource for Phase0GuestLogSource {
    fn snapshot_for(&self, activation_id: &ActivationId) -> Vec<GuestLogRecord> {
        let observed_at_unix_millis = now_unix_millis();
        self.sink
            .snapshot_for(activation_id)
            .into_iter()
            .map(|record| guest_log_record(record, observed_at_unix_millis))
            .collect()
    }
}

fn guest_log_record(record: CapturedLog, observed_at_unix_millis: u64) -> GuestLogRecord {
    GuestLogRecord {
        activation_id: record.activation_id,
        severity: severity(&record.level),
        body: record.message,
        fields: record.fields,
        observed_at_unix_millis,
    }
}

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
            hits,
            misses,
            evictions,
        } = self.backend.cache_snapshot();
        NodeCacheSummary {
            entries: usize_to_u64(entries),
            resident_bytes: usize_to_u64(source_bytes),
            maximum_entries: usize_to_u64(maximum_entries),
            maximum_bytes: usize_to_u64(maximum_source_bytes),
            hits,
            misses,
            evictions,
            descriptors: Vec::new(),
        }
    }
}

struct Phase0LivePressureSource {
    pool: Arc<FixedCellPool>,
    backend: Arc<Phase0WasmtimeBackend>,
    telemetry: TelemetryHandle,
    pool_queue_capacity: u32,
}

impl MemoryPressureSource for Phase0LivePressureSource {
    fn pressure(&self) -> NodePressureObservation {
        let pool = self.pool.observations();
        let cache = self.backend.cache_snapshot();
        let telemetry = self.telemetry.snapshot();
        let cache_entry_pressure = ratio_milli(cache.entries, cache.maximum_entries);
        let cache_byte_pressure = ratio_milli(cache.source_bytes, cache.maximum_source_bytes);
        NodePressureObservation {
            // Phase 0 has no process-wide resident-memory sampler. The bounded
            // node-owned prepared-cache byte occupancy is the live memory
            // pressure signal that this composition can measure accurately.
            memory_pressure_milli: cache_byte_pressure,
            queue_pressure_milli: ratio_milli(
                usize::try_from(pool.queue_depth).unwrap_or(usize::MAX),
                usize::try_from(self.pool_queue_capacity).unwrap_or(usize::MAX),
            ),
            cache_pressure_milli: cache_entry_pressure.max(cache_byte_pressure),
            telemetry_pressure_milli: ratio_milli(telemetry.queue_depth, telemetry.queue_capacity),
        }
    }
}

#[derive(Debug)]
struct Phase0LiveHealthSource {
    pool: Arc<FixedCellPool>,
    telemetry: TelemetryHandle,
}

impl NodeHealthSource for Phase0LiveHealthSource {
    fn health(&self) -> NodeHealthObservation {
        let pool = self.pool.observations();
        let telemetry = self.telemetry.snapshot();
        let dropped = telemetry
            .dropped_queue_full
            .saturating_add(telemetry.dropped_queue_closed)
            .saturating_add(telemetry.dropped_invalid_record);
        let all_cells_quarantined = pool.capacity > 0 && pool.quarantined >= pool.capacity;
        let worker_closed = self.telemetry.is_closed();

        let (status, ready, healthy, reasons) = if worker_closed {
            (
                HealthStatus::Unhealthy,
                false,
                false,
                vec!["telemetry-worker-closed".to_owned()],
            )
        } else if all_cells_quarantined {
            (
                HealthStatus::Unhealthy,
                false,
                false,
                vec!["all-execution-cells-quarantined".to_owned()],
            )
        } else {
            let mut reasons = Vec::new();
            if pool.quarantined > 0 {
                reasons.push("execution-cell-quarantined".to_owned());
            }
            if dropped > 0 {
                reasons.push("telemetry-records-dropped".to_owned());
            }
            if telemetry.sink_failures > 0 {
                reasons.push("telemetry-sink-failure".to_owned());
            }
            let status = if reasons.is_empty() {
                HealthStatus::Healthy
            } else {
                HealthStatus::Degraded
            };
            (status, true, true, reasons)
        };

        NodeHealthObservation {
            status,
            ready,
            healthy,
            reasons,
            observed_at_unix_millis: now_unix_millis(),
        }
    }
}

#[derive(Debug)]
struct Phase0FixedTopologySource {
    pool: Arc<FixedCellPool>,
    workers: Phase0RuntimeWorkerMonitor,
    telemetry: TelemetryHandle,
    configured_runtime_workers: usize,
}

impl NodeTopologySource for Phase0FixedTopologySource {
    fn topology(&self) -> NodeResourceTopology {
        self.bounded_topology(usize::MAX)
    }

    fn bounded_topology(&self, maximum_entries: usize) -> NodeResourceTopology {
        let active_workers = usize_to_u64(self.workers.active_workers());
        let entries = [
            NodeTopologyEntry {
                name: "latentd-process".to_owned(),
                kind: "process".to_owned(),
                ownership: ResourceOwnership::NodeFixed,
                configured_count: 1,
                active_count: 1,
                attributes: Metadata::from([("scope".to_owned(), "node".to_owned())]),
            },
            NodeTopologyEntry {
                name: "tokio-runtime-workers".to_owned(),
                kind: "thread".to_owned(),
                ownership: ResourceOwnership::NodeFixed,
                configured_count: usize_to_u64(self.configured_runtime_workers),
                active_count: active_workers,
                attributes: Metadata::from([("scope".to_owned(), "node".to_owned())]),
            },
            NodeTopologyEntry {
                name: "telemetry-exporter".to_owned(),
                kind: "task".to_owned(),
                ownership: ResourceOwnership::NodeFixed,
                configured_count: 1,
                active_count: u64::from(!self.telemetry.is_closed()),
                attributes: Metadata::from([("scope".to_owned(), "node".to_owned())]),
            },
            NodeTopologyEntry {
                name: "generic-execution-cells".to_owned(),
                kind: "execution-host".to_owned(),
                ownership: ResourceOwnership::NodeFixed,
                configured_count: u64::from(self.pool.capacity(CellClass::Standard)),
                active_count: u64::from(self.pool.capacity(CellClass::Standard)),
                attributes: Metadata::from([
                    ("scope".to_owned(), "node".to_owned()),
                    ("service_specific".to_owned(), "false".to_owned()),
                ]),
            },
        ]
        .into_iter()
        .take(maximum_entries)
        .collect();
        NodeResourceTopology { entries }
    }
}

struct Phase0ActivationTopologySource {
    backend: Arc<Phase0WasmtimeBackend>,
}

impl NodeTopologySource for Phase0ActivationTopologySource {
    fn topology(&self) -> NodeResourceTopology {
        self.bounded_topology(usize::MAX)
    }

    fn bounded_topology(&self, maximum_entries: usize) -> NodeResourceTopology {
        let RuntimeResourceSnapshot {
            active_invocations,
            live_stores,
            live_host_states,
            live_component_instances,
            live_temporary_buffers,
            live_cancellation_probes,
            stores_created: _,
        } = self.backend.resource_snapshot();
        let entries = [
            activation_resource("active-invocations", "execution", active_invocations),
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
        ]
        .into_iter()
        .take(maximum_entries)
        .collect();
        NodeResourceTopology { entries }
    }
}

fn activation_resource(name: &str, kind: &str, active_count: u64) -> NodeTopologyEntry {
    NodeTopologyEntry {
        name: name.to_owned(),
        kind: kind.to_owned(),
        ownership: ResourceOwnership::ActivationScoped,
        configured_count: 0,
        active_count,
        attributes: Metadata::from([("scope".to_owned(), "activation".to_owned())]),
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

fn inventory_metric_points(
    generation: RouteGeneration,
    cache: &PreparedCacheSnapshot,
    telemetry: TelemetryPipelineSnapshot,
    observed_at_unix_millis: u64,
) -> Vec<MetricPoint> {
    [
        (
            "latent.route.generation",
            MetricKind::Gauge,
            generation.0 as f64,
            "1",
        ),
        (
            "latent.cache.entries",
            MetricKind::Gauge,
            cache.entries as f64,
            "1",
        ),
        (
            "latent.cache.resident_bytes",
            MetricKind::Gauge,
            cache.source_bytes as f64,
            "By",
        ),
        (
            "latent.cache.hits",
            MetricKind::Counter,
            cache.hits as f64,
            "1",
        ),
        (
            "latent.cache.misses",
            MetricKind::Counter,
            cache.misses as f64,
            "1",
        ),
        (
            "latent.cache.evictions",
            MetricKind::Counter,
            cache.evictions as f64,
            "1",
        ),
        (
            "latent.telemetry.queue.depth",
            MetricKind::Gauge,
            telemetry.queue_depth as f64,
            "1",
        ),
        (
            "latent.telemetry.queue.capacity",
            MetricKind::Gauge,
            telemetry.queue_capacity as f64,
            "1",
        ),
        (
            "latent.telemetry.accepted.total",
            MetricKind::Counter,
            telemetry.accepted as f64,
            "1",
        ),
        (
            "latent.telemetry.exported.total",
            MetricKind::Counter,
            telemetry.exported as f64,
            "1",
        ),
        (
            "latent.telemetry.dropped.queue_full.total",
            MetricKind::Counter,
            telemetry.dropped_queue_full as f64,
            "1",
        ),
        (
            "latent.telemetry.dropped.queue_closed.total",
            MetricKind::Counter,
            telemetry.dropped_queue_closed as f64,
            "1",
        ),
        (
            "latent.telemetry.dropped.invalid_record.total",
            MetricKind::Counter,
            telemetry.dropped_invalid_record as f64,
            "1",
        ),
        (
            "latent.telemetry.sink_failures.total",
            MetricKind::Counter,
            telemetry.sink_failures as f64,
            "1",
        ),
    ]
    .into_iter()
    .map(|(name, kind, value, unit)| MetricPoint {
        name: name.to_owned(),
        kind,
        value,
        unit: unit.to_owned(),
        attributes: Metadata::new(),
        observed_at_unix_millis,
    })
    .collect()
}

fn emit_metric(
    telemetry: &TelemetryHandle,
    name: &str,
    kind: MetricKind,
    value: f64,
    unit: &str,
    attributes: Metadata,
    observed_at_unix_millis: u64,
) -> Result<(), PlatformError> {
    telemetry
        .try_emit_metric(MetricPoint {
            name: name.to_owned(),
            kind,
            value,
            unit: unit.to_owned(),
            attributes,
            observed_at_unix_millis,
        })
        .map(|_| ())
}

fn collect_error(first_error: &mut Option<PlatformError>, result: Result<(), PlatformError>) {
    if first_error.is_none() {
        *first_error = result.err();
    }
}

fn ratio_milli(numerator: usize, denominator: usize) -> u32 {
    if denominator == 0 {
        return 0;
    }
    let value = numerator.saturating_mul(1_000) / denominator;
    u32::try_from(value.min(1_000)).unwrap_or(1_000)
}

fn usize_to_u64(value: usize) -> u64 {
    u64::try_from(value).unwrap_or(u64::MAX)
}

fn now_unix_millis() -> u64 {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis();
    u64::try_from(millis).unwrap_or(u64::MAX)
}

fn phase0_observability_error(code: PlatformErrorCode, message: &str) -> PlatformError {
    PlatformError {
        code,
        message: message.to_owned(),
        retryable: false,
        details: Vec::new(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn route_and_cache_behavior_metrics_have_explicit_types_and_live_values() {
        let points = inventory_metric_points(
            RouteGeneration(42),
            &PreparedCacheSnapshot {
                entries: 3,
                source_bytes: 512,
                maximum_entries: 8,
                maximum_source_bytes: 4_096,
                hits: 11,
                misses: 7,
                evictions: 2,
            },
            TelemetryPipelineSnapshot {
                queue_capacity: 16,
                queue_depth: 4,
                accepted: 23,
                exported: 19,
                dropped_queue_full: 3,
                dropped_queue_closed: 0,
                dropped_invalid_record: 1,
                sink_failures: 0,
            },
            99,
        );

        assert_eq!(
            metric(&points, "latent.route.generation").kind,
            MetricKind::Gauge
        );
        assert_eq!(
            metric(&points, "latent.route.generation").value.to_bits(),
            42.0_f64.to_bits()
        );
        assert_eq!(
            metric(&points, "latent.cache.hits").kind,
            MetricKind::Counter
        );
        assert_eq!(
            metric(&points, "latent.cache.hits").value.to_bits(),
            11.0_f64.to_bits()
        );
        assert_eq!(
            metric(&points, "latent.cache.misses").value.to_bits(),
            7.0_f64.to_bits()
        );
        assert_eq!(
            metric(&points, "latent.cache.evictions").value.to_bits(),
            2.0_f64.to_bits()
        );
        assert_eq!(
            metric(&points, "latent.telemetry.queue.depth")
                .value
                .to_bits(),
            4.0_f64.to_bits()
        );
        assert!(points
            .iter()
            .all(|point| point.observed_at_unix_millis == 99));
    }

    fn metric<'a>(points: &'a [MetricPoint], name: &str) -> &'a MetricPoint {
        points
            .iter()
            .find(|point| point.name == name)
            .expect("metric must be emitted")
    }

    #[test]
    fn pressure_is_bounded_and_zero_capacity_is_not_reported_as_saturation() {
        assert_eq!(ratio_milli(5, 10), 500);
        assert_eq!(ratio_milli(10, 1), 1_000);
        assert_eq!(ratio_milli(1, 0), 0);
    }
}
