use std::collections::VecDeque;
use std::sync::{Arc, Mutex, MutexGuard};

use latent_core::{BoxFuture, PlatformError, PlatformErrorCode};

use crate::{LogRecord, MetricPoint, SpanRecord, TelemetrySink};

#[derive(Debug, Clone, PartialEq)]
pub enum TelemetryRecord {
    Metric(MetricPoint),
    Log(LogRecord),
    Span(SpanRecord),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct LocalSinkConfig {
    pub maximum_entries: usize,
    pub maximum_bytes: usize,
}

impl Default for LocalSinkConfig {
    fn default() -> Self {
        Self {
            maximum_entries: 4_096,
            maximum_bytes: 8 * 1024 * 1024,
        }
    }
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct LocalSinkSnapshot {
    pub entries: usize,
    pub retained_bytes: usize,
    pub maximum_entries: usize,
    pub maximum_bytes: usize,
    pub evicted_entries: u64,
    pub dropped_oversized: u64,
}

#[derive(Debug, Default)]
struct LocalSinkState {
    records: VecDeque<TelemetryRecord>,
    retained_bytes: usize,
    evicted_entries: u64,
    dropped_oversized: u64,
}

#[derive(Debug, Clone)]
pub struct StructuredLocalSink {
    config: LocalSinkConfig,
    state: Arc<Mutex<LocalSinkState>>,
}

impl StructuredLocalSink {
    pub fn new(config: LocalSinkConfig) -> Result<Self, PlatformError> {
        if config.maximum_entries == 0 || config.maximum_bytes == 0 {
            return Err(local_sink_error(
                PlatformErrorCode::InvalidArgument,
                "structured local sink bounds must be non-zero",
            ));
        }
        Ok(Self {
            config,
            state: Arc::new(Mutex::new(LocalSinkState::default())),
        })
    }

    #[must_use]
    pub fn records(&self) -> Vec<TelemetryRecord> {
        self.lock_state().records.iter().cloned().collect()
    }

    #[must_use]
    pub fn snapshot(&self) -> LocalSinkSnapshot {
        let state = self.lock_state();
        LocalSinkSnapshot {
            entries: state.records.len(),
            retained_bytes: state.retained_bytes,
            maximum_entries: self.config.maximum_entries,
            maximum_bytes: self.config.maximum_bytes,
            evicted_entries: state.evicted_entries,
            dropped_oversized: state.dropped_oversized,
        }
    }

    pub fn clear(&self) {
        let mut state = self.lock_state();
        state.records.clear();
        state.retained_bytes = 0;
    }

    fn push(&self, record: TelemetryRecord) {
        let record_bytes = record_size(&record);
        let mut state = self.lock_state();
        if record_bytes > self.config.maximum_bytes {
            state.dropped_oversized = state.dropped_oversized.saturating_add(1);
            return;
        }
        while state.records.len() >= self.config.maximum_entries
            || state.retained_bytes.saturating_add(record_bytes) > self.config.maximum_bytes
        {
            let Some(evicted) = state.records.pop_front() else {
                break;
            };
            state.retained_bytes = state.retained_bytes.saturating_sub(record_size(&evicted));
            state.evicted_entries = state.evicted_entries.saturating_add(1);
        }
        state.retained_bytes = state.retained_bytes.saturating_add(record_bytes);
        state.records.push_back(record);
    }

    fn lock_state(&self) -> MutexGuard<'_, LocalSinkState> {
        self.state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
    }
}

impl TelemetrySink for StructuredLocalSink {
    fn emit_metric<'a>(&'a self, point: MetricPoint) -> BoxFuture<'a, Result<(), PlatformError>> {
        self.push(TelemetryRecord::Metric(point));
        Box::pin(async move { Ok(()) })
    }

    fn emit_log<'a>(&'a self, record: LogRecord) -> BoxFuture<'a, Result<(), PlatformError>> {
        self.push(TelemetryRecord::Log(record));
        Box::pin(async move { Ok(()) })
    }

    fn emit_span<'a>(&'a self, span: SpanRecord) -> BoxFuture<'a, Result<(), PlatformError>> {
        self.push(TelemetryRecord::Span(span));
        Box::pin(async move { Ok(()) })
    }
}

fn record_size(record: &TelemetryRecord) -> usize {
    match record {
        TelemetryRecord::Metric(point) => {
            point.name.len()
                + point.unit.len()
                + std::mem::size_of::<f64>()
                + metadata_size(&point.attributes)
        }
        TelemetryRecord::Log(record) => {
            record.body.len()
                + record
                    .trace
                    .as_ref()
                    .map_or(0, |trace| trace.trace_id.0.len() + trace.span_id.0.len())
                + metadata_size(&record.attributes)
        }
        TelemetryRecord::Span(span) => {
            span.name.len()
                + span.status.len()
                + span.trace.trace_id.0.len()
                + span.trace.span_id.0.len()
                + span.parent_span_id.as_ref().map_or(0, String::len)
                + metadata_size(&span.attributes)
        }
    }
}

fn metadata_size(metadata: &latent_core::Metadata) -> usize {
    metadata
        .iter()
        .map(|(name, value)| name.len().saturating_add(value.len()))
        .sum()
}

fn local_sink_error(code: PlatformErrorCode, message: &str) -> PlatformError {
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
    use crate::LogSeverity;

    #[test]
    fn local_sink_evicts_oldest_records_within_both_bounds() {
        let sink = StructuredLocalSink::new(LocalSinkConfig {
            maximum_entries: 2,
            maximum_bytes: 256,
        })
        .expect("valid sink");
        for body in ["first", "second", "third"] {
            futures_lite_block_on(sink.emit_log(LogRecord {
                severity: LogSeverity::Info,
                body: body.to_owned(),
                trace: None,
                attributes: latent_core::Metadata::new(),
                observed_at_unix_millis: 1,
            }))
            .expect("local export succeeds");
        }
        let snapshot = sink.snapshot();
        assert_eq!(snapshot.entries, 2);
        assert_eq!(snapshot.evicted_entries, 1);
        let records = sink.records();
        let TelemetryRecord::Log(first) = &records[0] else {
            panic!("record is a log");
        };
        assert_eq!(first.body, "second");
    }

    fn futures_lite_block_on<F: std::future::Future>(future: F) -> F::Output {
        use std::pin::pin;
        use std::task::{Context, Poll, Wake, Waker};

        struct NoopWake;
        impl Wake for NoopWake {
            fn wake(self: Arc<Self>) {}
        }

        let waker = Waker::from(Arc::new(NoopWake));
        let mut context = Context::from_waker(&waker);
        let mut future = pin!(future);
        loop {
            match future.as_mut().poll(&mut context) {
                Poll::Ready(value) => return value,
                Poll::Pending => std::thread::yield_now(),
            }
        }
    }
}
