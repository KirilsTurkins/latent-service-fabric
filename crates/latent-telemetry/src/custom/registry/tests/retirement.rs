use super::*;
use crate::{LogRecord, SpanRecord, TelemetrySink};
use latent_core::{BoxFuture, PlatformError};
use std::sync::atomic::AtomicUsize;
use tokio::sync::Notify;

struct Gate {
    entered: Notify,
    live: AtomicUsize,
}
struct Live<'a>(&'a AtomicUsize);
impl Drop for Live<'_> {
    fn drop(&mut self) {
        self.0.fetch_sub(1, Ordering::AcqRel);
    }
}
impl TelemetrySink for Gate {
    fn emit_custom_metric(
        &self,
        _point: CustomMetricPoint,
    ) -> BoxFuture<'_, Result<(), PlatformError>> {
        self.live.fetch_add(1, Ordering::AcqRel);
        let live = Live(&self.live);
        Box::pin(async move {
            let _live = live;
            self.entered.notify_one();
            std::future::pending().await
        })
    }
    fn emit_metric(&self, _: MetricPoint) -> BoxFuture<'_, Result<(), PlatformError>> {
        Box::pin(std::future::ready(Ok(())))
    }
    fn emit_log(&self, _: LogRecord) -> BoxFuture<'_, Result<(), PlatformError>> {
        Box::pin(std::future::ready(Ok(())))
    }
    fn emit_span(&self, _: SpanRecord) -> BoxFuture<'_, Result<(), PlatformError>> {
        Box::pin(std::future::ready(Ok(())))
    }
}
#[tokio::test]
async fn blocked_export_keeps_node_and_tenant_bytes_until_actual_abort_cleanup() {
    let gate = Arc::new(Gate {
        entered: Notify::new(),
        live: AtomicUsize::new(0),
    });
    let (handle, runtime) = TelemetryRuntime::spawn(
        TelemetryPipelineConfig {
            queue_capacity: 1,
            export_timeout: Duration::from_secs(10),
            ..Default::default()
        },
        gate.clone(),
    )
    .unwrap();
    let mut c = config();
    c.limits.maximum_queued_bytes = 2 * RECORD_BYTES;
    c.limits.maximum_queued_bytes_per_tenant = RECORD_BYTES;
    let registry = CustomMetricRegistry::install(handle.clone(), c, Clock::new()).unwrap();
    let metric = input(MetricKind::Counter, 1.0, &[]);
    assert_eq!(registry.try_emit(source("a"), metric), Ok(true));
    gate.entered.notified().await;
    assert_eq!(
        registry.try_emit(source("a"), metric),
        Err(E::BudgetExhausted)
    );
    assert_eq!(registry.try_emit(source("b"), metric), Ok(true));
    assert_eq!(
        registry.try_emit(source("b"), metric),
        Err(E::BudgetExhausted)
    );
    let before = registry.snapshot().unwrap();
    assert_eq!(before.queued_bytes, 2 * RECORD_BYTES);
    assert_eq!(
        &before.tenant_queued_bytes[..2],
        &[RECORD_BYTES, RECORD_BYTES]
    );
    assert_eq!(before.active_series, 2);
    assert_eq!(before.accepted, 2);
    registry.retire();
    assert_eq!(registry.try_emit(source("a"), metric), Err(E::Unavailable));
    assert_eq!(registry.snapshot().unwrap().queued_bytes, 2 * RECORD_BYTES);
    drop(runtime);
    tokio::time::timeout(Duration::from_secs(1), async {
        while registry.snapshot().unwrap().queued_bytes != 0 {
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();
    assert_eq!(gate.live.load(Ordering::Acquire), 0);
    assert!(handle.is_closed());
    assert_eq!(registry.snapshot().unwrap().accepted, 2);
}
struct Unsupported;
impl TelemetrySink for Unsupported {
    fn emit_metric(&self, _: MetricPoint) -> BoxFuture<'_, Result<(), PlatformError>> {
        Box::pin(std::future::ready(Ok(())))
    }
    fn emit_log(&self, _: LogRecord) -> BoxFuture<'_, Result<(), PlatformError>> {
        Box::pin(std::future::ready(Ok(())))
    }
    fn emit_span(&self, _: SpanRecord) -> BoxFuture<'_, Result<(), PlatformError>> {
        Box::pin(std::future::ready(Ok(())))
    }
}
#[tokio::test]
async fn unsupported_custom_export_is_reported_without_claiming_durability_or_refunding_acceptance()
{
    let (handle, runtime) =
        TelemetryRuntime::spawn(TelemetryPipelineConfig::default(), Arc::new(Unsupported)).unwrap();
    let registry = CustomMetricRegistry::install(handle.clone(), config(), Clock::new()).unwrap();
    assert_eq!(
        registry.try_emit(source("a"), input(MetricKind::Counter, 1.0, &[])),
        Ok(true)
    );
    handle.flush().await.unwrap();
    assert_eq!(handle.snapshot().accepted, 1);
    assert_eq!(handle.snapshot().exported, 0);
    assert_eq!(handle.snapshot().sink_failures, 1);
    assert_eq!(registry.snapshot().unwrap().queued_bytes, 0);
    assert_eq!(registry.snapshot().unwrap().accepted, 1);
    runtime.shutdown().await.unwrap();
    assert_eq!(
        registry.try_emit(source("a"), input(MetricKind::Counter, 1.0, &[])),
        Err(E::Unavailable)
    );
}
#[tokio::test]
async fn validated_custom_path_does_not_relax_the_original_runtime_dimension_allowlist() {
    let (registry, sink, handle, runtime, _) = fixture(config());
    let attrs = vec![("region".into(), "east".into())];
    registry
        .try_emit(source("a"), input(MetricKind::Counter, 1.0, &attrs))
        .unwrap();
    let spoof = MetricPoint {
        name: "latent.test".into(),
        kind: MetricKind::Counter,
        value: 1.0,
        unit: "1".into(),
        attributes: Metadata::from([("latent.tenant".into(), "spoofed".into())]),
        observed_at_unix_millis: 0,
    };
    assert_eq!(handle.try_emit_metric(spoof), Ok(false));
    handle.flush().await.unwrap();
    assert_eq!(handle.snapshot().dropped_invalid_record, 1);
    assert_eq!(sink.records().len(), 1);
    let TelemetryRecord::CustomMetric(point) = &sink.records()[0] else {
        panic!("custom point")
    };
    assert_eq!(
        point.point().attributes.get("guest.region").unwrap(),
        "east"
    );
    runtime.shutdown().await.unwrap();
}
