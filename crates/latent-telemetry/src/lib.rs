//! Telemetry event, metric, log, trace, and activation-observer interfaces.

#![forbid(unsafe_code)]

use latent_activation::{ActivationEnvelope, ActivationEvent, ActivationOutcome, TraceContext};
use latent_core::{BoxFuture, Metadata, PlatformError};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MetricKind {
    Counter,
    UpDownCounter,
    Gauge,
    Histogram,
}

#[derive(Debug, Clone, PartialEq)]
pub struct MetricPoint {
    pub name: String,
    pub kind: MetricKind,
    pub value: f64,
    pub unit: String,
    pub attributes: Metadata,
    pub observed_at_unix_millis: u64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LogSeverity {
    Trace,
    Debug,
    Info,
    Warn,
    Error,
    Fatal,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LogRecord {
    pub severity: LogSeverity,
    pub body: String,
    pub trace: Option<TraceContext>,
    pub attributes: Metadata,
    pub observed_at_unix_millis: u64,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SpanRecord {
    pub name: String,
    pub trace: TraceContext,
    pub parent_span_id: Option<String>,
    pub started_at_unix_nanos: u64,
    pub ended_at_unix_nanos: u64,
    pub status: String,
    pub attributes: Metadata,
}

pub trait TelemetrySink: Send + Sync {
    fn emit_metric<'a>(&'a self, point: MetricPoint) -> BoxFuture<'a, Result<(), PlatformError>>;

    fn emit_log<'a>(&'a self, record: LogRecord) -> BoxFuture<'a, Result<(), PlatformError>>;

    fn emit_span<'a>(&'a self, record: SpanRecord) -> BoxFuture<'a, Result<(), PlatformError>>;
}

pub trait ActivationObserver: Send + Sync {
    fn on_received(&self, envelope: &ActivationEnvelope);
    fn on_event(&self, event: &ActivationEvent);
    fn on_completed(&self, envelope: &ActivationEnvelope, outcome: &ActivationOutcome);
}
