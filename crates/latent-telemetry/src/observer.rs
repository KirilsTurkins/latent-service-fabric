//! Bounded correlation bookkeeping and nonblocking submission to the exporter.

mod formatting;
mod metrics;
mod redaction;
#[cfg(test)]
mod tests;

use std::collections::{BTreeMap, BTreeSet};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex, MutexGuard};
use std::time::Duration;

use latent_core::{
    ActivationId, ActivationPhase, PlatformError, PlatformErrorCode, ResourceBudget,
};

use crate::{
    ActivationObservation, ActivationObservationContext, ActivationObservationKind,
    ActivationObservationToken, ActivationObserver, GuestLogObserver, GuestLogRecord,
    TelemetryHandle,
};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SharedActivationObserverConfig {
    pub maximum_active_correlations: usize,
    pub maximum_correlation_value_bytes: usize,
    pub maximum_context_bytes: usize,
    pub maximum_log_input_bytes: usize,
    pub maximum_log_body_bytes: usize,
    pub maximum_log_fields: usize,
    pub maximum_field_name_bytes: usize,
    pub maximum_field_value_bytes: usize,
    pub export_guest_log_bodies: bool,
    pub allowed_guest_field_names: Vec<String>,
}

impl Default for SharedActivationObserverConfig {
    fn default() -> Self {
        Self {
            maximum_active_correlations: 4096,
            maximum_correlation_value_bytes: 512,
            maximum_context_bytes: 8192,
            maximum_log_input_bytes: 64 * 1024,
            maximum_log_body_bytes: 1024,
            maximum_log_fields: 32,
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
    pub guest_logs: u64,
    pub observations_dropped: u64,
    pub capacity_drops: u64,
    pub invalid_records: u64,
    pub unknown_correlations: u64,
    pub submission_errors: u64,
    pub panics: u64,
}

#[derive(Debug, Default)]
struct Counters {
    received: AtomicU64,
    completed: AtomicU64,
    guest_logs: AtomicU64,
    observations_dropped: AtomicU64,
    capacity_drops: AtomicU64,
    invalid_records: AtomicU64,
    unknown_correlations: AtomicU64,
    submission_errors: AtomicU64,
    panics: AtomicU64,
}

#[derive(Debug, Clone)]
struct Correlation {
    context: ActivationObservationContext,
    received_at: u64,
    granted: Option<ResourceBudget>,
    phase: ActivationPhase,
    phase_started: Duration,
    previous_phase: Option<(ActivationPhase, Duration)>,
}

#[derive(Debug, Default)]
struct State {
    entries: BTreeMap<ActivationObservationToken, Box<Correlation>>,
    ids: BTreeMap<ActivationId, BTreeSet<ActivationObservationToken>>,
}

impl State {
    fn by_id(&self, id: &ActivationId) -> Option<&Correlation> {
        let tokens = self.ids.get(id)?;
        if tokens.len() != 1 {
            return None;
        }
        self.entries.get(tokens.first()?).map(Box::as_ref)
    }

    fn remove(&mut self, token: ActivationObservationToken) {
        let Some(entry) = self.entries.remove(&token) else {
            return;
        };
        let id = &entry.context.activation_id;
        if let Some(tokens) = self.ids.get_mut(id) {
            tokens.remove(&token);
            if tokens.is_empty() {
                self.ids.remove(id);
            }
        }
    }
}

#[derive(Debug, Clone)]
pub struct SharedActivationObserver {
    telemetry: TelemetryHandle,
    config: SharedActivationObserverConfig,
    state: Arc<Mutex<State>>,
    counters: Arc<Counters>,
}

impl SharedActivationObserver {
    pub fn new(
        telemetry: TelemetryHandle,
        config: SharedActivationObserverConfig,
    ) -> Result<Self, PlatformError> {
        redaction::validate_config(&config)?;
        Ok(Self {
            telemetry,
            config,
            state: Arc::new(Mutex::new(State::default())),
            counters: Arc::new(Counters::default()),
        })
    }

    #[must_use]
    pub fn snapshot(&self) -> ObserverSnapshot {
        let count = |value: &AtomicU64| value.load(Ordering::Relaxed);
        ObserverSnapshot {
            active_correlations: self.lock().entries.len(),
            received: count(&self.counters.received),
            completed: count(&self.counters.completed),
            guest_logs: count(&self.counters.guest_logs),
            observations_dropped: count(&self.counters.observations_dropped),
            capacity_drops: count(&self.counters.capacity_drops),
            invalid_records: count(&self.counters.invalid_records),
            unknown_correlations: count(&self.counters.unknown_correlations),
            submission_errors: count(&self.counters.submission_errors),
            panics: count(&self.counters.panics),
        }
    }

    #[must_use]
    pub fn correlation(
        &self,
        activation_id: &ActivationId,
    ) -> Option<ActivationObservationContext> {
        if activation_id.0.len() > self.config.maximum_correlation_value_bytes {
            return None;
        }
        self.lock()
            .by_id(activation_id)
            .map(|entry| entry.context.clone())
    }

    fn observe(&self, context: &ActivationObservationContext, event: &ActivationObservation) {
        if !redaction::valid_context(context, &self.config) {
            if matches!(event.kind, ActivationObservationKind::Terminal(_))
                && context.activation_id.0.len() <= self.config.maximum_correlation_value_bytes
            {
                let mut state = self.lock();
                if state
                    .entries
                    .get(&context.token)
                    .is_some_and(|entry| entry.context.activation_id == context.activation_id)
                {
                    state.remove(context.token);
                }
            }
            self.dropped(&self.counters.invalid_records);
            return;
        }
        let Some(correlation) = self.update(context, event) else {
            return;
        };
        // All exporter submission and formatting happens after releasing the
        // short bookkeeping lock. Active entries are never evicted for space.
        self.emit_lifecycle(&correlation, event);
    }

    fn update(
        &self,
        context: &ActivationObservationContext,
        event: &ActivationObservation,
    ) -> Option<Correlation> {
        let mut state = self.lock();
        if matches!(event.kind, ActivationObservationKind::Received) {
            if state.entries.contains_key(&context.token) {
                self.dropped(&self.counters.invalid_records);
                return None;
            }
            if state.entries.len() >= self.config.maximum_active_correlations {
                self.dropped(&self.counters.capacity_drops);
                return None;
            }
            state
                .ids
                .entry(context.activation_id.clone())
                .or_default()
                .insert(context.token);
            state.entries.insert(
                context.token,
                Box::new(Correlation {
                    context: context.clone(),
                    received_at: event.occurred_at_unix_millis,
                    granted: None,
                    phase: ActivationPhase::Received,
                    phase_started: event.elapsed,
                    previous_phase: None,
                }),
            );
            increment(&self.counters.received);
        }
        let Some(entry) = state
            .entries
            .get_mut(&context.token)
            .filter(|entry| entry.context.activation_id == context.activation_id)
        else {
            self.dropped(&self.counters.unknown_correlations);
            return None;
        };
        #[allow(
            clippy::assigning_clones,
            reason = "Fresh strings prevent previous field capacities from exceeding the aggregate context bound."
        )]
        {
            entry.context = context.clone();
        }
        entry.previous_phase = None;
        if let ActivationObservationKind::Phase { phase, .. } = event.kind {
            entry.previous_phase = Some((
                entry.phase,
                event.elapsed.saturating_sub(entry.phase_started),
            ));
            entry.phase = phase;
            entry.phase_started = event.elapsed;
        } else if matches!(event.kind, ActivationObservationKind::Terminal(_)) {
            entry.previous_phase = Some((
                entry.phase,
                event.elapsed.saturating_sub(entry.phase_started),
            ));
        }
        if let ActivationObservationKind::AdmittedGrant(grant) = &event.kind {
            entry.granted = Some(grant.clone());
        }
        let result = entry.as_ref().clone();
        if matches!(event.kind, ActivationObservationKind::Terminal(_)) {
            state.remove(context.token);
            increment(&self.counters.completed);
        }
        Some(result)
    }

    fn submitted(&self, result: &Result<bool, PlatformError>) {
        match result {
            Ok(true) => {}
            Ok(false) => increment(&self.counters.observations_dropped),
            Err(_) => self.dropped(&self.counters.submission_errors),
        }
    }

    fn dropped(&self, reason: &AtomicU64) {
        increment(reason);
        increment(&self.counters.observations_dropped);
    }

    fn lock(&self) -> MutexGuard<'_, State> {
        self.state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
    }
}

impl ActivationObserver for SharedActivationObserver {
    fn on_observation(
        &self,
        context: &ActivationObservationContext,
        event: &ActivationObservation,
    ) {
        if std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            self.observe(context, event);
        }))
        .is_err()
        {
            self.dropped(&self.counters.panics);
        }
    }
}

impl GuestLogObserver for SharedActivationObserver {
    fn on_guest_log(&self, record: GuestLogRecord<'_>) -> Result<(), PlatformError> {
        if !redaction::valid_log(&record, &self.config) {
            self.dropped(&self.counters.invalid_records);
            return Ok(());
        }
        let Some(correlation) = self.lock().by_id(record.activation_id).cloned() else {
            self.dropped(&self.counters.unknown_correlations);
            return Ok(());
        };
        increment(&self.counters.guest_logs);
        let log = redaction::guest_log(&record, &correlation.context, &self.config);
        let result = self.telemetry.try_emit_log(log);
        let error = result.as_ref().err().cloned();
        self.submitted(&result);
        self.emit_metric(
            "latent.guest.logs",
            crate::MetricKind::Counter,
            1.0,
            "1",
            latent_core::Metadata::from([(
                "severity".to_owned(),
                formatting::severity(record.severity).to_owned(),
            )]),
            record.observed_at_unix_millis,
        );
        error.map_or(Ok(()), Err)
    }
}

fn increment(counter: &AtomicU64) {
    let _ = counter.fetch_update(Ordering::Relaxed, Ordering::Relaxed, |value| {
        Some(value.saturating_add(1))
    });
}

fn error(message: &str) -> PlatformError {
    PlatformError {
        code: PlatformErrorCode::InvalidArgument,
        message: message.to_owned(),
        retryable: false,
        details: Vec::new(),
    }
}
