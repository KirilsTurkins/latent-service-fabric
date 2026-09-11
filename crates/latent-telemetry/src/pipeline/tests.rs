use super::*;
use crate::{LogRecord, LogSeverity, MetricKind, MetricPoint, SpanRecord, TelemetrySink};
use latent_core::{BoxFuture, Metadata};
use std::future::Future;
use std::pin::Pin;
use std::sync::atomic::AtomicUsize;
use std::task::{Context, Poll};
use std::time::Duration;
use tokio::sync::Notify;

#[derive(Clone, Copy)]
enum Mode {
    Pending,
    Fail,
    ConstructPanic,
    PollPanic,
    DropPanic,
}
struct Sink {
    mode: Mode,
    entered: Notify,
    live: Arc<AtomicUsize>,
}
impl Sink {
    fn new(mode: Mode) -> Arc<Self> {
        Arc::new(Self {
            mode,
            entered: Notify::new(),
            live: Arc::new(AtomicUsize::new(0)),
        })
    }
    fn emit(&self) -> BoxFuture<'_, Result<(), PlatformError>> {
        assert!(
            !matches!(self.mode, Mode::ConstructPanic),
            "export constructor panic"
        );
        self.live.fetch_add(1, Ordering::SeqCst);
        Box::pin(Export {
            sink: self,
            entered: false,
        })
    }
}
struct Export<'a> {
    sink: &'a Sink,
    entered: bool,
}
impl Future for Export<'_> {
    type Output = Result<(), PlatformError>;
    fn poll(mut self: Pin<&mut Self>, _: &mut Context<'_>) -> Poll<Self::Output> {
        if !self.entered {
            self.sink.entered.notify_one();
            self.entered = true;
        }
        match self.sink.mode {
            Mode::PollPanic => panic!("export poll panic"),
            Mode::Fail => Poll::Ready(Err(pipeline_error(
                PlatformErrorCode::Unavailable,
                "test sink failure",
            ))),
            Mode::Pending | Mode::DropPanic | Mode::ConstructPanic => Poll::Pending,
        }
    }
}
impl Drop for Export<'_> {
    fn drop(&mut self) {
        self.sink.live.fetch_sub(1, Ordering::SeqCst);
        assert!(
            !matches!(self.sink.mode, Mode::DropPanic),
            "export destructor panic"
        );
    }
}
impl TelemetrySink for Sink {
    fn emit_metric(&self, _: MetricPoint) -> BoxFuture<'_, Result<(), PlatformError>> {
        self.emit()
    }
    fn emit_log(&self, _: LogRecord) -> BoxFuture<'_, Result<(), PlatformError>> {
        self.emit()
    }
    fn emit_span(&self, _: SpanRecord) -> BoxFuture<'_, Result<(), PlatformError>> {
        self.emit()
    }
}
fn metric() -> MetricPoint {
    MetricPoint {
        name: "latent.test".to_owned(),
        kind: MetricKind::Counter,
        value: 1.0,
        unit: "1".to_owned(),
        attributes: Metadata::new(),
        observed_at_unix_millis: 1,
    }
}
fn config() -> TelemetryPipelineConfig {
    TelemetryPipelineConfig {
        queue_capacity: 2,
        export_timeout: Duration::from_millis(100),
        flush_timeout: Duration::from_secs(1),
        shutdown_timeout: Duration::from_secs(1),
        ..TelemetryPipelineConfig::default()
    }
}

#[tokio::test(start_paused = true)]
async fn blocked_exporter_bounds_queue_and_times_out_without_blocking_producers() {
    let sink = Sink::new(Mode::Pending);
    let (handle, runtime) = TelemetryRuntime::spawn(config(), sink.clone()).unwrap();
    assert_eq!(handle.try_emit_metric(metric()), Ok(true));
    sink.entered.notified().await;
    assert_eq!(handle.try_emit_metric(metric()), Ok(true));
    assert_eq!(handle.try_emit_metric(metric()), Ok(true));
    assert_eq!(handle.try_emit_metric(metric()), Ok(false));
    let snapshot = handle.snapshot();
    assert_eq!(snapshot.queue_depth, 2);
    assert_eq!(snapshot.accepted, 3);
    assert_eq!(snapshot.dropped_queue_full, 1);
    handle.flush().await.unwrap();
    assert_eq!(handle.snapshot().sink_timeouts, 3);
    assert_eq!(sink.live.load(Ordering::SeqCst), 0);
    runtime.shutdown().await.unwrap();
}

#[tokio::test(start_paused = true)]
async fn strict_mode_reports_full_invalid_and_closed_without_waiting() {
    let sink = Sink::new(Mode::Pending);
    let (handle, runtime) = TelemetryRuntime::spawn(
        TelemetryPipelineConfig {
            queue_capacity: 1,
            fail_on_drop: true,
            ..config()
        },
        sink.clone(),
    )
    .unwrap();
    handle.try_emit_metric(metric()).unwrap();
    sink.entered.notified().await;
    handle.try_emit_metric(metric()).unwrap();
    assert_eq!(
        handle.try_emit_metric(metric()).unwrap_err().code,
        PlatformErrorCode::ResourceExhausted
    );
    let mut invalid = metric();
    invalid
        .attributes
        .insert("activation_id".into(), "secret".into());
    assert!(handle.try_emit_metric(invalid).is_err());
    drop(runtime);
    assert!(handle.is_closed());
    assert!(handle.try_emit_metric(metric()).is_err());
    let snapshot = handle.snapshot();
    assert_eq!(snapshot.dropped_queue_full, 1);
    assert_eq!(snapshot.dropped_invalid_record, 1);
    assert_eq!(snapshot.dropped_queue_closed, 1);
    tokio::task::yield_now().await;
    assert_eq!(sink.live.load(Ordering::SeqCst), 0);
}

#[tokio::test(start_paused = true)]
async fn flush_has_one_deadline_covering_queue_insertion_and_acknowledgement() {
    let sink = Sink::new(Mode::Pending);
    let (handle, runtime) = TelemetryRuntime::spawn(
        TelemetryPipelineConfig {
            queue_capacity: 1,
            export_timeout: Duration::from_secs(2),
            flush_timeout: Duration::from_millis(10),
            ..config()
        },
        sink.clone(),
    )
    .unwrap();
    handle.try_emit_metric(metric()).unwrap();
    sink.entered.notified().await;
    handle.try_emit_metric(metric()).unwrap();
    assert_eq!(
        handle.flush().await.unwrap_err().code,
        PlatformErrorCode::DeadlineExceeded
    );
    assert_eq!(handle.snapshot().flush_timeouts, 1);
    assert_eq!(handle.snapshot().queue_depth, 1);
    drop(runtime);
    tokio::task::yield_now().await;
    assert_eq!(sink.live.load(Ordering::SeqCst), 0);
}

#[tokio::test(start_paused = true)]
async fn shutdown_deadline_aborts_export_and_closes_retained_handles() {
    let sink = Sink::new(Mode::Pending);
    let (handle, runtime) = TelemetryRuntime::spawn(
        TelemetryPipelineConfig {
            export_timeout: Duration::from_secs(2),
            shutdown_timeout: Duration::from_millis(10),
            ..config()
        },
        sink.clone(),
    )
    .unwrap();
    handle.try_emit_metric(metric()).unwrap();
    sink.entered.notified().await;
    assert_eq!(
        runtime.shutdown().await.unwrap_err().code,
        PlatformErrorCode::DeadlineExceeded
    );
    assert_eq!(handle.snapshot().shutdown_timeouts, 1);
    assert!(handle.is_closed());
    assert_eq!(handle.try_emit_metric(metric()), Ok(false));
    tokio::task::yield_now().await;
    assert_eq!(sink.live.load(Ordering::SeqCst), 0);
}

#[tokio::test(start_paused = true)]
async fn dropping_unpolled_shutdown_future_retains_worker_ownership() {
    let sink = Sink::new(Mode::Pending);
    let (handle, runtime) = TelemetryRuntime::spawn(config(), sink.clone()).unwrap();
    handle.try_emit_metric(metric()).unwrap();
    sink.entered.notified().await;
    drop(runtime.shutdown());
    assert!(handle.is_closed());
    tokio::task::yield_now().await;
    assert_eq!(sink.live.load(Ordering::SeqCst), 0);
}

#[tokio::test(start_paused = true)]
async fn sink_errors_and_constructor_poll_and_drop_panics_are_isolated() {
    for mode in [
        Mode::Fail,
        Mode::ConstructPanic,
        Mode::PollPanic,
        Mode::DropPanic,
    ] {
        let sink = Sink::new(mode);
        let (handle, runtime) = TelemetryRuntime::spawn(config(), sink.clone()).unwrap();
        handle.try_emit_metric(metric()).unwrap();
        handle.flush().await.unwrap();
        let snapshot = handle.snapshot();
        assert_eq!(snapshot.exported, 0);
        assert_eq!(snapshot.sink_failures + snapshot.sink_timeouts, 1);
        assert_eq!(
            snapshot.worker_panics,
            u64::from(!matches!(mode, Mode::Fail))
        );
        assert!(!handle.is_closed());
        assert_eq!(sink.live.load(Ordering::SeqCst), 0);
        runtime.shutdown().await.unwrap();
    }
}

#[tokio::test]
async fn redacted_short_strings_with_large_retained_allocations_are_rejected() {
    let sink =
        Arc::new(crate::StructuredLocalSink::new(crate::LocalSinkConfig::default()).unwrap());
    let (handle, runtime) = TelemetryRuntime::spawn(config(), sink.clone()).unwrap();
    let mut body = String::with_capacity(128 * 1024);
    body.push_str("redacted");
    let log = LogRecord {
        severity: LogSeverity::Info,
        body,
        trace: None,
        attributes: Metadata::new(),
        observed_at_unix_millis: 1,
    };
    assert_eq!(handle.try_emit_log(log), Ok(false));
    let mut point = metric();
    point
        .attributes
        .insert("error_code".into(), "resource-exhausted".into());
    assert_eq!(handle.try_emit_metric(point), Ok(true));
    handle.flush().await.unwrap();
    assert_eq!(handle.snapshot().dropped_invalid_record, 1);
    assert_eq!(handle.snapshot().exported, 1);
    assert_eq!(sink.snapshot().entries, 1);
    runtime.shutdown().await.unwrap();
}

#[test]
fn invalid_or_overflowing_pipeline_bounds_are_rejected_before_spawn() {
    for candidate in [
        TelemetryPipelineConfig {
            queue_capacity: usize::MAX,
            ..config()
        },
        TelemetryPipelineConfig {
            maximum_record_bytes: usize::MAX,
            ..config()
        },
        TelemetryPipelineConfig {
            export_timeout: Duration::ZERO,
            ..config()
        },
        TelemetryPipelineConfig {
            flush_timeout: Duration::from_secs(61),
            ..config()
        },
        TelemetryPipelineConfig {
            shutdown_timeout: Duration::ZERO,
            ..config()
        },
    ] {
        assert!(candidate.validate().is_err());
    }
    assert!(TelemetryRuntime::spawn(config(), Sink::new(Mode::Pending)).is_err());
}
