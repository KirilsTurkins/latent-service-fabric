//! One bounded, node-owned exporter worker. Producers never await a sink.

mod config;
mod dimensions;
mod handle;
mod metrics;
pub(crate) mod record;
mod runtime;
#[cfg(test)]
mod tests;

use crate::local::TelemetryRecord;
use latent_core::{PlatformError, PlatformErrorCode};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::Arc;
use tokio::sync::{mpsc, oneshot};

pub use config::TelemetryPipelineConfig;
pub use handle::TelemetryHandle;
pub use runtime::TelemetryRuntime;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TelemetryDropReason {
    QueueFull,
    QueueClosed,
    InvalidRecord,
    SinkFailure,
    SinkTimeout,
}
impl TelemetryDropReason {
    const fn as_str(self) -> &'static str {
        match self {
            Self::QueueFull => "queue_full",
            Self::QueueClosed => "queue_closed",
            Self::InvalidRecord => "invalid_record",
            Self::SinkFailure => "sink_failure",
            Self::SinkTimeout => "sink_timeout",
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
    pub sink_timeouts: u64,
    pub flush_timeouts: u64,
    pub shutdown_timeouts: u64,
    pub worker_panics: u64,
}

#[derive(Debug, Default)]
struct PipelineCounters {
    accepted: AtomicU64,
    exported: AtomicU64,
    dropped_queue_full: AtomicU64,
    dropped_queue_closed: AtomicU64,
    dropped_invalid_record: AtomicU64,
    sink_failures: AtomicU64,
    sink_timeouts: AtomicU64,
    flush_timeouts: AtomicU64,
    shutdown_timeouts: AtomicU64,
    worker_panics: AtomicU64,
    closed: AtomicBool,
}

enum PipelineCommand {
    Record(TelemetryRecord),
    Flush(oneshot::Sender<()>),
    Shutdown(oneshot::Sender<()>),
}

fn increment(counter: &AtomicU64) {
    let _ = counter.fetch_update(Ordering::Relaxed, Ordering::Relaxed, |value| {
        Some(value.saturating_add(1))
    });
}

fn pipeline_error(code: PlatformErrorCode, message: &str) -> PlatformError {
    PlatformError {
        code,
        message: message.to_owned(),
        retryable: false,
        details: Vec::new(),
    }
}
