//! Bounded in-memory structured capture. Redaction belongs to the observer;
//! this sink preserves accepted records exactly and never captures payloads implicitly.
use crate::pipeline::record::retained_bytes;
use crate::{LogRecord, MetricPoint, SpanRecord, TelemetrySink};
use latent_core::{BoxFuture, PlatformError, PlatformErrorCode};
use std::collections::VecDeque;
use std::sync::{Arc, Mutex, MutexGuard};
#[cfg(test)]
mod tests;

#[derive(Debug, Clone, PartialEq)]
pub enum TelemetryRecord {
    Metric(MetricPoint),
    Log(LogRecord),
    Span(SpanRecord),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct LocalSinkConfig {
    pub maximum_entries: usize,
    /// Owned string capacities and conservative record/map bookkeeping.
    /// Deque spare slots are separately bounded by `max(4, 2 * maximum_entries)`.
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
#[derive(Debug)]
struct StoredRecord {
    record: TelemetryRecord,
    bytes: usize,
}
#[derive(Debug, Default)]
struct LocalSinkState {
    records: VecDeque<StoredRecord>,
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
        let slots = config
            .maximum_entries
            .checked_mul(2)
            .and_then(|count| count.max(4).checked_mul(size_of::<StoredRecord>()));
        if config.maximum_entries == 0
            || config.maximum_bytes == 0
            || slots
                .and_then(|slots| slots.checked_add(config.maximum_bytes))
                .is_none_or(|bytes| bytes > isize::MAX as usize)
        {
            return Err(local_sink_error(
                PlatformErrorCode::InvalidArgument,
                "invalid structured local sink bounds",
            ));
        }
        Ok(Self {
            config,
            state: Arc::new(Mutex::new(LocalSinkState::default())),
        })
    }
    #[must_use]
    pub fn records(&self) -> Vec<TelemetryRecord> {
        self.lock_state()
            .records
            .iter()
            .map(|stored| stored.record.clone())
            .collect()
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
    fn push(&self, record: TelemetryRecord) -> Result<(), PlatformError> {
        let bytes = retained_bytes(&record, self.config.maximum_bytes);
        let mut state = self.lock_state();
        let Some(bytes) = bytes else {
            state.dropped_oversized = state.dropped_oversized.saturating_add(1);
            return Err(local_sink_error(
                PlatformErrorCode::ResourceExhausted,
                "telemetry record exceeds the local retention bound",
            ));
        };
        while state.records.len() >= self.config.maximum_entries
            || state.retained_bytes > self.config.maximum_bytes - bytes
        {
            let Some(evicted) = state.records.pop_front() else {
                break;
            };
            state.retained_bytes -= evicted.bytes;
            state.evicted_entries = state.evicted_entries.saturating_add(1);
        }
        state.retained_bytes += bytes;
        state.records.push_back(StoredRecord { record, bytes });
        Ok(())
    }
    fn lock_state(&self) -> MutexGuard<'_, LocalSinkState> {
        self.state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
    }
}
impl TelemetrySink for StructuredLocalSink {
    fn emit_metric(&self, point: MetricPoint) -> BoxFuture<'_, Result<(), PlatformError>> {
        Box::pin(std::future::ready(
            self.push(TelemetryRecord::Metric(point)),
        ))
    }
    fn emit_log(&self, record: LogRecord) -> BoxFuture<'_, Result<(), PlatformError>> {
        Box::pin(std::future::ready(self.push(TelemetryRecord::Log(record))))
    }
    fn emit_span(&self, span: SpanRecord) -> BoxFuture<'_, Result<(), PlatformError>> {
        Box::pin(std::future::ready(self.push(TelemetryRecord::Span(span))))
    }
}
fn local_sink_error(code: PlatformErrorCode, message: &str) -> PlatformError {
    PlatformError {
        code,
        message: message.to_owned(),
        retryable: false,
        details: Vec::new(),
    }
}
