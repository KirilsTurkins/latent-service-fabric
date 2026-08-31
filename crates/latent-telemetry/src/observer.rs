use std::collections::{HashMap, VecDeque};
use std::sync::{Arc, Mutex, MutexGuard};
use std::time::{SystemTime, UNIX_EPOCH};

use latent_activation::{ActivationEnvelope, ActivationEvent, ActivationOutcome, TraceContext};
use latent_core::{
    ActivationId, ActivationPhase, BudgetConsumption, Metadata, PlatformError, PlatformErrorCode,
};

use crate::{
    ActivationObserver, LogRecord, LogSeverity, MetricKind, MetricPoint, SpanRecord,
    TelemetryHandle,
};

const REDACTED: &str = "[REDACTED]";
const MAX_CORRELATION_VALUE_BYTES: usize = 256;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ActivationLifecycleStage {
    Receipt,
    Resolution,
    Admission,
    Queueing,
    Materialization,
    Execution,
    Cancellation,
    Failure,
    Completion,
    Cleanup,
}

impl ActivationLifecycleStage {
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Receipt => "receipt",
            Self::Resolution => "resolution",
            Self::Admission => "admission",
            Self::Queueing => "queueing",
            Self::Materialization => "materialization",
            Self::Execution => "execution",
            Self::Cancellation => "cancellation",
            Self::Failure => "failure",
            Self::Completion => "completion",
            Self::Cleanup => "cleanup",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ActivationLifecycleEvent {
    pub activation_id: ActivationId,
    pub stage: ActivationLifecycleStage,
    pub occurred_at_unix_millis: u64,
    pub duration_micros: Option<u64>,
    pub attributes: Metadata,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ActivationOutcomeClass {
    GuestSuccess,
    GuestDomainError,
    PlatformFailure,
}

impl ActivationOutcomeClass {
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::GuestSuccess => "guest_success",
            Self::GuestDomainError => "guest_domain_error",
            Self::PlatformFailure => "platform_failure",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ActivationCorrelation {
    pub activation_id: ActivationId,
    pub tenant: String,
    pub service: String,
    pub release: Option<String>,
    pub revision: Option<String>,
    pub route_generation: Option<u64>,
    pub trace: TraceContext,
    pub received_at_unix_millis: u64,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct GuestLogRecord {
    pub activation_id: ActivationId,
    pub severity: LogSeverity,
    pub body: String,
    pub fields: Metadata,
    pub observed_at_unix_millis: u64,
}

pub trait GuestLogObserver: Send + Sync {
    fn on_guest_log(&self, record: GuestLogRecord);
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SharedActivationObserverConfig {
    pub maximum_active_correlations: usize,
    pub maximum_log_body_bytes: usize,
    pub maximum_log_fields: usize,
    pub maximum_field_name_bytes: usize,
    pub maximum_field_value_bytes: usize,
    pub domain_error_media_types: Vec<String>,
}

impl Default for SharedActivationObserverConfig {
    fn default() -> Self {
        Self {
            maximum_active_correlations: 4_096,
            maximum_log_body_bytes: 1_024,
            maximum_log_fields: 24,
            maximum_field_name_bytes: 64,
            maximum_field_value_bytes: 256,
            domain_error_media_types: Vec::new(),
        }
    }
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct ObserverSnapshot {
    pub active_correlations: usize,
    pub received: u64,
    pub completed: u64,
    pub evicted_correlations: u64,
    pub guest_logs: u64,
}

#[derive(Debug, Clone)]
struct CorrelationState {
    correlation: ActivationCorrelation,
    last_observed_unix_millis: u64,
}

#[derive(Debug, Default)]
struct ObserverState {
    correlations: HashMap<ActivationId, CorrelationState>,
    insertion_order: VecDeque<ActivationId>,
    received: u64,
    completed: u64,
    evicted_correlations: u64,
    guest_logs: u64,
}

#[derive(Debug, Clone)]
pub struct SharedActivationObserver {
    telemetry: TelemetryHandle,
    config: SharedActivationObserverConfig,
    state: Arc<Mutex<ObserverState>>,
}

impl SharedActivationObserver {
    pub fn new(
        telemetry: TelemetryHandle,
        config: SharedActivationObserverConfig,
    ) -> Result<Self, PlatformError> {
        if config.maximum_active_correlations == 0
            || config.maximum_log_body_bytes == 0
            || config.maximum_log_fields == 0
            || config.maximum_field_name_bytes == 0
            || config.maximum_field_value_bytes == 0
        {
            return Err(observer_error(
                PlatformErrorCode::InvalidArgument,
                "activation observer bounds must be non-zero",
            ));
        }
        Ok(Self {
            telemetry,
            config,
            state: Arc::new(Mutex::new(ObserverState::default())),
        })
    }

    #[must_use]
    pub fn snapshot(&self) -> ObserverSnapshot {
        let state = self.lock_state();
        ObserverSnapshot {
            active_correlations: state.correlations.len(),
            received: state.received,
            completed: state.completed,
            evicted_correlations: state.evicted_correlations,
            guest_logs: state.guest_logs,
        }
    }

    #[must_use]
    pub fn correlation(&self, activation_id: &ActivationId) -> Option<ActivationCorrelation> {
        self.lock_state()
            .correlations
            .get(activation_id)
            .map(|state| state.correlation.clone())
    }

    fn register(&self, envelope: &ActivationEnvelope, observed_at: u64) {
        let resolved = envelope.resolved_revision.as_ref();
        let correlation = ActivationCorrelation {
            activation_id: envelope.activation_id.clone(),
            tenant: bounded(&envelope.target.tenant.0, MAX_CORRELATION_VALUE_BYTES),
            service: bounded(&envelope.target.service.0, MAX_CORRELATION_VALUE_BYTES),
            release: resolved
                .map(|revision| bounded(&revision.release.0, MAX_CORRELATION_VALUE_BYTES)),
            revision: resolved
                .map(|revision| bounded(&revision.revision.0, MAX_CORRELATION_VALUE_BYTES)),
            route_generation: resolved.map(|revision| revision.route_generation.0),
            trace: sanitized_trace(&envelope.trace, &self.config),
            received_at_unix_millis: observed_at,
        };
        let mut state = self.lock_state();
        state.received = state.received.saturating_add(1);
        if state.correlations.contains_key(&envelope.activation_id) {
            remove_from_order(&mut state.insertion_order, &envelope.activation_id);
        }
        while state.correlations.len() >= self.config.maximum_active_correlations {
            let Some(evicted) = state.insertion_order.pop_front() else {
                break;
            };
            if state.correlations.remove(&evicted).is_some() {
                state.evicted_correlations = state.evicted_correlations.saturating_add(1);
            }
        }
        state
            .insertion_order
            .push_back(envelope.activation_id.clone());
        state.correlations.insert(
            envelope.activation_id.clone(),
            CorrelationState {
                correlation,
                last_observed_unix_millis: observed_at,
            },
        );
    }

    fn lifecycle(&self, event: &ActivationLifecycleEvent) {
        let correlation = {
            let mut state = self.lock_state();
            let correlation = state
                .correlations
                .get(&event.activation_id)
                .map(|state| state.correlation.clone());
            if let Some(current) = state.correlations.get_mut(&event.activation_id) {
                current.last_observed_unix_millis = event.occurred_at_unix_millis;
            }
            correlation
        };

        let metric_attributes =
            Metadata::from([("stage".to_owned(), event.stage.as_str().to_owned())]);
        self.emit_metric(
            "latent.activation.lifecycle.events",
            MetricKind::Counter,
            1.0,
            "1",
            metric_attributes.clone(),
            event.occurred_at_unix_millis,
        );
        if let Some(duration) = event.duration_micros {
            self.emit_metric(
                "latent.activation.lifecycle.duration",
                MetricKind::Histogram,
                duration as f64,
                "us",
                metric_attributes,
                event.occurred_at_unix_millis,
            );
        }

        let Some(correlation) = correlation else {
            return;
        };
        let mut attributes = correlation_attributes(&correlation);
        attributes.insert("stage".to_owned(), event.stage.as_str().to_owned());
        for (name, value) in lifecycle_attributes(&event.attributes, &self.config) {
            attributes.insert(name, value);
        }
        let _ = self.telemetry.try_emit_log(LogRecord {
            severity: lifecycle_severity(event.stage),
            body: format!("activation lifecycle: {}", event.stage.as_str()),
            trace: Some(correlation.trace.clone()),
            attributes: attributes.clone(),
            observed_at_unix_millis: event.occurred_at_unix_millis,
        });
        let ended = event.occurred_at_unix_millis.saturating_mul(1_000_000);
        let started = event.duration_micros.map_or(ended, |duration| {
            ended.saturating_sub(duration.saturating_mul(1_000))
        });
        let _ = self.telemetry.try_emit_span(SpanRecord {
            name: format!("latent.activation.{}", event.stage.as_str()),
            trace: correlation.trace,
            parent_span_id: None,
            started_at_unix_nanos: started,
            ended_at_unix_nanos: ended,
            status: "ok".to_owned(),
            attributes,
        });
    }

    fn finish(&self, activation_id: &ActivationId, outcome: &ActivationOutcome) {
        let observed_at = now_unix_millis();
        let correlation = {
            let mut state = self.lock_state();
            state.completed = state.completed.saturating_add(1);
            remove_from_order(&mut state.insertion_order, activation_id);
            state
                .correlations
                .remove(activation_id)
                .map(|state| state.correlation)
        };
        let outcome_class = classify_outcome(outcome, &self.config.domain_error_media_types);
        let mut outcome_attributes =
            Metadata::from([("outcome".to_owned(), outcome_class.as_str().to_owned())]);
        if let ActivationOutcome::Failed { error, .. } = outcome {
            outcome_attributes.insert(
                "error_code".to_owned(),
                error_code_name(error.code).to_owned(),
            );
        }
        self.emit_metric(
            "latent.activation.outcomes",
            MetricKind::Counter,
            1.0,
            "1",
            outcome_attributes.clone(),
            observed_at,
        );
        emit_consumption_metrics(
            &self.telemetry,
            outcome_consumption(outcome),
            outcome_class,
            observed_at,
        );

        let Some(correlation) = correlation else {
            return;
        };
        let latency_micros = observed_at
            .saturating_sub(correlation.received_at_unix_millis)
            .saturating_mul(1_000);
        self.emit_metric(
            "latent.activation.latency",
            MetricKind::Histogram,
            latency_micros as f64,
            "us",
            outcome_attributes,
            observed_at,
        );
        let mut attributes = correlation_attributes(&correlation);
        attributes.insert("outcome".to_owned(), outcome_class.as_str().to_owned());
        add_consumption_attributes(&mut attributes, outcome_consumption(outcome));
        if let ActivationOutcome::Failed {
            terminal_state,
            error,
            ..
        } = outcome
        {
            attributes.insert(
                "terminal_state".to_owned(),
                bounded(&format!("{terminal_state:?}"), MAX_CORRELATION_VALUE_BYTES),
            );
            attributes.insert(
                "error_code".to_owned(),
                error_code_name(error.code).to_owned(),
            );
            self.lifecycle(&ActivationLifecycleEvent {
                activation_id: activation_id.clone(),
                stage: ActivationLifecycleStage::Failure,
                occurred_at_unix_millis: observed_at,
                duration_micros: None,
                attributes: Metadata::from([(
                    "error_code".to_owned(),
                    error_code_name(error.code).to_owned(),
                )]),
            });
        }
        let _ = self.telemetry.try_emit_log(LogRecord {
            severity: match outcome_class {
                ActivationOutcomeClass::GuestSuccess => LogSeverity::Info,
                ActivationOutcomeClass::GuestDomainError => LogSeverity::Warn,
                ActivationOutcomeClass::PlatformFailure => LogSeverity::Error,
            },
            body: "activation completed".to_owned(),
            trace: Some(correlation.trace.clone()),
            attributes: attributes.clone(),
            observed_at_unix_millis: observed_at,
        });
        let _ = self.telemetry.try_emit_span(SpanRecord {
            name: "latent.activation".to_owned(),
            trace: correlation.trace,
            parent_span_id: None,
            started_at_unix_nanos: correlation
                .received_at_unix_millis
                .saturating_mul(1_000_000),
            ended_at_unix_nanos: observed_at.saturating_mul(1_000_000),
            status: outcome_class.as_str().to_owned(),
            attributes,
        });
    }

    fn emit_metric(
        &self,
        name: &str,
        kind: MetricKind,
        value: f64,
        unit: &str,
        attributes: Metadata,
        observed_at_unix_millis: u64,
    ) {
        let _ = self.telemetry.try_emit_metric(MetricPoint {
            name: name.to_owned(),
            kind,
            value,
            unit: unit.to_owned(),
            attributes,
            observed_at_unix_millis,
        });
    }

    fn lock_state(&self) -> MutexGuard<'_, ObserverState> {
        self.state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
    }
}

impl ActivationObserver for SharedActivationObserver {
    fn on_received(&self, envelope: &ActivationEnvelope) {
        let observed_at = now_unix_millis();
        self.register(envelope, observed_at);
        self.lifecycle(&ActivationLifecycleEvent {
            activation_id: envelope.activation_id.clone(),
            stage: ActivationLifecycleStage::Receipt,
            occurred_at_unix_millis: observed_at,
            duration_micros: None,
            attributes: Metadata::new(),
        });
        emit_budget_grant_metrics(&self.telemetry, &envelope.budget, observed_at);
    }

    fn on_event(&self, event: &ActivationEvent) {
        self.lifecycle(&ActivationLifecycleEvent {
            activation_id: event.activation_id.clone(),
            stage: stage_for_phase(event.phase),
            occurred_at_unix_millis: event.occurred_at_unix_millis,
            duration_micros: event
                .attributes
                .get("duration_micros")
                .and_then(|value| value.parse().ok()),
            attributes: event.attributes.clone(),
        });
    }

    fn on_lifecycle(&self, event: &ActivationLifecycleEvent) {
        self.lifecycle(event);
    }

    fn on_completed(&self, envelope: &ActivationEnvelope, outcome: &ActivationOutcome) {
        self.finish(&envelope.activation_id, outcome);
    }

    fn on_finalized(&self, activation_id: &ActivationId, outcome: &ActivationOutcome) {
        self.finish(activation_id, outcome);
    }

    fn on_cancel_requested(&self, activation_id: &ActivationId) {
        let observed_at = now_unix_millis();
        self.lifecycle(&ActivationLifecycleEvent {
            activation_id: activation_id.clone(),
            stage: ActivationLifecycleStage::Cancellation,
            occurred_at_unix_millis: observed_at,
            duration_micros: None,
            attributes: Metadata::new(),
        });
        self.emit_metric(
            "latent.activation.cancellations",
            MetricKind::Counter,
            1.0,
            "1",
            Metadata::new(),
            observed_at,
        );
    }
}

impl GuestLogObserver for SharedActivationObserver {
    fn on_guest_log(&self, record: GuestLogRecord) {
        let correlation = {
            let mut state = self.lock_state();
            state.guest_logs = state.guest_logs.saturating_add(1);
            state
                .correlations
                .get(&record.activation_id)
                .map(|state| state.correlation.clone())
        };
        let Some(correlation) = correlation else {
            return;
        };
        let mut attributes = correlation_attributes(&correlation);
        for (name, value) in sanitize_fields(&record.fields, &self.config) {
            attributes.insert(format!("guest.{name}"), value);
        }
        attributes.insert(
            "severity".to_owned(),
            severity_name(record.severity).to_owned(),
        );
        let body = sanitize_body(&record.body, self.config.maximum_log_body_bytes);
        let _ = self.telemetry.try_emit_log(LogRecord {
            severity: record.severity,
            body,
            trace: Some(correlation.trace),
            attributes,
            observed_at_unix_millis: record.observed_at_unix_millis,
        });
        self.emit_metric(
            "latent.guest.logs",
            MetricKind::Counter,
            1.0,
            "1",
            Metadata::from([(
                "severity".to_owned(),
                severity_name(record.severity).to_owned(),
            )]),
            record.observed_at_unix_millis,
        );
    }
}

#[derive(Debug, Clone, Copy, Default)]
pub struct NoopActivationObserver;

impl ActivationObserver for NoopActivationObserver {}
impl GuestLogObserver for NoopActivationObserver {
    fn on_guest_log(&self, _record: GuestLogRecord) {}
}

fn stage_for_phase(phase: ActivationPhase) -> ActivationLifecycleStage {
    match phase {
        ActivationPhase::Received => ActivationLifecycleStage::Receipt,
        ActivationPhase::Resolved => ActivationLifecycleStage::Resolution,
        ActivationPhase::Admitted => ActivationLifecycleStage::Admission,
        ActivationPhase::Queued => ActivationLifecycleStage::Queueing,
        ActivationPhase::Materializing => ActivationLifecycleStage::Materialization,
        ActivationPhase::Running
        | ActivationPhase::Suspended
        | ActivationPhase::PreparingCommit
        | ActivationPhase::Committed
        | ActivationPhase::EffectsPending => ActivationLifecycleStage::Execution,
        _ => ActivationLifecycleStage::Execution,
    }
}

fn classify_outcome(
    outcome: &ActivationOutcome,
    domain_error_media_types: &[String],
) -> ActivationOutcomeClass {
    match outcome {
        ActivationOutcome::Succeeded(success)
            if domain_error_media_types
                .iter()
                .any(|media_type| media_type == &success.output_media_type) =>
        {
            ActivationOutcomeClass::GuestDomainError
        }
        ActivationOutcome::Succeeded(_) => ActivationOutcomeClass::GuestSuccess,
        ActivationOutcome::Failed { .. } => ActivationOutcomeClass::PlatformFailure,
    }
}

fn outcome_consumption(outcome: &ActivationOutcome) -> &BudgetConsumption {
    match outcome {
        ActivationOutcome::Succeeded(success) => &success.consumption,
        ActivationOutcome::Failed { consumption, .. } => consumption,
    }
}

fn emit_budget_grant_metrics(
    telemetry: &TelemetryHandle,
    budget: &latent_core::ResourceBudget,
    observed_at: u64,
) {
    let grants = [
        ("cpu_fuel", budget.cpu_fuel as f64),
        ("memory_bytes", budget.memory_bytes as f64),
        ("child_calls", f64::from(budget.child_calls)),
        ("outbound_requests", f64::from(budget.outbound_requests)),
        ("state_read_bytes", budget.state_read_bytes as f64),
        ("state_write_bytes", budget.state_write_bytes as f64),
        ("blob_read_bytes", budget.blob_read_bytes as f64),
        ("blob_write_bytes", budget.blob_write_bytes as f64),
        ("log_bytes", budget.log_bytes as f64),
        ("effect_count", f64::from(budget.effect_count)),
    ];
    for (resource, value) in grants {
        let _ = telemetry.try_emit_metric(MetricPoint {
            name: "latent.activation.budget.granted".to_owned(),
            kind: MetricKind::Histogram,
            value,
            unit: "1".to_owned(),
            attributes: Metadata::from([("resource".to_owned(), resource.to_owned())]),
            observed_at_unix_millis: observed_at,
        });
    }
}

fn emit_consumption_metrics(
    telemetry: &TelemetryHandle,
    consumption: &BudgetConsumption,
    outcome: ActivationOutcomeClass,
    observed_at: u64,
) {
    let values = [
        ("cpu_fuel", consumption.cpu_fuel as f64),
        ("peak_memory_bytes", consumption.peak_memory_bytes as f64),
        ("wall_time_micros", consumption.wall_time_micros as f64),
        ("child_calls", f64::from(consumption.child_calls)),
        (
            "outbound_requests",
            f64::from(consumption.outbound_requests),
        ),
        ("state_read_bytes", consumption.state_read_bytes as f64),
        ("state_write_bytes", consumption.state_write_bytes as f64),
        ("blob_read_bytes", consumption.blob_read_bytes as f64),
        ("blob_write_bytes", consumption.blob_write_bytes as f64),
        ("log_bytes", consumption.log_bytes as f64),
        ("effect_count", f64::from(consumption.effect_count)),
    ];
    for (resource, value) in values {
        let _ = telemetry.try_emit_metric(MetricPoint {
            name: "latent.activation.budget.consumed".to_owned(),
            kind: MetricKind::Histogram,
            value,
            unit: "1".to_owned(),
            attributes: Metadata::from([
                ("resource".to_owned(), resource.to_owned()),
                ("outcome".to_owned(), outcome.as_str().to_owned()),
            ]),
            observed_at_unix_millis: observed_at,
        });
    }
}

fn add_consumption_attributes(attributes: &mut Metadata, consumption: &BudgetConsumption) {
    attributes.insert(
        "consumption.cpu_fuel".to_owned(),
        consumption.cpu_fuel.to_string(),
    );
    attributes.insert(
        "consumption.peak_memory_bytes".to_owned(),
        consumption.peak_memory_bytes.to_string(),
    );
    attributes.insert(
        "consumption.wall_time_micros".to_owned(),
        consumption.wall_time_micros.to_string(),
    );
    attributes.insert(
        "consumption.log_bytes".to_owned(),
        consumption.log_bytes.to_string(),
    );
}

fn correlation_attributes(correlation: &ActivationCorrelation) -> Metadata {
    let mut attributes = Metadata::from([
        (
            "activation_id".to_owned(),
            bounded(&correlation.activation_id.0, MAX_CORRELATION_VALUE_BYTES),
        ),
        ("tenant".to_owned(), correlation.tenant.clone()),
        ("service".to_owned(), correlation.service.clone()),
        (
            "trace_id".to_owned(),
            bounded(&correlation.trace.trace_id.0, MAX_CORRELATION_VALUE_BYTES),
        ),
    ]);
    if let Some(release) = &correlation.release {
        attributes.insert("release".to_owned(), release.clone());
    }
    if let Some(revision) = &correlation.revision {
        attributes.insert("revision".to_owned(), revision.clone());
    }
    if let Some(generation) = correlation.route_generation {
        attributes.insert("route_generation".to_owned(), generation.to_string());
    }
    attributes
}

fn lifecycle_attributes(
    attributes: &Metadata,
    config: &SharedActivationObserverConfig,
) -> Metadata {
    const ALLOWED: [&str; 6] = [
        "cell_class",
        "cleanup",
        "duration_micros",
        "error_code",
        "result",
        "reason_code",
    ];
    attributes
        .iter()
        .filter(|(name, _)| ALLOWED.contains(&name.as_str()))
        .take(config.maximum_log_fields)
        .map(|(name, value)| {
            (
                bounded(name, config.maximum_field_name_bytes),
                bounded(value, config.maximum_field_value_bytes),
            )
        })
        .collect()
}

fn sanitize_fields(fields: &Metadata, config: &SharedActivationObserverConfig) -> Metadata {
    fields
        .iter()
        .take(config.maximum_log_fields)
        .map(|(name, value)| {
            let normalized_name = bounded(name, config.maximum_field_name_bytes);
            let normalized_value = if sensitive_name(name) {
                REDACTED.to_owned()
            } else {
                bounded(value, config.maximum_field_value_bytes)
            };
            (normalized_name, normalized_value)
        })
        .collect()
}

fn sanitize_body(body: &str, maximum_bytes: usize) -> String {
    let lower = body.to_ascii_lowercase();
    const MARKERS: [&str; 10] = [
        "authorization:",
        "bearer ",
        "password=",
        "password:",
        "secret=",
        "api_key=",
        "apikey=",
        "private key",
        "cookie:",
        "session=",
    ];
    if MARKERS.iter().any(|marker| lower.contains(marker)) {
        REDACTED.to_owned()
    } else {
        bounded(body, maximum_bytes)
    }
}

fn sensitive_name(name: &str) -> bool {
    let lower = name.to_ascii_lowercase();
    [
        "authorization",
        "credential",
        "cookie",
        "password",
        "secret",
        "token",
        "api_key",
        "apikey",
        "private_key",
        "session",
    ]
    .iter()
    .any(|marker| lower.contains(marker))
}

fn sanitized_trace(trace: &TraceContext, config: &SharedActivationObserverConfig) -> TraceContext {
    TraceContext {
        trace_id: latent_core::TraceId(bounded(
            &trace.trace_id.0,
            config.maximum_field_value_bytes,
        )),
        span_id: latent_core::SpanId(bounded(&trace.span_id.0, config.maximum_field_value_bytes)),
        trace_flags: trace.trace_flags,
        baggage: Metadata::new(),
    }
}

fn lifecycle_severity(stage: ActivationLifecycleStage) -> LogSeverity {
    match stage {
        ActivationLifecycleStage::Cancellation => LogSeverity::Warn,
        ActivationLifecycleStage::Failure => LogSeverity::Error,
        _ => LogSeverity::Info,
    }
}

fn severity_name(severity: LogSeverity) -> &'static str {
    match severity {
        LogSeverity::Trace => "trace",
        LogSeverity::Debug => "debug",
        LogSeverity::Info => "info",
        LogSeverity::Warn => "warn",
        LogSeverity::Error => "error",
        LogSeverity::Fatal => "fatal",
    }
}

fn error_code_name(code: PlatformErrorCode) -> &'static str {
    match code {
        PlatformErrorCode::Unavailable => "unavailable",
        PlatformErrorCode::DeadlineExceeded => "deadline_exceeded",
        PlatformErrorCode::Cancelled => "cancelled",
        PlatformErrorCode::ResourceExhausted => "resource_exhausted",
        PlatformErrorCode::PermissionDenied => "permission_denied",
        PlatformErrorCode::Unauthenticated => "unauthenticated",
        PlatformErrorCode::InvalidArgument => "invalid_argument",
        PlatformErrorCode::NotFound => "not_found",
        PlatformErrorCode::AlreadyExists => "already_exists",
        PlatformErrorCode::IncompatibleContract => "incompatible_contract",
        PlatformErrorCode::StateConflict => "state_conflict",
        PlatformErrorCode::DependencyFailed => "dependency_failed",
        PlatformErrorCode::GuestTrap => "guest_trap",
        PlatformErrorCode::CorruptArtifact => "corrupt_artifact",
        PlatformErrorCode::RouteUnavailable => "route_unavailable",
        PlatformErrorCode::AdmissionRejected => "admission_rejected",
        PlatformErrorCode::Internal => "internal",
        _ => "unknown",
    }
}

fn remove_from_order(order: &mut VecDeque<ActivationId>, activation_id: &ActivationId) {
    if let Some(position) = order
        .iter()
        .position(|candidate| candidate == activation_id)
    {
        order.remove(position);
    }
}

fn now_unix_millis() -> u64 {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis();
    u64::try_from(millis).unwrap_or(u64::MAX)
}

fn bounded(value: &str, maximum_bytes: usize) -> String {
    if value.len() <= maximum_bytes {
        return value.to_owned();
    }
    let mut end = maximum_bytes;
    while !value.is_char_boundary(end) {
        end = end.saturating_sub(1);
    }
    value[..end].to_owned()
}

fn observer_error(code: PlatformErrorCode, message: &str) -> PlatformError {
    PlatformError {
        code,
        message: message.to_owned(),
        retryable: false,
        details: Vec::new(),
    }
}
