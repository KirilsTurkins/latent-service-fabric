#![allow(clippy::cast_precision_loss, clippy::too_many_lines)]

use std::collections::{HashMap, VecDeque};
use std::sync::{Arc, Mutex, MutexGuard};
use std::time::{SystemTime, UNIX_EPOCH};

use latent_activation::{ActivationEnvelope, ActivationEvent, ActivationOutcome, TraceContext};
use latent_core::{
    ActivationId, ActivationPhase, BudgetConsumption, Metadata, PlatformError, PlatformErrorCode,
    ResourceBudget,
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
    fn on_guest_log(&self, record: GuestLogRecord) -> Result<(), PlatformError>;
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SharedActivationObserverConfig {
    pub maximum_active_correlations: usize,
    pub maximum_log_body_bytes: usize,
    pub maximum_log_fields: usize,
    pub maximum_field_name_bytes: usize,
    pub maximum_field_value_bytes: usize,
    /// Guest message bodies are treated as raw payload-like data and are hidden
    /// unless an operator explicitly enables bounded body export.
    pub export_guest_log_bodies: bool,
    /// Guest field values are hidden by default. Only exact, explicitly
    /// allow-listed names may export a bounded value.
    pub allowed_guest_field_names: Vec<String>,
}

impl Default for SharedActivationObserverConfig {
    fn default() -> Self {
        Self {
            maximum_active_correlations: 4_096,
            maximum_log_body_bytes: 1_024,
            maximum_log_fields: 24,
            maximum_field_name_bytes: 64,
            maximum_field_value_bytes: 256,
            export_guest_log_bodies: false,
            allowed_guest_field_names: Vec::new(),
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
    granted_budget: ResourceBudget,
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
            || config
                .allowed_guest_field_names
                .iter()
                .any(|name| name.is_empty() || name.len() > config.maximum_field_name_bytes)
        {
            return Err(observer_error(
                PlatformErrorCode::InvalidArgument,
                "activation observer bounds and guest-field allow-list must be valid",
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
                granted_budget: envelope.budget.clone(),
                last_observed_unix_millis: observed_at,
            },
        );
    }

    fn unregister(&self, activation_id: &ActivationId) {
        let mut state = self.lock_state();
        remove_from_order(&mut state.insertion_order, activation_id);
        state.correlations.remove(activation_id);
    }

    fn lifecycle(&self, event: &ActivationLifecycleEvent) -> Result<(), PlatformError> {
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
        let mut first_error = None;
        collect_error(
            &mut first_error,
            self.emit_metric(
                "latent.activation.lifecycle.events",
                MetricKind::Counter,
                1.0,
                "1",
                metric_attributes.clone(),
                event.occurred_at_unix_millis,
            ),
        );
        if let Some(duration) = event.duration_micros {
            collect_error(
                &mut first_error,
                self.emit_metric(
                    "latent.activation.lifecycle.duration",
                    MetricKind::Histogram,
                    duration as f64,
                    "us",
                    metric_attributes,
                    event.occurred_at_unix_millis,
                ),
            );
        }

        if let Some(correlation) = correlation {
            let mut attributes = correlation_attributes(&correlation);
            attributes.insert("stage".to_owned(), event.stage.as_str().to_owned());
            for (name, value) in lifecycle_attributes(&event.attributes, &self.config) {
                attributes.insert(name, value);
            }
            collect_error(
                &mut first_error,
                self.telemetry
                    .try_emit_log(LogRecord {
                        severity: lifecycle_severity(event.stage),
                        body: format!("activation lifecycle: {}", event.stage.as_str()),
                        trace: Some(correlation.trace.clone()),
                        attributes: attributes.clone(),
                        observed_at_unix_millis: event.occurred_at_unix_millis,
                    })
                    .map(|_| ()),
            );
            let ended = event.occurred_at_unix_millis.saturating_mul(1_000_000);
            let started = event.duration_micros.map_or(ended, |duration| {
                ended.saturating_sub(duration.saturating_mul(1_000))
            });
            collect_error(
                &mut first_error,
                self.telemetry
                    .try_emit_span(SpanRecord {
                        name: format!("latent.activation.{}", event.stage.as_str()),
                        trace: correlation.trace,
                        parent_span_id: None,
                        started_at_unix_nanos: started,
                        ended_at_unix_nanos: ended,
                        status: lifecycle_status(event.stage, &event.attributes).to_owned(),
                        attributes,
                    })
                    .map(|_| ()),
            );
        }

        first_error.map_or(Ok(()), Err)
    }

    fn finish(
        &self,
        activation_id: &ActivationId,
        outcome: &ActivationOutcome,
    ) -> Result<(), PlatformError> {
        let observed_at = now_unix_millis();
        let correlation_state = {
            let mut state = self.lock_state();
            let current = state.correlations.get(activation_id).cloned();
            if current.is_some() {
                state.completed = state.completed.saturating_add(1);
            }
            current
        };
        let outcome_class = classify_outcome(outcome);
        let mut outcome_attributes =
            Metadata::from([("outcome".to_owned(), outcome_class.as_str().to_owned())]);
        if let ActivationOutcome::Failed { error, .. } = outcome {
            outcome_attributes.insert(
                "error_code".to_owned(),
                error_code_name(error.code).to_owned(),
            );
        }

        let mut first_error = None;
        collect_error(
            &mut first_error,
            self.emit_metric(
                "latent.activation.outcomes",
                MetricKind::Counter,
                1.0,
                "1",
                outcome_attributes.clone(),
                observed_at,
            ),
        );
        collect_error(
            &mut first_error,
            emit_consumption_metrics(
                &self.telemetry,
                outcome_consumption(outcome),
                outcome_class,
                observed_at,
            ),
        );
        if let Some(state) = &correlation_state {
            collect_error(
                &mut first_error,
                emit_budget_exhaustion_metrics(
                    &self.telemetry,
                    &state.granted_budget,
                    outcome_consumption(outcome),
                    outcome_class,
                    observed_at,
                ),
            );
        }

        if !matches!(outcome_class, ActivationOutcomeClass::GuestSuccess) {
            let mut attributes =
                Metadata::from([("outcome".to_owned(), outcome_class.as_str().to_owned())]);
            if let ActivationOutcome::Failed { error, .. } = outcome {
                attributes.insert(
                    "error_code".to_owned(),
                    error_code_name(error.code).to_owned(),
                );
            }
            collect_error(
                &mut first_error,
                self.lifecycle(&ActivationLifecycleEvent {
                    activation_id: activation_id.clone(),
                    stage: ActivationLifecycleStage::Failure,
                    occurred_at_unix_millis: observed_at,
                    duration_micros: None,
                    attributes,
                }),
            );
        }

        collect_error(
            &mut first_error,
            self.lifecycle(&ActivationLifecycleEvent {
                activation_id: activation_id.clone(),
                stage: ActivationLifecycleStage::Completion,
                occurred_at_unix_millis: observed_at,
                duration_micros: None,
                attributes: Metadata::from([(
                    "outcome".to_owned(),
                    outcome_class.as_str().to_owned(),
                )]),
            }),
        );

        if let Some(state) = correlation_state {
            let correlation = state.correlation;
            let latency_micros = observed_at
                .saturating_sub(correlation.received_at_unix_millis)
                .saturating_mul(1_000);
            collect_error(
                &mut first_error,
                self.emit_metric(
                    "latent.activation.latency",
                    MetricKind::Histogram,
                    latency_micros as f64,
                    "us",
                    outcome_attributes,
                    observed_at,
                ),
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
            }
            collect_error(
                &mut first_error,
                self.telemetry
                    .try_emit_log(LogRecord {
                        severity: match outcome_class {
                            ActivationOutcomeClass::GuestSuccess => LogSeverity::Info,
                            ActivationOutcomeClass::GuestDomainError => LogSeverity::Warn,
                            ActivationOutcomeClass::PlatformFailure => LogSeverity::Error,
                        },
                        body: "activation completed".to_owned(),
                        trace: Some(correlation.trace.clone()),
                        attributes: attributes.clone(),
                        observed_at_unix_millis: observed_at,
                    })
                    .map(|_| ()),
            );
            collect_error(
                &mut first_error,
                self.telemetry
                    .try_emit_span(SpanRecord {
                        name: "latent.activation".to_owned(),
                        trace: correlation.trace,
                        parent_span_id: None,
                        started_at_unix_nanos: correlation
                            .received_at_unix_millis
                            .saturating_mul(1_000_000),
                        ended_at_unix_nanos: observed_at.saturating_mul(1_000_000),
                        status: outcome_status(outcome_class).to_owned(),
                        attributes,
                    })
                    .map(|_| ()),
            );
        }

        // Correlation must remain live through failure and completion emission.
        // It is removed only after all correlated terminal records were attempted.
        self.unregister(activation_id);
        first_error.map_or(Ok(()), Err)
    }

    fn emit_metric(
        &self,
        name: &str,
        kind: MetricKind,
        value: f64,
        unit: &str,
        attributes: Metadata,
        observed_at_unix_millis: u64,
    ) -> Result<(), PlatformError> {
        self.telemetry
            .try_emit_metric(MetricPoint {
                name: name.to_owned(),
                kind,
                value,
                unit: unit.to_owned(),
                attributes,
                observed_at_unix_millis,
            })
            .map(|_| ())
    }

    fn lock_state(&self) -> MutexGuard<'_, ObserverState> {
        self.state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
    }
}

impl ActivationObserver for SharedActivationObserver {
    fn on_received(&self, envelope: &ActivationEnvelope) -> Result<(), PlatformError> {
        let observed_at = now_unix_millis();
        self.register(envelope, observed_at);
        let mut first_error = None;
        collect_error(
            &mut first_error,
            self.lifecycle(&ActivationLifecycleEvent {
                activation_id: envelope.activation_id.clone(),
                stage: ActivationLifecycleStage::Receipt,
                occurred_at_unix_millis: observed_at,
                duration_micros: None,
                attributes: Metadata::new(),
            }),
        );
        collect_error(
            &mut first_error,
            emit_budget_grant_metrics(&self.telemetry, &envelope.budget, observed_at),
        );
        if let Some(error) = first_error {
            self.unregister(&envelope.activation_id);
            Err(error)
        } else {
            Ok(())
        }
    }

    fn on_event(&self, event: &ActivationEvent) -> Result<(), PlatformError> {
        self.lifecycle(&ActivationLifecycleEvent {
            activation_id: event.activation_id.clone(),
            stage: stage_for_phase(event.phase),
            occurred_at_unix_millis: event.occurred_at_unix_millis,
            duration_micros: event
                .attributes
                .get("duration_micros")
                .and_then(|value| value.parse().ok()),
            attributes: event.attributes.clone(),
        })
    }

    fn on_lifecycle(&self, event: &ActivationLifecycleEvent) -> Result<(), PlatformError> {
        self.lifecycle(event)
    }

    fn on_completed(
        &self,
        envelope: &ActivationEnvelope,
        outcome: &ActivationOutcome,
    ) -> Result<(), PlatformError> {
        self.finish(&envelope.activation_id, outcome)
    }

    fn on_finalized(
        &self,
        activation_id: &ActivationId,
        outcome: &ActivationOutcome,
    ) -> Result<(), PlatformError> {
        self.finish(activation_id, outcome)
    }

    fn on_cancel_requested(&self, activation_id: &ActivationId) -> Result<(), PlatformError> {
        let observed_at = now_unix_millis();
        let mut first_error = None;
        collect_error(
            &mut first_error,
            self.lifecycle(&ActivationLifecycleEvent {
                activation_id: activation_id.clone(),
                stage: ActivationLifecycleStage::Cancellation,
                occurred_at_unix_millis: observed_at,
                duration_micros: None,
                attributes: Metadata::new(),
            }),
        );
        collect_error(
            &mut first_error,
            self.emit_metric(
                "latent.activation.cancellations",
                MetricKind::Counter,
                1.0,
                "1",
                Metadata::new(),
                observed_at,
            ),
        );
        first_error.map_or(Ok(()), Err)
    }
}

impl GuestLogObserver for SharedActivationObserver {
    fn on_guest_log(&self, record: GuestLogRecord) -> Result<(), PlatformError> {
        let correlation = {
            let mut state = self.lock_state();
            state.guest_logs = state.guest_logs.saturating_add(1);
            state
                .correlations
                .get(&record.activation_id)
                .map(|state| state.correlation.clone())
        };
        let Some(correlation) = correlation else {
            return Ok(());
        };
        let mut attributes = correlation_attributes(&correlation);
        for (name, value) in sanitize_fields(&record.fields, &self.config) {
            attributes.insert(format!("guest.{name}"), value);
        }
        attributes.insert(
            "severity".to_owned(),
            severity_name(record.severity).to_owned(),
        );
        let body = sanitize_body(&record.body, &self.config);
        let mut first_error = None;
        collect_error(
            &mut first_error,
            self.telemetry
                .try_emit_log(LogRecord {
                    severity: record.severity,
                    body,
                    trace: Some(correlation.trace),
                    attributes,
                    observed_at_unix_millis: record.observed_at_unix_millis,
                })
                .map(|_| ()),
        );
        collect_error(
            &mut first_error,
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
            ),
        );
        first_error.map_or(Ok(()), Err)
    }
}

#[derive(Debug, Clone, Copy, Default)]
pub struct NoopActivationObserver;

impl ActivationObserver for NoopActivationObserver {}
impl GuestLogObserver for NoopActivationObserver {
    fn on_guest_log(&self, _record: GuestLogRecord) -> Result<(), PlatformError> {
        Ok(())
    }
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

fn classify_outcome(outcome: &ActivationOutcome) -> ActivationOutcomeClass {
    match outcome {
        ActivationOutcome::Succeeded(_) => ActivationOutcomeClass::GuestSuccess,
        ActivationOutcome::DeclaredError { .. } => ActivationOutcomeClass::GuestDomainError,
        ActivationOutcome::Failed { .. } => ActivationOutcomeClass::PlatformFailure,
    }
}

fn outcome_consumption(outcome: &ActivationOutcome) -> &BudgetConsumption {
    match outcome {
        ActivationOutcome::Succeeded(success) => &success.consumption,
        ActivationOutcome::DeclaredError { consumption, .. }
        | ActivationOutcome::Failed { consumption, .. } => consumption,
    }
}

fn emit_budget_grant_metrics(
    telemetry: &TelemetryHandle,
    budget: &ResourceBudget,
    observed_at: u64,
) -> Result<(), PlatformError> {
    let mut grants = vec![
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
    if let Some(wall_time_limit_millis) = budget.wall_time_limit_millis {
        grants.push((
            "wall_time_micros",
            wall_time_limit_millis.saturating_mul(1_000) as f64,
        ));
    }
    emit_resource_metrics(
        telemetry,
        "latent.activation.budget.granted",
        MetricKind::Histogram,
        &grants,
        None,
        observed_at,
    )
}

fn emit_consumption_metrics(
    telemetry: &TelemetryHandle,
    consumption: &BudgetConsumption,
    outcome: ActivationOutcomeClass,
    observed_at: u64,
) -> Result<(), PlatformError> {
    let values = consumption_values(consumption);
    emit_resource_metrics(
        telemetry,
        "latent.activation.budget.consumed",
        MetricKind::Histogram,
        &values,
        Some(outcome),
        observed_at,
    )
}

fn emit_budget_exhaustion_metrics(
    telemetry: &TelemetryHandle,
    budget: &ResourceBudget,
    consumption: &BudgetConsumption,
    outcome: ActivationOutcomeClass,
    observed_at: u64,
) -> Result<(), PlatformError> {
    let mut exhausted = vec![
        ("cpu_fuel", reached(consumption.cpu_fuel, budget.cpu_fuel)),
        (
            "memory_bytes",
            reached(consumption.peak_memory_bytes, budget.memory_bytes),
        ),
        (
            "child_calls",
            reached(
                u64::from(consumption.child_calls),
                u64::from(budget.child_calls),
            ),
        ),
        (
            "outbound_requests",
            reached(
                u64::from(consumption.outbound_requests),
                u64::from(budget.outbound_requests),
            ),
        ),
        (
            "state_read_bytes",
            reached(consumption.state_read_bytes, budget.state_read_bytes),
        ),
        (
            "state_write_bytes",
            reached(consumption.state_write_bytes, budget.state_write_bytes),
        ),
        (
            "blob_read_bytes",
            reached(consumption.blob_read_bytes, budget.blob_read_bytes),
        ),
        (
            "blob_write_bytes",
            reached(consumption.blob_write_bytes, budget.blob_write_bytes),
        ),
        (
            "log_bytes",
            reached(consumption.log_bytes, budget.log_bytes),
        ),
        (
            "effect_count",
            reached(
                u64::from(consumption.effect_count),
                u64::from(budget.effect_count),
            ),
        ),
    ];
    if let Some(limit_millis) = budget.wall_time_limit_millis {
        exhausted.push((
            "wall_time_micros",
            reached(
                consumption.wall_time_micros,
                limit_millis.saturating_mul(1_000),
            ),
        ));
    }

    let mut first_error = None;
    for (resource, _) in exhausted
        .into_iter()
        .filter(|(_, was_exhausted)| *was_exhausted)
    {
        collect_error(
            &mut first_error,
            telemetry
                .try_emit_metric(MetricPoint {
                    name: "latent.activation.budget.exhausted".to_owned(),
                    kind: MetricKind::Counter,
                    value: 1.0,
                    unit: "1".to_owned(),
                    attributes: Metadata::from([
                        ("resource".to_owned(), resource.to_owned()),
                        ("outcome".to_owned(), outcome.as_str().to_owned()),
                    ]),
                    observed_at_unix_millis: observed_at,
                })
                .map(|_| ()),
        );
    }
    first_error.map_or(Ok(()), Err)
}

fn consumption_values(consumption: &BudgetConsumption) -> Vec<(&'static str, f64)> {
    vec![
        ("cpu_fuel", consumption.cpu_fuel as f64),
        ("memory_bytes", consumption.peak_memory_bytes as f64),
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
    ]
}

fn emit_resource_metrics(
    telemetry: &TelemetryHandle,
    name: &str,
    kind: MetricKind,
    values: &[(&str, f64)],
    outcome: Option<ActivationOutcomeClass>,
    observed_at: u64,
) -> Result<(), PlatformError> {
    let mut first_error = None;
    for (resource, value) in values {
        let mut attributes = Metadata::from([("resource".to_owned(), (*resource).to_owned())]);
        if let Some(outcome) = outcome {
            attributes.insert("outcome".to_owned(), outcome.as_str().to_owned());
        }
        collect_error(
            &mut first_error,
            telemetry
                .try_emit_metric(MetricPoint {
                    name: name.to_owned(),
                    kind,
                    value: *value,
                    unit: "1".to_owned(),
                    attributes,
                    observed_at_unix_millis: observed_at,
                })
                .map(|_| ()),
        );
    }
    first_error.map_or(Ok(()), Err)
}

fn reached(consumed: u64, granted: u64) -> bool {
    consumed > 0 && consumed >= granted
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
    const ALLOWED: [&str; 8] = [
        "cell_class",
        "cleanup",
        "duration_micros",
        "error_code",
        "outcome",
        "result",
        "reason_code",
        "resolution",
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
        .enumerate()
        .map(|(index, (name, value))| {
            let permitted = config
                .allowed_guest_field_names
                .iter()
                .any(|allowed| allowed == name)
                && !sensitive_field_name(name);
            let normalized_name = if permitted {
                bounded(name, config.maximum_field_name_bytes)
            } else {
                format!("redacted_field_{index}")
            };
            let normalized_value = if permitted && !sensitive_text(value) {
                bounded(value, config.maximum_field_value_bytes)
            } else {
                REDACTED.to_owned()
            };
            (normalized_name, normalized_value)
        })
        .collect()
}

fn sensitive_field_name(name: &str) -> bool {
    let canonical = name
        .chars()
        .filter(char::is_ascii_alphanumeric)
        .flat_map(char::to_lowercase)
        .collect::<String>();
    const MARKERS: [&str; 14] = [
        "authorization",
        "credential",
        "password",
        "passwd",
        "secret",
        "token",
        "apikey",
        "accesskey",
        "privatekey",
        "cookie",
        "session",
        "backtrace",
        "stacktrace",
        "payload",
    ];
    MARKERS.iter().any(|marker| canonical.contains(marker))
}

fn sanitize_body(body: &str, config: &SharedActivationObserverConfig) -> String {
    if !config.export_guest_log_bodies || sensitive_text(body) {
        REDACTED.to_owned()
    } else {
        bounded(body, config.maximum_log_body_bytes)
    }
}

fn sensitive_text(value: &str) -> bool {
    let lower = value.to_ascii_lowercase();
    const MARKERS: [&str; 24] = [
        "authorization",
        "bearer ",
        "password",
        "passwd",
        "secret",
        "api_key",
        "api-key",
        "apikey",
        "access_token",
        "access-token",
        "refresh_token",
        "refresh-token",
        "private key",
        "begin rsa",
        "begin openssh",
        "cookie",
        "session",
        "token=",
        "token:",
        "\"token\"",
        "\"password\"",
        "\"secret\"",
        "backtrace",
        "stack trace",
    ];
    MARKERS.iter().any(|marker| lower.contains(marker))
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

fn lifecycle_status(stage: ActivationLifecycleStage, attributes: &Metadata) -> &'static str {
    match stage {
        ActivationLifecycleStage::Failure => "error",
        ActivationLifecycleStage::Cancellation => "cancelled",
        ActivationLifecycleStage::Completion
            if attributes.get("outcome").is_some_and(|outcome| {
                outcome != ActivationOutcomeClass::GuestSuccess.as_str()
            }) =>
        {
            "error"
        }
        _ => "ok",
    }
}

fn outcome_status(outcome: ActivationOutcomeClass) -> &'static str {
    match outcome {
        ActivationOutcomeClass::GuestSuccess => "ok",
        ActivationOutcomeClass::GuestDomainError | ActivationOutcomeClass::PlatformFailure => {
            "error"
        }
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

fn collect_error(first_error: &mut Option<PlatformError>, result: Result<(), PlatformError>) {
    if first_error.is_none() {
        *first_error = result.err();
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

#[cfg(test)]
mod tests {
    use super::*;

    fn test_envelope(id: &str) -> ActivationEnvelope {
        let activation_id = ActivationId(id.to_owned());
        ActivationEnvelope {
            activation_id: activation_id.clone(),
            parent_activation_id: None,
            root_activation_id: activation_id,
            principal: latent_core::InvocationPrincipal {
                subject: "subject".to_owned(),
                kind: latent_core::PrincipalKind::User,
                tenant: Some(latent_core::TenantId("tenant".to_owned())),
                service: None,
                claims: Metadata::new(),
            },
            target: latent_routing::InvocationTarget {
                tenant: latent_core::TenantId("tenant".to_owned()),
                service: latent_core::ServiceId("service".to_owned()),
                contract: latent_core::ContractId("example:contract".to_owned()),
                function: latent_core::FunctionId("invoke".to_owned()),
                route: None,
            },
            resolved_revision: None,
            deadline_unix_millis: None,
            priority: 0,
            trace: TraceContext {
                trace_id: latent_core::TraceId(format!("trace-{id}")),
                span_id: latent_core::SpanId(format!("span-{id}")),
                trace_flags: 1,
                baggage: Metadata::new(),
            },
            idempotency_key: None,
            retry_attempt: 0,
            budget: ResourceBudget {
                cpu_fuel: 10,
                memory_bytes: 1_024,
                wall_time_limit_millis: Some(100),
                child_calls: 0,
                outbound_requests: 0,
                state_read_bytes: 0,
                state_write_bytes: 0,
                blob_read_bytes: 0,
                blob_write_bytes: 0,
                log_bytes: 1_024,
                effect_count: 0,
            },
            metadata: Metadata::new(),
            input: Vec::new(),
            input_media_type: "application/octet-stream".to_owned(),
        }
    }

    #[test]
    fn outcome_contract_is_three_way_without_media_type_inference() {
        assert_eq!(
            classify_outcome(&ActivationOutcome::DeclaredError {
                error: latent_core::DeclaredError {
                    code: "domain".to_owned(),
                    message: "declared".to_owned(),
                    payload: Vec::new(),
                    media_type: "application/anything".to_owned(),
                    metadata: Metadata::new(),
                },
                consumption: BudgetConsumption::default(),
            }),
            ActivationOutcomeClass::GuestDomainError
        );
    }

    #[test]
    fn default_guest_filter_redacts_every_body_and_field_value() {
        let config = SharedActivationObserverConfig::default();
        assert_eq!(sanitize_body("ordinary text", &config), REDACTED);
        let fields = sanitize_fields(
            &Metadata::from([
                (
                    "safe-looking".to_owned(),
                    "secret under innocuous key".to_owned(),
                ),
                ("token".to_owned(), "abc".to_owned()),
            ]),
            &config,
        );
        assert!(fields.values().all(|value| value == REDACTED));
        assert_eq!(
            fields.keys().cloned().collect::<Vec<_>>(),
            vec!["redacted_field_0".to_owned(), "redacted_field_1".to_owned()]
        );
    }

    #[test]
    fn explicit_body_export_still_blocks_structured_secrets_and_backtraces() {
        let config = SharedActivationObserverConfig {
            export_guest_log_bodies: true,
            ..SharedActivationObserverConfig::default()
        };
        assert_eq!(sanitize_body(r#"{"token":"abc"}"#, &config), REDACTED);
        assert_eq!(sanitize_body("stack trace: frame 1", &config), REDACTED);
        assert_eq!(
            sanitize_body("bounded diagnostic", &config),
            "bounded diagnostic"
        );
    }

    #[test]
    fn cancellation_and_failure_spans_are_not_successful() {
        assert_eq!(
            lifecycle_status(ActivationLifecycleStage::Cancellation, &Metadata::new()),
            "cancelled"
        );
        assert_eq!(
            lifecycle_status(ActivationLifecycleStage::Failure, &Metadata::new()),
            "error"
        );
    }

    #[test]
    fn every_declared_budget_dimension_can_report_exhaustion() {
        let budget = ResourceBudget {
            cpu_fuel: 1,
            memory_bytes: 1,
            wall_time_limit_millis: Some(1),
            child_calls: 1,
            outbound_requests: 1,
            state_read_bytes: 1,
            state_write_bytes: 1,
            blob_read_bytes: 1,
            blob_write_bytes: 1,
            log_bytes: 1,
            effect_count: 1,
        };
        let consumption = BudgetConsumption {
            cpu_fuel: 1,
            peak_memory_bytes: 1,
            wall_time_micros: 1_000,
            child_calls: 1,
            outbound_requests: 1,
            state_read_bytes: 1,
            state_write_bytes: 1,
            blob_read_bytes: 1,
            blob_write_bytes: 1,
            log_bytes: 1,
            effect_count: 1,
        };
        let exhausted = [
            reached(consumption.cpu_fuel, budget.cpu_fuel),
            reached(consumption.peak_memory_bytes, budget.memory_bytes),
            reached(
                consumption.wall_time_micros,
                budget.wall_time_limit_millis.unwrap_or_default() * 1_000,
            ),
            reached(
                u64::from(consumption.child_calls),
                u64::from(budget.child_calls),
            ),
            reached(
                u64::from(consumption.outbound_requests),
                u64::from(budget.outbound_requests),
            ),
            reached(consumption.state_read_bytes, budget.state_read_bytes),
            reached(consumption.state_write_bytes, budget.state_write_bytes),
            reached(consumption.blob_read_bytes, budget.blob_read_bytes),
            reached(consumption.blob_write_bytes, budget.blob_write_bytes),
            reached(consumption.log_bytes, budget.log_bytes),
            reached(
                u64::from(consumption.effect_count),
                u64::from(budget.effect_count),
            ),
        ];
        assert!(exhausted.into_iter().all(std::convert::identity));
    }

    #[tokio::test]
    async fn all_three_terminal_outcomes_export_distinct_correlated_classes() {
        use std::collections::BTreeSet;

        use latent_activation::ActivationSuccess;
        use latent_core::{ActivationTerminalState, DeclaredError};

        use crate::{
            LocalSinkConfig, StructuredLocalSink, TelemetryPipelineConfig, TelemetryRecord,
            TelemetryRuntime,
        };

        let sink = Arc::new(
            StructuredLocalSink::new(LocalSinkConfig {
                maximum_entries: 4_096,
                maximum_bytes: 4 * 1_024 * 1_024,
            })
            .expect("valid local sink"),
        );
        let export: Arc<dyn crate::TelemetrySink> = sink.clone();
        let (handle, runtime) = TelemetryRuntime::spawn(
            TelemetryPipelineConfig {
                queue_capacity: 512,
                ..TelemetryPipelineConfig::default()
            },
            export,
        )
        .expect("valid pipeline");
        let observer = SharedActivationObserver::new(
            handle.clone(),
            SharedActivationObserverConfig::default(),
        )
        .expect("valid observer");
        let cases = [
            (
                test_envelope("success"),
                ActivationOutcome::Succeeded(ActivationSuccess {
                    output: Vec::new(),
                    output_media_type: "application/octet-stream".to_owned(),
                    consumption: BudgetConsumption::default(),
                    committed_state_version: None,
                    effect_ids: Vec::new(),
                    metadata: Metadata::new(),
                }),
            ),
            (
                test_envelope("declared"),
                ActivationOutcome::DeclaredError {
                    error: DeclaredError {
                        code: "domain".to_owned(),
                        message: "declared".to_owned(),
                        payload: Vec::new(),
                        media_type: "application/domain-error".to_owned(),
                        metadata: Metadata::new(),
                    },
                    consumption: BudgetConsumption::default(),
                },
            ),
            (
                test_envelope("platform"),
                ActivationOutcome::Failed {
                    terminal_state: ActivationTerminalState::PlatformFailed,
                    error: observer_error(PlatformErrorCode::Internal, "platform"),
                    consumption: BudgetConsumption::default(),
                },
            ),
        ];

        for (envelope, outcome) in cases {
            observer.on_received(&envelope).expect("receipt");
            observer
                .on_completed(&envelope, &outcome)
                .expect("terminal observation");
        }
        handle.flush().await.expect("flush");

        let records = sink.records();
        let metric_classes = records
            .iter()
            .filter_map(|record| match record {
                TelemetryRecord::Metric(point) if point.name == "latent.activation.outcomes" => {
                    point.attributes.get("outcome").cloned()
                }
                _ => None,
            })
            .collect::<BTreeSet<_>>();
        assert_eq!(
            metric_classes,
            BTreeSet::from([
                "guest_success".to_owned(),
                "guest_domain_error".to_owned(),
                "platform_failure".to_owned(),
            ])
        );
        for (activation_id, outcome) in [
            ("success", "guest_success"),
            ("declared", "guest_domain_error"),
            ("platform", "platform_failure"),
        ] {
            assert!(records.iter().any(|record| matches!(
                record,
                TelemetryRecord::Log(log)
                    if log.body == "activation completed"
                        && log.attributes.get("activation_id").map(String::as_str)
                            == Some(activation_id)
                        && log.attributes.get("outcome").map(String::as_str) == Some(outcome)
            )));
        }
        assert_eq!(observer.snapshot().active_correlations, 0);
        runtime.shutdown().await.expect("shutdown");
    }

    #[tokio::test]
    async fn failure_path_exports_every_stage_with_correlation_and_non_ok_status() {
        use latent_core::ActivationTerminalState;

        use crate::{
            LocalSinkConfig, StructuredLocalSink, TelemetryPipelineConfig, TelemetryRecord,
            TelemetryRuntime,
        };

        let sink = Arc::new(
            StructuredLocalSink::new(LocalSinkConfig {
                maximum_entries: 4_096,
                maximum_bytes: 4 * 1_024 * 1_024,
            })
            .expect("valid local sink"),
        );
        let export: Arc<dyn crate::TelemetrySink> = sink.clone();
        let (handle, runtime) = TelemetryRuntime::spawn(
            TelemetryPipelineConfig {
                queue_capacity: 512,
                ..TelemetryPipelineConfig::default()
            },
            export,
        )
        .expect("valid pipeline");
        let observer = SharedActivationObserver::new(
            handle.clone(),
            SharedActivationObserverConfig::default(),
        )
        .expect("valid observer");
        let envelope = test_envelope("activation-test");
        let activation_id = envelope.activation_id.clone();

        observer.on_received(&envelope).expect("receipt");
        for stage in [
            ActivationLifecycleStage::Resolution,
            ActivationLifecycleStage::Admission,
            ActivationLifecycleStage::Queueing,
            ActivationLifecycleStage::Materialization,
            ActivationLifecycleStage::Execution,
            ActivationLifecycleStage::Cancellation,
            ActivationLifecycleStage::Cleanup,
        ] {
            observer
                .on_lifecycle(&ActivationLifecycleEvent {
                    activation_id: activation_id.clone(),
                    stage,
                    occurred_at_unix_millis: 2,
                    duration_micros: Some(1),
                    attributes: Metadata::new(),
                })
                .expect("lifecycle stage");
        }
        observer
            .on_completed(
                &envelope,
                &ActivationOutcome::Failed {
                    terminal_state: ActivationTerminalState::PlatformFailed,
                    error: observer_error(PlatformErrorCode::Internal, "failure"),
                    consumption: BudgetConsumption::default(),
                },
            )
            .expect("completion");
        handle.flush().await.expect("flush");

        let records = sink.records();
        for stage in [
            ActivationLifecycleStage::Receipt,
            ActivationLifecycleStage::Resolution,
            ActivationLifecycleStage::Admission,
            ActivationLifecycleStage::Queueing,
            ActivationLifecycleStage::Materialization,
            ActivationLifecycleStage::Execution,
            ActivationLifecycleStage::Cancellation,
            ActivationLifecycleStage::Failure,
            ActivationLifecycleStage::Completion,
            ActivationLifecycleStage::Cleanup,
        ] {
            assert!(
                records.iter().any(|record| matches!(
                    record,
                    TelemetryRecord::Log(log)
                        if log.attributes.get("stage").map(String::as_str) == Some(stage.as_str())
                            && log.attributes.get("activation_id").map(String::as_str)
                                == Some("activation-test")
                )),
                "missing correlated lifecycle log for {}",
                stage.as_str()
            );
        }
        assert!(records.iter().any(|record| matches!(
            record,
            TelemetryRecord::Span(span)
                if span.name == "latent.activation.failure"
                    && span.status == "error"
                    && span.attributes.get("activation_id").map(String::as_str)
                        == Some("activation-test")
        )));
        assert!(records.iter().any(|record| matches!(
            record,
            TelemetryRecord::Span(span)
                if span.name == "latent.activation.cancellation"
                    && span.status == "cancelled"
        )));
        assert_eq!(observer.snapshot().active_correlations, 0);
        runtime.shutdown().await.expect("shutdown");
    }
}
