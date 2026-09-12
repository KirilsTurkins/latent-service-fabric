//! Telemetry event, metric, log, trace, and activation-observer interfaces.

#![forbid(unsafe_code)]

mod local;
mod observation;
mod observer;
mod phase2_canary;
mod pipeline;

pub use local::{LocalSinkConfig, LocalSinkSnapshot, StructuredLocalSink, TelemetryRecord};
pub use observation::{
    ActivationCleanupDisposition, ActivationObservation, ActivationObservationContext,
    ActivationObservationKind, ActivationObservationToken, ActivationOutcomeClass,
    ActivationTerminalObservation, GuestLogObserver, GuestLogRecord, NoopActivationObserver,
};
pub use observer::{ObserverSnapshot, SharedActivationObserver, SharedActivationObserverConfig};
pub use phase2_canary::{
    BoundedPhase2CanaryOutcomeWindow, CanaryCapture, CanaryCaptureAttempt, CanaryCoverage,
    CanaryRevisionBinding, CanaryRevisionSnapshot, CanarySample, CanaryWindow,
    CanaryWindowIdentity, CanaryWindowSnapshot, CanaryWindowSpec, Phase2CanaryOutcomeClass,
    Phase2CanaryOutcomeCounters, Phase2CanaryOutcomeWindowConfig, Phase2CanaryWindowSnapshot,
    SelectedOutcomeRevision, CANARY_LATENCY_UPPER_MICROS,
};
pub use pipeline::{
    TelemetryDropReason, TelemetryHandle, TelemetryPipelineConfig, TelemetryPipelineSnapshot,
    TelemetryRuntime,
};

use latent_activation::TraceContext;
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
    fn emit_metric(&self, point: MetricPoint) -> BoxFuture<'_, Result<(), PlatformError>>;

    fn emit_log(&self, record: LogRecord) -> BoxFuture<'_, Result<(), PlatformError>>;

    fn emit_span(&self, record: SpanRecord) -> BoxFuture<'_, Result<(), PlatformError>>;
}

pub trait ActivationObserver: Send + Sync {
    /// Nonblocking observation of a committed lifecycle transition. The context
    /// deliberately excludes payloads, claims, baggage, and diagnostic messages.
    fn on_observation(&self, context: &ActivationObservationContext, event: &ActivationObservation);
}
