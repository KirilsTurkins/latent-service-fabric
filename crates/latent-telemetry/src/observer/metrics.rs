use latent_core::{ActivationPhase, BudgetConsumption, Metadata, ResourceBudget};

use crate::{
    ActivationObservation, ActivationObservationKind, ActivationOutcomeClass,
    ActivationTerminalObservation, LogRecord, LogSeverity, MetricKind, MetricPoint, SpanRecord,
};

use super::{formatting, Correlation, SharedActivationObserver};

impl SharedActivationObserver {
    pub(super) fn emit_lifecycle(&self, correlation: &Correlation, event: &ActivationObservation) {
        self.phase_duration(correlation, event);
        if let ActivationObservationKind::AdmittedGrant(grant) = &event.kind {
            self.grants(grant, event.occurred_at_unix_millis);
            return;
        }
        let stage = formatting::stage(&event.kind);
        let mut attributes =
            formatting::attributes(&correlation.context, self.config.maximum_field_value_bytes);
        attributes.insert("stage".to_owned(), stage.to_owned());
        attributes.insert(
            "elapsed_micros".to_owned(),
            micros(event.elapsed).to_string(),
        );
        match &event.kind {
            ActivationObservationKind::Phase { sequence, .. } => {
                attributes.insert("sequence".to_owned(), sequence.to_string());
            }
            ActivationObservationKind::Cancellation(disposition) => {
                let result = formatting::cancellation(*disposition);
                attributes.insert("result".to_owned(), result.to_owned());
                self.emit_metric(
                    "latent.activation.cancellations",
                    MetricKind::Counter,
                    1.0,
                    "1",
                    Metadata::from([("result".to_owned(), result.to_owned())]),
                    event.occurred_at_unix_millis,
                );
            }
            ActivationObservationKind::Cleanup(disposition) => {
                let disposition = formatting::cleanup(*disposition);
                attributes.insert("cleanup".to_owned(), disposition.to_owned());
                self.emit_metric(
                    "latent.execution.cleanup",
                    MetricKind::Counter,
                    1.0,
                    "1",
                    Metadata::from([("disposition".to_owned(), disposition.to_owned())]),
                    event.occurred_at_unix_millis,
                );
            }
            ActivationObservationKind::Terminal(terminal) => {
                terminal_attributes(&mut attributes, terminal);
                self.terminal_metrics(correlation, terminal, event);
                if terminal.class != ActivationOutcomeClass::GuestSuccess {
                    self.lifecycle_count("failure", event.occurred_at_unix_millis);
                    let mut failure = attributes.clone();
                    failure.insert("stage".to_owned(), "failure".to_owned());
                    self.lifecycle_log(correlation, event, "failure", failure);
                }
            }
            ActivationObservationKind::Received | ActivationObservationKind::AdmittedGrant(_) => {}
        }
        self.lifecycle_count(stage, event.occurred_at_unix_millis);
        self.lifecycle_log(correlation, event, stage, attributes);
    }

    fn lifecycle_count(&self, stage: &str, timestamp: u64) {
        self.emit_metric(
            "latent.activation.lifecycle.events",
            MetricKind::Counter,
            1.0,
            "1",
            Metadata::from([("stage".to_owned(), stage.to_owned())]),
            timestamp,
        );
    }

    fn phase_duration(&self, correlation: &Correlation, event: &ActivationObservation) {
        let Some((phase, duration)) = correlation.previous_phase else {
            return;
        };
        let kind = ActivationObservationKind::Phase { phase, sequence: 0 };
        self.emit_metric(
            "latent.activation.lifecycle.duration",
            MetricKind::Histogram,
            number(micros(duration)),
            "us",
            Metadata::from([("stage".to_owned(), formatting::stage(&kind).to_owned())]),
            event.occurred_at_unix_millis,
        );
        if phase == ActivationPhase::Queued {
            self.emit_metric(
                "latent.scheduler.queue.wait",
                MetricKind::Histogram,
                number(micros(duration)),
                "us",
                Metadata::new(),
                event.occurred_at_unix_millis,
            );
        }
    }

    fn lifecycle_log(
        &self,
        correlation: &Correlation,
        event: &ActivationObservation,
        stage: &str,
        attributes: Metadata,
    ) {
        let (severity, status) = match &event.kind {
            ActivationObservationKind::Terminal(terminal) => match terminal.class {
                ActivationOutcomeClass::GuestSuccess => (LogSeverity::Info, "ok"),
                ActivationOutcomeClass::GuestDomainError => (LogSeverity::Warn, "declared_error"),
                ActivationOutcomeClass::PlatformFailure => (LogSeverity::Error, "error"),
            },
            ActivationObservationKind::Cancellation(_) => (LogSeverity::Info, "cancel_requested"),
            _ => (LogSeverity::Info, "ok"),
        };
        let trace = formatting::trace(&correlation.context, self.config.maximum_field_value_bytes);
        self.submitted(&self.telemetry.try_emit_log(LogRecord {
            severity,
            body: format!("activation {stage}"),
            trace: Some(trace.clone()),
            attributes: attributes.clone(),
            observed_at_unix_millis: event.occurred_at_unix_millis,
        }));
        if stage != "completion" || !matches!(event.kind, ActivationObservationKind::Terminal(_)) {
            return;
        }
        // Translate the monotonic duration against one captured wall origin;
        // a wall-clock rollback never creates a backwards span or fake latency.
        let started = correlation.received_at.saturating_mul(1_000_000);
        let elapsed = u64::try_from(event.elapsed.as_nanos()).unwrap_or(u64::MAX);
        let ended = started.saturating_add(elapsed);
        self.submitted(&self.telemetry.try_emit_span(SpanRecord {
            name: "latent.activation".to_owned(),
            trace,
            parent_span_id: None,
            started_at_unix_nanos: started,
            ended_at_unix_nanos: ended,
            status: status.to_owned(),
            attributes,
        }));
    }

    fn grants(&self, grant: &ResourceBudget, timestamp: u64) {
        for (resource, value) in [
            ("cpu_fuel", grant.cpu_fuel),
            ("memory_bytes", grant.memory_bytes),
            ("log_bytes", grant.log_bytes),
        ] {
            self.resource_metric(
                "latent.activation.budget.granted",
                resource,
                value,
                Metadata::new(),
                timestamp,
            );
        }
        if let Some(millis) = grant.wall_time_limit_millis {
            self.resource_metric(
                "latent.activation.budget.granted",
                "wall_time_micros",
                millis.saturating_mul(1000),
                Metadata::new(),
                timestamp,
            );
        }
    }

    fn terminal_metrics(
        &self,
        correlation: &Correlation,
        terminal: &ActivationTerminalObservation,
        event: &ActivationObservation,
    ) {
        let mut labels =
            Metadata::from([("outcome".to_owned(), terminal.class.as_str().to_owned())]);
        if let Some(code) = terminal.platform_code {
            labels.insert("error_code".to_owned(), code.wire_code().to_owned());
        }
        self.emit_metric(
            "latent.activation.outcomes",
            MetricKind::Counter,
            1.0,
            "1",
            labels.clone(),
            event.occurred_at_unix_millis,
        );
        self.emit_metric(
            "latent.activation.latency",
            MetricKind::Histogram,
            number(micros(event.elapsed)),
            "us",
            labels,
            event.occurred_at_unix_millis,
        );
        for (resource, value) in consumption(&terminal.consumption) {
            self.resource_metric(
                "latent.activation.budget.consumed",
                resource,
                value,
                Metadata::from([("outcome".to_owned(), terminal.class.as_str().to_owned())]),
                event.occurred_at_unix_millis,
            );
        }
        if let Some(grant) = &correlation.granted {
            for (resource, used, limit) in [
                ("cpu_fuel", terminal.consumption.cpu_fuel, grant.cpu_fuel),
                (
                    "memory_bytes",
                    terminal.consumption.peak_memory_bytes,
                    grant.memory_bytes,
                ),
                ("log_bytes", terminal.consumption.log_bytes, grant.log_bytes),
            ] {
                if used > 0 && used >= limit {
                    self.emit_metric(
                        "latent.activation.budget.limit_reached",
                        MetricKind::Counter,
                        1.0,
                        "1",
                        Metadata::from([("resource".to_owned(), resource.to_owned())]),
                        event.occurred_at_unix_millis,
                    );
                }
            }
        }
    }

    fn resource_metric(
        &self,
        name: &str,
        resource: &str,
        value: u64,
        mut labels: Metadata,
        timestamp: u64,
    ) {
        labels.insert("resource".to_owned(), resource.to_owned());
        self.emit_metric(
            name,
            MetricKind::Histogram,
            number(value),
            "1",
            labels,
            timestamp,
        );
    }

    pub(super) fn emit_metric(
        &self,
        name: &str,
        kind: MetricKind,
        value: f64,
        unit: &str,
        attributes: Metadata,
        timestamp: u64,
    ) {
        self.submitted(&self.telemetry.try_emit_metric(MetricPoint {
            name: name.to_owned(),
            kind,
            value,
            unit: unit.to_owned(),
            attributes,
            observed_at_unix_millis: timestamp,
        }));
    }
}

fn terminal_attributes(attributes: &mut Metadata, terminal: &ActivationTerminalObservation) {
    attributes.insert("outcome".to_owned(), terminal.class.as_str().to_owned());
    attributes.insert(
        "terminal_state".to_owned(),
        formatting::terminal(terminal.terminal_state).to_owned(),
    );
    attributes.insert("sequence".to_owned(), terminal.sequence.to_string());
    if let Some(code) = terminal.platform_code {
        attributes.insert("error_code".to_owned(), code.wire_code().to_owned());
    }
    for (name, value) in consumption(&terminal.consumption) {
        attributes.insert(name.to_owned(), value.to_string());
    }
}

fn consumption(value: &BudgetConsumption) -> [(&'static str, u64); 4] {
    [
        ("cpu_fuel", value.cpu_fuel),
        ("memory_bytes", value.peak_memory_bytes),
        ("wall_time_micros", value.wall_time_micros),
        ("log_bytes", value.log_bytes),
    ]
}

fn micros(value: std::time::Duration) -> u64 {
    u64::try_from(value.as_micros()).unwrap_or(u64::MAX)
}

#[allow(
    clippy::cast_precision_loss,
    reason = "MetricPoint stores approximate floating point observations; lifecycle logs retain exact integer values."
)]
fn number(value: u64) -> f64 {
    value as f64
}
