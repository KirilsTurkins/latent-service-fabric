//! Bounded node-owned telemetry, structured local export, and activation observation.
//!
//! The production-facing types in this crate deliberately separate activation
//! correlation from metric dimensions. Logs and spans may carry bounded
//! activation, tenant, service, release, and revision context. Metric attributes
//! are filtered through a fixed allow-list so activation identifiers and other
//! unbounded values can never become labels.

#![forbid(unsafe_code)]

mod local;
mod observer;
mod pipeline;

use latent_activation::{ActivationEnvelope, ActivationEvent, ActivationOutcome, TraceContext};
use latent_core::{ActivationId, BoxFuture, Metadata, PlatformError};

pub use local::{LocalSinkConfig, LocalSinkSnapshot, StructuredLocalSink, TelemetryRecord};
pub use observer::{
    ActivationCorrelation, ActivationLifecycleEvent, ActivationLifecycleStage,
    ActivationOutcomeClass, GuestLogObserver, GuestLogRecord, NoopActivationObserver,
    ObserverSnapshot, SharedActivationObserver, SharedActivationObserverConfig,
};
pub use pipeline::{
    TelemetryDropReason, TelemetryHandle, TelemetryPipelineConfig, TelemetryPipelineSnapshot,
    TelemetryRuntime,
};

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

/// Export boundary implemented once per node, never once per service.
///
/// Implementations may forward to OTLP, a file, a local collector, or another
/// backend. The shared pipeline invokes these methods from its single worker;
/// activation threads only call the non-blocking `TelemetryHandle` methods.
pub trait TelemetrySink: Send + Sync {
    fn emit_metric<'a>(&'a self, point: MetricPoint) -> BoxFuture<'a, Result<(), PlatformError>>;

    fn emit_log<'a>(&'a self, record: LogRecord) -> BoxFuture<'a, Result<(), PlatformError>>;

    fn emit_span<'a>(&'a self, span: SpanRecord) -> BoxFuture<'a, Result<(), PlatformError>>;
}

/// Synchronous observer contract used by activation, scheduler, and execution
/// boundaries. Implementations used on the hot path must be non-blocking.
pub trait ActivationObserver: Send + Sync {
    fn on_received(&self, _envelope: &ActivationEnvelope) {}

    fn on_event(&self, _event: &ActivationEvent) {}

    fn on_lifecycle(&self, _event: &ActivationLifecycleEvent) {}

    /// Original scaffold completion hook. Implementations that need no access
    /// to the full envelope can override [`Self::on_finalized`] instead.
    fn on_completed(&self, envelope: &ActivationEnvelope, outcome: &ActivationOutcome) {
        self.on_finalized(&envelope.activation_id, outcome);
    }

    /// Payload-free completion hook used by node wrappers so completing an
    /// activation never requires cloning or retaining its input.
    fn on_finalized(&self, _activation_id: &ActivationId, _outcome: &ActivationOutcome) {}

    fn on_cancel_requested(&self, _activation_id: &ActivationId) {}
}
