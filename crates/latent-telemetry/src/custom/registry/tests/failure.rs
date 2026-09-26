use super::*;
use crate::{LogRecord, SpanRecord, TelemetrySink};
use latent_core::{BoxFuture, PlatformError};
use std::sync::atomic::AtomicUsize;
struct Failing(AtomicUsize);
impl TelemetrySink for Failing {
    fn emit_custom_metric(&self, _: CustomMetricPoint) -> BoxFuture<'_, Result<(), PlatformError>> {
        match self.0.fetch_add(1, Ordering::AcqRel) {
            0 => panic!("test exporter construction panic"),
            1 => Box::pin(std::future::pending()),
            _ => Box::pin(std::future::ready(Ok(()))),
        }
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
async fn custom_export_panic_and_timeout_release_original_charges_and_worker_continues() {
    let (handle, runtime) = TelemetryRuntime::spawn(
        TelemetryPipelineConfig {
            export_timeout: Duration::from_millis(1),
            ..Default::default()
        },
        Arc::new(Failing(AtomicUsize::new(0))),
    )
    .unwrap();
    let mut c = config();
    c.limits.maximum_queued_bytes_per_tenant = RECORD_BYTES;
    let registry = CustomMetricRegistry::install(handle.clone(), c, Clock::new()).unwrap();
    for _ in 0..3 {
        assert_eq!(
            registry.try_emit(source("a"), input(MetricKind::Counter, 1.0, &[])),
            Ok(true)
        );
        handle.flush().await.unwrap();
        assert_eq!(registry.snapshot().unwrap().queued_bytes, 0);
    }
    let snapshot = handle.snapshot();
    assert_eq!(snapshot.accepted, 3);
    assert_eq!(snapshot.exported, 1);
    assert_eq!(snapshot.sink_failures, 1);
    assert_eq!(snapshot.worker_panics, 1);
    assert_eq!(snapshot.sink_timeouts, 1);
    assert_eq!(registry.snapshot().unwrap().accepted, 3);
    runtime.shutdown().await.unwrap();
}
