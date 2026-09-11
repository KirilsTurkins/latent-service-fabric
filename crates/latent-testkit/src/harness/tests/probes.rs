use std::sync::atomic::{AtomicUsize, Ordering};

use latent_core::{BoxFuture, Metadata, NodeId, PlatformError, PlatformErrorCode, RouteGeneration};
use latent_node::{
    HealthStatus, InventoryReporter, NodeCacheSummary, NodeDescriptor, NodeHealthObservation,
    NodeInventory, NodePressureObservation, NodeResourceTopology,
};
use latent_telemetry::{
    LocalSinkConfig, LogRecord, LogSeverity, MetricKind, MetricPoint, StructuredLocalSink,
    TelemetrySink,
};

use crate::harness::{IdleScalingMeasurement, ObservedInvariantProbe};
use crate::{block_on, IdleScalingObservation, InvariantProbe};

struct Reporter {
    calls: AtomicUsize,
    value: Result<NodeInventory, PlatformError>,
}
impl InventoryReporter for Reporter {
    fn snapshot(&self) -> BoxFuture<'_, Result<NodeInventory, PlatformError>> {
        self.calls.fetch_add(1, Ordering::Relaxed);
        Box::pin(std::future::ready(self.value.clone()))
    }
}

fn inventory() -> NodeInventory {
    NodeInventory {
        node: NodeDescriptor {
            id: NodeId("measured-node".to_owned()),
            architecture: "test".to_owned(),
            operating_system: "test".to_owned(),
            cpu_features: Vec::new(),
            trust_classes: Vec::new(),
            region: None,
            zone: None,
            endpoint: "local".to_owned(),
            identity: "node".to_owned(),
            attributes: Metadata::new(),
        },
        cell_capacity: Vec::new(),
        memory_pressure_milli: 17,
        queue_depth: 2,
        route_generation: RouteGeneration(42),
        cache_entries: Vec::new(),
        observed_at_unix_millis: 123,
        cache_summary: NodeCacheSummary::default(),
        pressure: NodePressureObservation::default(),
        health: NodeHealthObservation {
            status: HealthStatus::Degraded,
            ready: false,
            healthy: true,
            reasons: vec!["measured".to_owned()],
            observed_at_unix_millis: 123,
        },
        topology: NodeResourceTopology::default(),
        quotas: None,
        retained_bytes: 1024,
    }
}

#[test]
fn inventory_is_delegated_without_reconstructing_or_hiding_source_failures() {
    let sink = StructuredLocalSink::new(LocalSinkConfig::default()).unwrap();
    let reporter = Reporter {
        calls: AtomicUsize::new(0),
        value: Ok(inventory()),
    };
    let probe = ObservedInvariantProbe::new(&reporter, &sink, None).unwrap();
    assert_eq!(block_on(probe.node_inventory()).unwrap(), inventory());
    assert_eq!(reporter.calls.load(Ordering::Relaxed), 1);
    let reporter = Reporter {
        calls: AtomicUsize::new(0),
        value: Err(super::super::error(
            PlatformErrorCode::Unavailable,
            "real-source-unavailable",
        )),
    };
    let probe = ObservedInvariantProbe::new(&reporter, &sink, None).unwrap();
    assert_eq!(
        block_on(probe.node_inventory()).unwrap_err().message,
        "real-source-unavailable"
    );
}

#[test]
fn telemetry_returns_actual_metrics_and_rejects_large_source_maxima_even_when_empty() {
    let reporter = Reporter {
        calls: AtomicUsize::new(0),
        value: Ok(inventory()),
    };
    let sink = StructuredLocalSink::new(LocalSinkConfig {
        maximum_entries: 4,
        maximum_bytes: 16 * 1024,
    })
    .unwrap();
    let point = MetricPoint {
        name: "actual.metric".to_owned(),
        kind: MetricKind::Counter,
        value: 7.0,
        unit: "count".to_owned(),
        attributes: Metadata::new(),
        observed_at_unix_millis: 123,
    };
    block_on(sink.emit_metric(point.clone())).unwrap();
    block_on(sink.emit_log(LogRecord {
        severity: LogSeverity::Info,
        body: "private log".to_owned(),
        trace: None,
        attributes: Metadata::new(),
        observed_at_unix_millis: 123,
    }))
    .unwrap();
    assert_eq!(sink.snapshot().entries, 2);
    assert_eq!(sink.snapshot().evicted_entries, 0);
    let probe = ObservedInvariantProbe::new(&reporter, &sink, None).unwrap();
    assert_eq!(block_on(probe.telemetry()).unwrap(), [point]);
    let large = StructuredLocalSink::new(LocalSinkConfig {
        maximum_entries: 4097,
        maximum_bytes: 8192,
    })
    .unwrap();
    assert!(ObservedInvariantProbe::new(&reporter, &large, None).is_err());
    assert_eq!(large.snapshot().entries, 0);
}

struct Measured(IdleScalingObservation);
impl IdleScalingMeasurement for Measured {
    fn observation(&self, _: u64) -> BoxFuture<'_, Result<IdleScalingObservation, PlatformError>> {
        Box::pin(std::future::ready(Ok(self.0.clone())))
    }
}

#[test]
fn idle_scaling_requires_explicit_measurement_and_exact_release_count() {
    let reporter = Reporter {
        calls: AtomicUsize::new(0),
        value: Ok(inventory()),
    };
    let sink = StructuredLocalSink::new(LocalSinkConfig::default()).unwrap();
    let probe = ObservedInvariantProbe::new(&reporter, &sink, None).unwrap();
    let error = block_on(probe.idle_scaling(4)).unwrap_err();
    assert_eq!(error.code, PlatformErrorCode::IncompatibleContract);
    assert_eq!(
        error.message,
        "idle-scaling-requires-measured-route-latency-evidence"
    );
    let source = Measured(IdleScalingObservation {
        registered_releases: 4,
        process_count: 1,
        thread_count: 3,
        socket_count: 2,
        cell_count: 1,
        resident_memory_bytes: 8192,
        route_lookup_p99_micros: 9,
    });
    let probe = ObservedInvariantProbe::new(&reporter, &sink, Some(&source)).unwrap();
    assert_eq!(block_on(probe.idle_scaling(4)).unwrap(), source.0);
    assert_eq!(
        block_on(probe.idle_scaling(3)).unwrap_err().message,
        "invalid-idle-scaling-measurement"
    );
}
