use std::future::poll_fn;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use std::task::Poll;
use std::time::Duration;

use latent_admission::{NodeLoadSnapshot, NodeLoadSource};
use latent_artifacts::{CacheEntryDescriptor, CacheTier};
use latent_core::{
    ActivationClock, ActivationId, ClockSample, Metadata, PlatformError, ReleaseDigest,
    RouteGeneration,
};
use latent_scheduler::{
    ActivationScheduler, AdmittedSchedulingRequest, CellClass, SchedulerSnapshot,
};

use super::*;

mod limits;
mod support;
use support::{node, Fixture};

fn reporter(fixture: &Fixture) -> StandaloneInventoryReporter {
    StandaloneInventoryReporter::new(
        StandaloneInventoryConfig::default(),
        node(),
        fixture.sources(),
    )
    .expect("reporter")
}

#[tokio::test]
async fn actual_scheduler_queue_cell_quarantine_and_quota_refunds_are_observed() {
    let fixture = Fixture::new();
    let reporter = reporter(&fixture);
    let cancellations = crate::ActivationCancellationRegistry::new(64).expect("registry");
    let first = cancellations
        .register(ActivationId("first".to_owned()))
        .expect("first");
    let second = cancellations
        .register(ActivationId("second".to_owned()))
        .expect("second");
    let held = fixture
        .scheduler
        .enqueue(AdmittedSchedulingRequest {
            permit: fixture.admit("first"),
            cancellation: Arc::new(first.handle()),
        })
        .await
        .expect("one cell");
    let mut queued = fixture.scheduler.enqueue(AdmittedSchedulingRequest {
        permit: fixture.admit("second"),
        cancellation: Arc::new(second.handle()),
    });
    assert!(poll_fn(|cx| Poll::Ready(queued.as_mut().poll(cx).is_pending())).await);
    let inventory = reporter.snapshot().await.expect("queued inventory");
    let cell = inventory
        .cell_capacity
        .iter()
        .find(|cell| cell.class == "standard")
        .expect("standard");
    assert_eq!(
        (
            cell.total,
            cell.available,
            cell.active,
            cell.queue_depth,
            cell.queue_capacity
        ),
        (1, 0, 1, 1, 2)
    );
    assert_eq!(
        inventory.queue_depth, 1,
        "the pool's disabled FIFO is not the scheduler queue"
    );
    assert_eq!(
        inventory.quotas.expect("quotas").usage.active_activations,
        2
    );
    assert_eq!(
        inventory.quotas.expect("quotas").usage.queued_activations,
        1
    );
    assert!(
        inventory.health.ready,
        "busy cells still accept bounded queued work"
    );
    drop(queued);
    held.quarantine("test quarantine".to_owned())
        .await
        .expect("quarantine");
    let inventory = reporter.snapshot_now().expect("reclaimed inventory");
    let cell = &inventory.cell_capacity[2];
    assert_eq!(
        (cell.total, cell.active, cell.queue_depth, cell.quarantined),
        (1, 0, 0, 1)
    );
    assert_eq!(
        inventory.quotas.expect("quotas").usage.active_activations,
        0
    );
    assert_eq!(inventory.quotas.expect("quotas").retained_tenants, 0);
    assert!(!inventory.health.ready);
    assert!(!inventory.health.healthy);
    assert!(inventory
        .health
        .reasons
        .iter()
        .any(|reason| reason == "no-usable-execution-cells"));
}

#[tokio::test]
async fn zero_queue_capacity_and_shutdown_are_unready_without_hiding_fixed_cells() {
    for queue_capacity in [0, 2] {
        let fixture = Fixture::with_queue_capacity(queue_capacity);
        let reporter = reporter(&fixture);
        let initial = reporter.snapshot_now().expect("configured inventory");
        assert_eq!(initial.health.ready, queue_capacity != 0);
        assert_eq!(initial.cell_capacity[2].accepting, queue_capacity != 0);
        if queue_capacity == 0 {
            let cancellations = crate::ActivationCancellationRegistry::new(64).expect("registry");
            let registration = cancellations
                .register(ActivationId("denied".to_owned()))
                .expect("registration");
            let result = fixture
                .scheduler
                .enqueue(AdmittedSchedulingRequest {
                    permit: fixture.admit("denied"),
                    cancellation: Arc::new(registration.handle()),
                })
                .await;
            assert!(
                result.is_err(),
                "zero queue capacity rejects even idle dispatch"
            );
        }
        fixture.scheduler.shutdown();
        let shutdown = reporter.snapshot_now().expect("shutdown inventory");
        assert!(!shutdown.health.ready);
        assert!(
            shutdown.health.healthy,
            "deliberate shutdown is not a broken cell"
        );
        assert!(!shutdown.cell_capacity[2].accepting);
        assert_eq!(shutdown.cell_capacity[2].total, 1);
        assert_eq!(shutdown.cell_capacity[2].available, 1);
        assert_eq!(shutdown.cell_capacity[2].queue_capacity, queue_capacity);
        assert!(shutdown
            .health
            .reasons
            .iter()
            .any(|reason| reason == "scheduler-not-accepting"));
    }
}

#[test]
fn load_health_uses_monotonic_age_and_explicit_unavailability() {
    let fixture = Fixture::new();
    let reporter = reporter(&fixture);
    let initial = reporter.snapshot_now().expect("healthy");
    assert!(initial.health.ready);
    assert_eq!(initial.pressure.memory_pressure_milli, 200);
    let initial_sample = fixture.clock.sample();
    *fixture.clock.0.lock().expect("clock") =
        ClockSample::new(1, initial_sample.monotonic() + Duration::from_secs(6));
    let stale = reporter.snapshot_now().expect("stale diagnostic");
    assert!(!stale.pressure.load_available);
    assert!(!stale.health.ready);
    assert!(stale
        .health
        .reasons
        .iter()
        .any(|reason| reason == "load-not-current"));
    let mut sources = fixture.sources();
    sources.load = Arc::new(Unavailable);
    let unavailable =
        StandaloneInventoryReporter::new(StandaloneInventoryConfig::default(), node(), sources)
            .expect("reporter")
            .snapshot_now()
            .expect("unavailable diagnostic");
    assert!(!unavailable.health.healthy);
    assert_eq!(unavailable.pressure.load_sample_age_millis, None);
    assert!(unavailable
        .health
        .reasons
        .iter()
        .any(|reason| reason == "load-unavailable"));
}

struct Unavailable;
impl NodeLoadSource for Unavailable {
    fn snapshot(&self) -> Result<NodeLoadSnapshot, PlatformError> {
        Err(invalid("sensitive external diagnostic is not copied"))
    }
}

#[test]
fn fixed_class_collection_and_live_generation_never_inspect_dormant_catalog_rows() {
    struct Classes(AtomicUsize);
    impl SchedulerInventorySource for Classes {
        fn snapshot(&self, class: CellClass) -> Result<SchedulerInventorySnapshot, PlatformError> {
            self.0.fetch_add(1, Ordering::Relaxed);
            let count = match class {
                CellClass::Tiny => 1,
                CellClass::Small => 2,
                CellClass::Standard => 3,
                CellClass::Large => 4,
                CellClass::ExtraLarge => 5,
            };
            Ok(SchedulerInventorySnapshot {
                queue_capacity: count,
                observations: SchedulerSnapshot {
                    accepting: true,
                    capacity: count,
                    available: count,
                    ..SchedulerSnapshot::default()
                },
            })
        }
    }
    let fixture = Fixture::new();
    let classes = Arc::new(Classes(AtomicUsize::new(0)));
    let mut sources = fixture.sources();
    sources.scheduler = classes.clone();
    let reporter =
        StandaloneInventoryReporter::new(StandaloneInventoryConfig::default(), node(), sources)
            .expect("reporter");
    let first = reporter.snapshot_now().expect("first");
    assert_eq!(
        first
            .cell_capacity
            .iter()
            .map(|cell| cell.total)
            .collect::<Vec<_>>(),
        [1, 2, 3, 4, 5]
    );
    fixture.routes.generation.store(100_000, Ordering::Relaxed);
    let second = reporter
        .snapshot_now()
        .expect("changed generation, no catalog allocation");
    assert_eq!(second.route_generation, RouteGeneration(100_000));
    assert_eq!(classes.0.load(Ordering::Relaxed), 10);
    assert_eq!(fixture.routes.reads.load(Ordering::Relaxed), 2);
    assert_eq!(first.retained_bytes, second.retained_bytes);
}

struct Cache;
fn cache_summary() -> NodeCacheSummary {
    NodeCacheSummary {
        available: true,
        entries: 3,
        maximum_entries: 8,
        source_bytes: 40,
        maximum_source_bytes: 100,
        metadata_bytes: 30,
        maximum_metadata_bytes: 60,
        compiled_image_bytes: 20,
        maximum_compiled_image_bytes: 80,
        preparing: 2,
        maximum_concurrent_preparations: 4,
        preparing_source_bytes: 100,
        preparing_metadata_bytes: 60,
        hits: 19,
        misses: 13,
        evictions: 7,
        invalidations: 5,
    }
}
impl CacheInventorySource for Cache {
    fn snapshot(&self, writer: &mut CacheInventoryWriter<'_>) -> Result<(), PlatformError> {
        writer.set_summary(cache_summary())?;
        writer.push_descriptor(&descriptor())?;
        Ok(())
    }
}
fn descriptor() -> CacheEntryDescriptor {
    CacheEntryDescriptor {
        key: "private-cache-key".to_owned(),
        release_digest: ReleaseDigest("private-release".to_owned()),
        tier: CacheTier::ImportsPrepared,
        size_bytes: 40,
        last_access_unix_millis: 7,
    }
}

#[test]
fn cache_dimensions_and_fixed_metric_labels_preserve_their_meaning() {
    let fixture = Fixture::new();
    let mut sources = fixture.sources();
    sources.cache = Arc::new(Cache);
    let inventory =
        StandaloneInventoryReporter::new(StandaloneInventoryConfig::default(), node(), sources)
            .expect("reporter")
            .snapshot_now()
            .expect("inventory");
    assert_eq!(inventory.cache_summary, cache_summary());
    assert_eq!(inventory.cache_entries, [descriptor()]);
    assert_eq!(inventory.pressure.cache_pressure_milli, 500);
    assert_eq!(
        inventory.memory_pressure_milli, 200,
        "memory pressure comes from the trusted load sample"
    );
    let metrics = inventory.metric_points();
    assert!(metrics.len() <= 128);
    for point in &metrics {
        assert!(point.attributes.keys().all(|key| key == "cell_class"));
        assert!(point.attributes.values().all(|value| [
            "tiny",
            "small",
            "standard",
            "large",
            "extra-large"
        ]
        .contains(&value.as_str())));
    }
    let invalidations = metrics
        .iter()
        .find(|point| point.name == "latent.cache.invalidations")
        .expect("explicit invalidation counter");
    assert_eq!(invalidations.kind, latent_telemetry::MetricKind::Counter);
    assert_eq!(invalidations.value.to_bits(), 5.0_f64.to_bits());
    let serialized = format!("{metrics:?}");
    assert!(!serialized.contains("private-cache-key"));
    assert!(!serialized.contains("private-release"));
    assert!(!serialized.contains("inventory-node"));
}

#[tokio::test]
async fn inventory_metrics_pass_the_shared_pipeline_dimension_allowlist() {
    use latent_telemetry::{
        LocalSinkConfig, StructuredLocalSink, TelemetryPipelineConfig, TelemetryRuntime,
    };

    let fixture = Fixture::new();
    let points = reporter(&fixture)
        .snapshot_now()
        .expect("inventory")
        .metric_points();
    let expected = u64::try_from(points.len()).expect("bounded metric count");
    let sink = Arc::new(StructuredLocalSink::new(LocalSinkConfig::default()).expect("sink"));
    let (handle, runtime) = TelemetryRuntime::spawn(
        TelemetryPipelineConfig {
            queue_capacity: 128,
            ..TelemetryPipelineConfig::default()
        },
        sink,
    )
    .expect("pipeline");
    for point in points {
        assert!(handle.try_emit_metric(point).expect("metric submission"));
    }
    handle.flush().await.expect("bounded flush");
    assert_eq!(handle.snapshot().exported, expected);
    assert_eq!(handle.snapshot().dropped_invalid_record, 0);
    runtime.shutdown().await.expect("bounded shutdown");
}
