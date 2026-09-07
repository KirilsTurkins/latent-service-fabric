use super::{
    increment, mpsc, oneshot, pipeline_error, record, Arc, Ordering, PipelineCommand,
    PipelineCounters, TelemetryDropReason, TelemetryPipelineConfig, TelemetryPipelineSnapshot,
    TelemetryRecord,
};
use crate::{LogRecord, MetricPoint, SpanRecord};
use latent_core::{PlatformError, PlatformErrorCode};

#[derive(Clone)]
pub struct TelemetryHandle {
    pub(super) sender: mpsc::Sender<PipelineCommand>,
    pub(super) counters: Arc<PipelineCounters>,
    pub(super) config: TelemetryPipelineConfig,
}
impl std::fmt::Debug for TelemetryHandle {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("TelemetryHandle")
            .field("snapshot", &self.snapshot())
            .field("closed", &self.is_closed())
            .finish()
    }
}
impl TelemetryHandle {
    pub fn try_emit_metric(&self, point: MetricPoint) -> Result<bool, PlatformError> {
        self.try_submit(TelemetryRecord::Metric(point))
    }
    pub fn try_emit_log(&self, record: LogRecord) -> Result<bool, PlatformError> {
        self.try_submit(TelemetryRecord::Log(record))
    }
    pub fn try_emit_span(&self, span: SpanRecord) -> Result<bool, PlatformError> {
        self.try_submit(TelemetryRecord::Span(span))
    }
    #[must_use]
    pub fn snapshot(&self) -> TelemetryPipelineSnapshot {
        let counters = &self.counters;
        TelemetryPipelineSnapshot {
            queue_capacity: self.config.queue_capacity,
            queue_depth: self
                .config
                .queue_capacity
                .saturating_sub(self.sender.capacity()),
            accepted: counters.accepted.load(Ordering::Relaxed),
            exported: counters.exported.load(Ordering::Relaxed),
            dropped_queue_full: counters.dropped_queue_full.load(Ordering::Relaxed),
            dropped_queue_closed: counters.dropped_queue_closed.load(Ordering::Relaxed),
            dropped_invalid_record: counters.dropped_invalid_record.load(Ordering::Relaxed),
            sink_failures: counters.sink_failures.load(Ordering::Relaxed),
            sink_timeouts: counters.sink_timeouts.load(Ordering::Relaxed),
            flush_timeouts: counters.flush_timeouts.load(Ordering::Relaxed),
            shutdown_timeouts: counters.shutdown_timeouts.load(Ordering::Relaxed),
            worker_panics: counters.worker_panics.load(Ordering::Relaxed),
        }
    }
    #[must_use]
    pub fn is_closed(&self) -> bool {
        self.counters.closed.load(Ordering::Acquire) || self.sender.is_closed()
    }
    /// Waits for records preceding this barrier, including failed/timed-out
    /// export attempts. Inspect counters for delivery failures.
    pub async fn flush(&self) -> Result<(), PlatformError> {
        if self.is_closed() {
            return Err(closed());
        }
        let barrier = async {
            let (sender, receiver) = oneshot::channel();
            self.sender
                .send(PipelineCommand::Flush(sender))
                .await
                .map_err(|_| closed())?;
            receiver.await.map_err(|_| closed())
        };
        tokio::time::timeout(self.config.flush_timeout, barrier)
            .await
            .map_err(|_| {
                increment(&self.counters.flush_timeouts);
                pipeline_error(
                    PlatformErrorCode::DeadlineExceeded,
                    "telemetry flush timed out",
                )
            })?
    }
    fn try_submit(&self, record: TelemetryRecord) -> Result<bool, PlatformError> {
        if self.is_closed() {
            increment(&self.counters.dropped_queue_closed);
            return self.drop_result(TelemetryDropReason::QueueClosed);
        }
        if !record::valid(&record, &self.config) {
            increment(&self.counters.dropped_invalid_record);
            return self.drop_result(TelemetryDropReason::InvalidRecord);
        }
        match self.sender.try_send(PipelineCommand::Record(record)) {
            Ok(()) => {
                increment(&self.counters.accepted);
                Ok(true)
            }
            Err(mpsc::error::TrySendError::Full(_)) => {
                increment(&self.counters.dropped_queue_full);
                self.drop_result(TelemetryDropReason::QueueFull)
            }
            Err(mpsc::error::TrySendError::Closed(_)) => {
                increment(&self.counters.dropped_queue_closed);
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
fn closed() -> PlatformError {
    pipeline_error(PlatformErrorCode::Unavailable, "telemetry worker is closed")
}
