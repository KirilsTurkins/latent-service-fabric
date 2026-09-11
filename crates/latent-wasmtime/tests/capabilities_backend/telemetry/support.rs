use super::super::support::*;
use latent_core::{ActivationClock, BoxFuture, Metadata, PlatformError};
use latent_telemetry::{
    ActivationObservation, ActivationObservationContext, ActivationObservationKind,
    ActivationObservationToken, ActivationObserver, LocalSinkConfig, LogRecord, MetricKind,
    MetricPoint, SharedActivationObserver, SharedActivationObserverConfig, SpanRecord,
    StructuredLocalSink, TelemetryHandle, TelemetryPipelineConfig, TelemetryRuntime, TelemetrySink,
};
use latent_wasmtime::WasmtimeConfig;
use serde_json::{json, Value};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::Notify;

pub const MESSAGE: &str = "private guest body";
pub fn fields() -> Value {
    json!([{"name":"allowed","value":"visible"}, {"name":"discard","value":"private"}])
}
pub fn capture_config() -> WasmtimeConfig {
    WasmtimeConfig {
        retained_log_maximum_entries: 1,
        ..config()
    }
}
fn expected_bytes(cancellation: &Cancellation) -> u64 {
    let id = &cancellation.id.0;
    u64::try_from(
        serde_json::to_vec(
            &json!({"activation_id": id, "level": "info", "message": MESSAGE,
        "fields": {"allowed":"visible", "discard":"private", "latent.activation_id":id,
            "latent.trace_id":"trace-pinned", "latent.span_id":"span-pinned"}}),
        )
        .unwrap()
        .len(),
    )
    .unwrap()
}
pub fn assert_writes(
    output: &Value,
    cancellation: &Cancellation,
    clock: &ManualClock,
    accepted: bool,
) {
    let charge = if accepted {
        expected_bytes(cancellation)
    } else {
        0
    };
    let grant = cancellation.accounting.granted().log_bytes;
    for (index, probe) in output[0].as_array().unwrap().iter().enumerate() {
        assert_eq!(
            probe["outcome"],
            if accepted {
                json!({"ok":true})
            } else {
                json!({"err":{"case":"unavailable"}})
            }
        );
        let previous = charge * u64::try_from(index).unwrap();
        assert_eq!(unsigned(&probe["before"]), grant - previous);
        assert_eq!(unsigned(&probe["after"]), grant - previous - charge);
    }
    assert_eq!(output[0].as_array().unwrap().len(), 2);
    assert_eq!(
        cancellation
            .accounting
            .snapshot_at(clock.monotonic_now())
            .log_bytes,
        2 * charge
    );
    assert_eq!(cancellation.accounting.outstanding_reservations(), 0);
}

struct GatedSink {
    local: StructuredLocalSink,
    block: AtomicBool,
    entered: Notify,
}
impl GatedSink {
    async fn wait(&self) {
        if self.block.load(Ordering::Acquire) {
            self.entered.notify_one();
            std::future::pending::<()>().await;
        }
    }
}
impl TelemetrySink for GatedSink {
    fn emit_metric(&self, point: MetricPoint) -> BoxFuture<'_, Result<(), PlatformError>> {
        Box::pin(async move {
            self.wait().await;
            self.local.emit_metric(point).await
        })
    }
    fn emit_log(&self, log: LogRecord) -> BoxFuture<'_, Result<(), PlatformError>> {
        Box::pin(async move {
            self.wait().await;
            self.local.emit_log(log).await
        })
    }
    fn emit_span(&self, span: SpanRecord) -> BoxFuture<'_, Result<(), PlatformError>> {
        Box::pin(async move {
            self.wait().await;
            self.local.emit_span(span).await
        })
    }
}
pub struct Pipeline {
    pub observer: Arc<SharedActivationObserver>,
    pub handle: TelemetryHandle,
    pub runtime: TelemetryRuntime,
    pub local: StructuredLocalSink,
    sink: Arc<GatedSink>,
}
impl Pipeline {
    pub fn new(config: TelemetryPipelineConfig, observer: SharedActivationObserverConfig) -> Self {
        let local = StructuredLocalSink::new(LocalSinkConfig::default()).unwrap();
        let sink = Arc::new(GatedSink {
            local: local.clone(),
            block: AtomicBool::new(false),
            entered: Notify::new(),
        });
        let (handle, runtime) = TelemetryRuntime::spawn(config, sink.clone()).unwrap();
        let observer = Arc::new(SharedActivationObserver::new(handle.clone(), observer).unwrap());
        Self {
            observer,
            handle,
            runtime,
            local,
            sink,
        }
    }
    pub fn register(&self, cancellation: &Cancellation) {
        let context = ActivationObservationContext {
            token: ActivationObservationToken {
                manager: 1,
                sequence: 1,
            },
            activation_id: cancellation.id.clone(),
            root_activation_id: latent_core::ActivationId("root-pinned".into()),
            parent_activation_id: Some(latent_core::ActivationId("parent-pinned".into())),
            tenant: latent_core::TenantId("tests".into()),
            service: latent_core::ServiceId("capabilities".into()),
            contract: latent_core::ContractId(CONTRACT.into()),
            function: latent_core::FunctionId("log-twice".into()),
            trace_id: latent_core::TraceId("trace-pinned".into()),
            span_id: latent_core::SpanId("span-pinned".into()),
            trace_flags: 1,
            release: None,
            revision: None,
            route_generation: None,
        };
        self.observer.on_observation(
            &context,
            &ActivationObservation {
                occurred_at_unix_millis: 10_000,
                elapsed: Duration::ZERO,
                kind: ActivationObservationKind::Received,
            },
        );
        assert_eq!(self.observer.snapshot().active_correlations, 1);
    }
    pub async fn block(&self) {
        self.sink.block.store(true, Ordering::Release);
        self.handle.try_emit_metric(metric()).unwrap();
        tokio::time::timeout(Duration::from_secs(5), self.sink.entered.notified())
            .await
            .expect("exporter entered before watchdog");
        for _ in 0..self.handle.snapshot().queue_capacity {
            assert_eq!(self.handle.try_emit_metric(metric()), Ok(true));
        }
        assert_eq!(
            self.handle.snapshot().queue_depth,
            self.handle.snapshot().queue_capacity
        );
    }
}
fn metric() -> MetricPoint {
    MetricPoint {
        name: "latent.test".into(),
        kind: MetricKind::Counter,
        value: 1.0,
        unit: "1".into(),
        attributes: Metadata::new(),
        observed_at_unix_millis: 10_000,
    }
}
