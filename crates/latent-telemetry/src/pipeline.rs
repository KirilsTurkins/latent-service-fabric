use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;

use latent_core::{Metadata, PlatformError, PlatformErrorCode};
use tokio::sync::{mpsc, oneshot};
use tokio::task::JoinHandle;

use crate::{LogRecord, MetricKind, MetricPoint, SpanRecord, TelemetrySink};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TelemetryDropReason {
    QueueFull,
    QueueClosed,
    InvalidRecord,
    SinkFailure,
}

impl TelemetryDropReason {
    const fn as_str(self) -> &'static str {
        match self {
            Self::QueueFull => "queue_full",
            Self::QueueClosed => "queue_closed",
            Self::InvalidRecord => "invalid_record",
            Self::SinkFailure => "sink_failure",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct TelemetryPipelineConfig {
    pub queue_capacity: usize,
    pub maximum_record_bytes: usize,
    pub maximum_attributes: usize,
    pub maximum_attribute_name_bytes: usize,
    pub maximum_attribute_value_bytes: usize,
    pub fail_on_drop: bool,
}

impl Default for TelemetryPipelineConfig {
    fn default() -> Self {
        Self {
            queue_capacity: 1_024,
            maximum_record_bytes: 64 * 1_024,
            maximum_attributes: 32,
            maximum_attribute_name_bytes: 64,
            maximum_attribute_value_bytes: 256,
            fail_on_drop: false,
        }
    }
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct TelemetryPipelineSnapshot {
    pub queue_capacity: usize,
    pub queue_depth: usize,
    pub accepted: u64,
    pub exported: u64,
    pub dropped_queue_full: u64,
    pub dropped_queue_closed: u64,
    pub dropped_invalid_record: u64,
    pub sink_failures: u64,
}

#[derive(Debug, Default)]
struct PipelineCounters {
    accepted: AtomicU64,
    exported: AtomicU64,
    dropped_queue_full: AtomicU64,
    dropped_queue_closed: AtomicU64,
    dropped_invalid_record: AtomicU64,
    sink_failures: AtomicU64,
}

enum PipelineCommand {
    Metric(MetricPoint),
    Log(LogRecord),
    Span(SpanRecord),
    Flush(oneshot::Sender<()>),
    Shutdown(oneshot::Sender<()>),
}

#[derive(Clone)]
pub struct TelemetryHandle {
    sender: mpsc::Sender<PipelineCommand>,
    counters: Arc<PipelineCounters>,
    config: TelemetryPipelineConfig,
}

impl std::fmt::Debug for TelemetryHandle {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("TelemetryHandle")
            .field("snapshot", &self.snapshot())
            .finish()
    }
}

impl TelemetryHandle {
    pub fn try_emit_metric(&self, point: MetricPoint) -> Result<bool, PlatformError> {
        let valid = validate_metric(&point, &self.config);
        self.try_submit(PipelineCommand::Metric(point), valid)
    }

    pub fn try_emit_log(&self, record: LogRecord) -> Result<bool, PlatformError> {
        let valid = validate_log(&record, &self.config);
        self.try_submit(PipelineCommand::Log(record), valid)
    }

    pub fn try_emit_span(&self, span: SpanRecord) -> Result<bool, PlatformError> {
        let valid = validate_span(&span, &self.config);
        self.try_submit(PipelineCommand::Span(span), valid)
    }

    #[must_use]
    pub fn snapshot(&self) -> TelemetryPipelineSnapshot {
        TelemetryPipelineSnapshot {
            queue_capacity: self.config.queue_capacity,
            queue_depth: self
                .config
                .queue_capacity
                .saturating_sub(self.sender.capacity()),
            accepted: self.counters.accepted.load(Ordering::Relaxed),
            exported: self.counters.exported.load(Ordering::Relaxed),
            dropped_queue_full: self.counters.dropped_queue_full.load(Ordering::Relaxed),
            dropped_queue_closed: self.counters.dropped_queue_closed.load(Ordering::Relaxed),
            dropped_invalid_record: self.counters.dropped_invalid_record.load(Ordering::Relaxed),
            sink_failures: self.counters.sink_failures.load(Ordering::Relaxed),
        }
    }

    #[must_use]
    pub fn operational_metrics(&self, observed_at_unix_millis: u64) -> Vec<MetricPoint> {
        let snapshot = self.snapshot();
        let metric = |name: &str, value: f64, kind: MetricKind, attributes: Metadata| MetricPoint {
            name: name.to_owned(),
            kind,
            value,
            unit: "1".to_owned(),
            attributes,
            observed_at_unix_millis,
        };
        let dropped = |reason: TelemetryDropReason, value: u64| {
            metric(
                "latent.telemetry.dropped",
                value as f64,
                MetricKind::Counter,
                Metadata::from([("reason".to_owned(), reason.as_str().to_owned())]),
            )
        };
        vec![
            metric(
                "latent.telemetry.queue.depth",
                snapshot.queue_depth as f64,
                MetricKind::Gauge,
                Metadata::new(),
            ),
            metric(
                "latent.telemetry.queue.capacity",
                snapshot.queue_capacity as f64,
                MetricKind::Gauge,
                Metadata::new(),
            ),
            metric(
                "latent.telemetry.accepted",
                snapshot.accepted as f64,
                MetricKind::Counter,
                Metadata::new(),
            ),
            metric(
                "latent.telemetry.exported",
                snapshot.exported as f64,
                MetricKind::Counter,
                Metadata::new(),
            ),
            dropped(TelemetryDropReason::QueueFull, snapshot.dropped_queue_full),
            dropped(
                TelemetryDropReason::QueueClosed,
                snapshot.dropped_queue_closed,
            ),
            dropped(
                TelemetryDropReason::InvalidRecord,
                snapshot.dropped_invalid_record,
            ),
            dropped(TelemetryDropReason::SinkFailure, snapshot.sink_failures),
        ]
    }

    pub async fn flush(&self) -> Result<(), PlatformError> {
        let (sender, receiver) = oneshot::channel();
        self.sender
            .send(PipelineCommand::Flush(sender))
            .await
            .map_err(|_| {
                pipeline_error(PlatformErrorCode::Unavailable, "telemetry worker is closed")
            })?;
        receiver.await.map_err(|_| {
            pipeline_error(
                PlatformErrorCode::Unavailable,
                "telemetry flush was interrupted",
            )
        })
    }

    fn try_submit(&self, command: PipelineCommand, valid: bool) -> Result<bool, PlatformError> {
        if !valid {
            self.counters
                .dropped_invalid_record
                .fetch_add(1, Ordering::Relaxed);
            return self.drop_result(TelemetryDropReason::InvalidRecord);
        }
        match self.sender.try_send(command) {
            Ok(()) => {
                self.counters.accepted.fetch_add(1, Ordering::Relaxed);
                Ok(true)
            }
            Err(mpsc::error::TrySendError::Full(_)) => {
                self.counters
                    .dropped_queue_full
                    .fetch_add(1, Ordering::Relaxed);
                self.drop_result(TelemetryDropReason::QueueFull)
            }
            Err(mpsc::error::TrySendError::Closed(_)) => {
                self.counters
                    .dropped_queue_closed
                    .fetch_add(1, Ordering::Relaxed);
                self.drop_result(TelemetryDropReason::QueueClosed)
            }
        }
    }

    fn drop_result(&self, reason: TelemetryDropReason) -> Result<bool, PlatformError> {
        if self.config.fail_on_drop {
            Err(pipeline_error(
                PlatformErrorCode::ResourceExhausted,
                &format!("telemetry record dropped: {}", reason.as_str()),
            ))
        } else {
            Ok(false)
        }
    }
}

pub struct TelemetryRuntime {
    sender: mpsc::Sender<PipelineCommand>,
    task: Option<JoinHandle<()>>,
}

impl std::fmt::Debug for TelemetryRuntime {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("TelemetryRuntime")
            .field(
                "worker_finished",
                &self.task.as_ref().is_none_or(JoinHandle::is_finished),
            )
            .finish()
    }
}

impl TelemetryRuntime {
    pub fn spawn(
        config: TelemetryPipelineConfig,
        sink: Arc<dyn TelemetrySink>,
    ) -> Result<(TelemetryHandle, Self), PlatformError> {
        validate_config(&config)?;
        let (sender, mut receiver) = mpsc::channel(config.queue_capacity);
        let counters = Arc::new(PipelineCounters::default());
        let worker_counters = Arc::clone(&counters);
        let task = tokio::spawn(async move {
            while let Some(command) = receiver.recv().await {
                match command {
                    PipelineCommand::Metric(point) => {
                        export_result(sink.emit_metric(point).await, &worker_counters);
                    }
                    PipelineCommand::Log(record) => {
                        export_result(sink.emit_log(record).await, &worker_counters);
                    }
                    PipelineCommand::Span(span) => {
                        export_result(sink.emit_span(span).await, &worker_counters);
                    }
                    PipelineCommand::Flush(acknowledge) => {
                        let _ = acknowledge.send(());
                    }
                    PipelineCommand::Shutdown(acknowledge) => {
                        let _ = acknowledge.send(());
                        break;
                    }
                }
            }
        });
        let handle = TelemetryHandle {
            sender: sender.clone(),
            counters,
            config,
        };
        Ok((
            handle,
            Self {
                sender,
                task: Some(task),
            },
        ))
    }

    pub async fn shutdown(mut self) -> Result<(), PlatformError> {
        let (sender, receiver) = oneshot::channel();
        self.sender
            .send(PipelineCommand::Shutdown(sender))
            .await
            .map_err(|_| {
                pipeline_error(PlatformErrorCode::Unavailable, "telemetry worker is closed")
            })?;
        receiver.await.map_err(|_| {
            pipeline_error(
                PlatformErrorCode::Unavailable,
                "telemetry shutdown acknowledgement was interrupted",
            )
        })?;
        if let Some(task) = self.task.take() {
            task.await.map_err(|error| {
                pipeline_error(
                    PlatformErrorCode::Internal,
                    &format!("telemetry worker failed: {error}"),
                )
            })?;
        }
        Ok(())
    }

    pub fn abort(mut self) {
        if let Some(task) = self.task.take() {
            task.abort();
        }
    }
}

fn export_result(result: Result<(), PlatformError>, counters: &PipelineCounters) {
    if result.is_ok() {
        counters.exported.fetch_add(1, Ordering::Relaxed);
    } else {
        counters.sink_failures.fetch_add(1, Ordering::Relaxed);
    }
}

fn validate_config(config: &TelemetryPipelineConfig) -> Result<(), PlatformError> {
    if config.queue_capacity == 0
        || config.maximum_record_bytes == 0
        || config.maximum_attributes == 0
        || config.maximum_attribute_name_bytes == 0
        || config.maximum_attribute_value_bytes == 0
    {
        return Err(pipeline_error(
            PlatformErrorCode::InvalidArgument,
            "telemetry pipeline bounds must be non-zero",
        ));
    }
    Ok(())
}

fn validate_metric(point: &MetricPoint, config: &TelemetryPipelineConfig) -> bool {
    !point.name.is_empty()
        && point.name.len() <= config.maximum_attribute_value_bytes
        && point.unit.len() <= config.maximum_attribute_name_bytes
        && point.value.is_finite()
        && valid_metadata(&point.attributes, config)
        && metric_size(point) <= config.maximum_record_bytes
}

fn validate_log(record: &LogRecord, config: &TelemetryPipelineConfig) -> bool {
    valid_trace(record.trace.as_ref(), config)
        && valid_metadata(&record.attributes, config)
        && log_size(record) <= config.maximum_record_bytes
}

fn validate_span(span: &SpanRecord, config: &TelemetryPipelineConfig) -> bool {
    !span.name.is_empty()
        && span.name.len() <= config.maximum_attribute_value_bytes
        && span.status.len() <= config.maximum_attribute_value_bytes
        && valid_trace(Some(&span.trace), config)
        && span
            .parent_span_id
            .as_ref()
            .is_none_or(|value| value.len() <= config.maximum_attribute_value_bytes)
        && valid_metadata(&span.attributes, config)
        && span_size(span) <= config.maximum_record_bytes
}

fn valid_trace(
    trace: Option<&latent_activation::TraceContext>,
    config: &TelemetryPipelineConfig,
) -> bool {
    trace.is_none_or(|trace| {
        trace.trace_id.0.len() <= config.maximum_attribute_value_bytes
            && trace.span_id.0.len() <= config.maximum_attribute_value_bytes
            && valid_metadata(&trace.baggage, config)
    })
}

fn valid_metadata(metadata: &Metadata, config: &TelemetryPipelineConfig) -> bool {
    metadata.len() <= config.maximum_attributes
        && metadata.iter().all(|(name, value)| {
            !name.is_empty()
                && name.len() <= config.maximum_attribute_name_bytes
                && value.len() <= config.maximum_attribute_value_bytes
        })
}

fn metric_size(point: &MetricPoint) -> usize {
    point
        .name
        .len()
        .saturating_add(point.unit.len())
        .saturating_add(metadata_size(&point.attributes))
        .saturating_add(std::mem::size_of::<f64>())
}

fn log_size(record: &LogRecord) -> usize {
    record
        .body
        .len()
        .saturating_add(trace_size(record.trace.as_ref()))
        .saturating_add(metadata_size(&record.attributes))
}

fn span_size(span: &SpanRecord) -> usize {
    span.name
        .len()
        .saturating_add(span.status.len())
        .saturating_add(trace_size(Some(&span.trace)))
        .saturating_add(span.parent_span_id.as_ref().map_or(0, String::len))
        .saturating_add(metadata_size(&span.attributes))
}

fn trace_size(trace: Option<&latent_activation::TraceContext>) -> usize {
    trace.map_or(0, |trace| {
        trace
            .trace_id
            .0
            .len()
            .saturating_add(trace.span_id.0.len())
            .saturating_add(metadata_size(&trace.baggage))
    })
}

fn metadata_size(metadata: &Metadata) -> usize {
    metadata.iter().fold(0, |total, (name, value)| {
        total.saturating_add(name.len()).saturating_add(value.len())
    })
}

fn pipeline_error(code: PlatformErrorCode, message: &str) -> PlatformError {
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
    use crate::{LocalSinkConfig, StructuredLocalSink};

    #[tokio::test]
    async fn blocked_or_full_pipeline_remains_bounded_and_reports_drops() {
        let sink = Arc::new(
            StructuredLocalSink::new(LocalSinkConfig {
                maximum_entries: 8,
                maximum_bytes: 8 * 1_024,
            })
            .expect("valid sink"),
        );
        let (handle, runtime) = TelemetryRuntime::spawn(
            TelemetryPipelineConfig {
                queue_capacity: 1,
                ..TelemetryPipelineConfig::default()
            },
            sink,
        )
        .expect("valid pipeline");
        for _ in 0..128 {
            let _ = handle.try_emit_metric(MetricPoint {
                name: "latent.test".to_owned(),
                kind: MetricKind::Counter,
                value: 1.0,
                unit: "1".to_owned(),
                attributes: Metadata::new(),
                observed_at_unix_millis: 1,
            });
        }
        handle.flush().await.expect("flush succeeds");
        let snapshot = handle.snapshot();
        assert!(snapshot.queue_depth <= snapshot.queue_capacity);
        assert!(snapshot.accepted + snapshot.dropped_queue_full >= 128);
        runtime.shutdown().await.expect("shutdown succeeds");
    }
}
