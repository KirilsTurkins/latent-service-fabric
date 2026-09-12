//! Observations share the lifecycle owner and never affect its committed result.

use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use std::time::Instant;

use latent_activation::{ActivationEnvelope, ActivationOutcome};
use latent_core::{ActivationClock, ActivationPhase, CancelDisposition};
use latent_routing::ResolvedRevision;
use latent_telemetry::{
    ActivationCleanupDisposition, ActivationObservation, ActivationObservationContext,
    ActivationObservationKind, ActivationObservationToken, ActivationObserver,
    ActivationOutcomeClass, ActivationTerminalObservation, CanaryCapture, CanarySample,
    SelectedOutcomeRevision,
};

use crate::activation_runner::outcome_consumption;
use crate::budgeted_activation::outcome_terminal_state;
use crate::journal::JournalStamp;

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct ActivationObservationSnapshot {
    pub attempted: u64,
    pub observer_panics: u64,
}

#[derive(Default)]
pub(super) struct Counters {
    attempted: AtomicU64,
    panics: AtomicU64,
}

impl Counters {
    pub(super) fn snapshot(&self) -> ActivationObservationSnapshot {
        ActivationObservationSnapshot {
            attempted: self.attempted.load(Ordering::Relaxed),
            observer_panics: self.panics.load(Ordering::Relaxed),
        }
    }
}

#[derive(Clone)]
pub(super) struct ObservationServices {
    pub observer: Option<Arc<dyn ActivationObserver>>,
    pub canary: Option<CanaryCapture>,
    pub counters: Arc<Counters>,
    pub clock: Arc<dyn ActivationClock>,
    pub owner: u64,
}

pub(super) struct Observation {
    services: ObservationServices,
    context: Option<ActivationObservationContext>,
    canary: Option<CanarySample>,
    started: Instant,
    last_phase: ActivationPhase,
    sequence: u64,
    cleanup: bool,
    cancellation: bool,
}

impl Observation {
    pub(super) fn new(
        services: ObservationServices,
        serial: u64,
        envelope: &ActivationEnvelope,
        stamp: JournalStamp,
    ) -> Self {
        let token = ActivationObservationToken {
            manager: services.owner,
            sequence: serial,
        };
        let canary = services.canary.as_ref().and_then(|capture| {
            capture
                .try_begin(token, &envelope.target.tenant, &envelope.target.service)
                .into_sample()
        });
        let context = services
            .observer
            .as_ref()
            .map(|_| ActivationObservationContext {
                token,
                activation_id: envelope.activation_id.clone(),
                root_activation_id: envelope.root_activation_id.clone(),
                parent_activation_id: envelope.parent_activation_id.clone(),
                tenant: envelope.target.tenant.clone(),
                service: envelope.target.service.clone(),
                contract: envelope.target.contract.clone(),
                function: envelope.target.function.clone(),
                trace_id: envelope.trace.trace_id.clone(),
                span_id: envelope.trace.span_id.clone(),
                trace_flags: envelope.trace.trace_flags,
                release: None,
                revision: None,
                route_generation: None,
            });
        let started = services.clock.monotonic_now();
        let observation = Self {
            services,
            context,
            canary,
            started,
            last_phase: stamp.phase,
            sequence: stamp.sequence,
            cleanup: false,
            cancellation: false,
        };
        observation.emit(ActivationObservationKind::Received, stamp.unix_millis);
        observation
    }

    pub(super) fn advance(
        &mut self,
        stamp: JournalStamp,
        resolved: Option<&ResolvedRevision>,
        grant: Option<&latent_core::ResourceBudget>,
    ) {
        self.refresh(resolved);
        self.last_phase = stamp.phase;
        self.sequence = stamp.sequence;
        self.emit(
            ActivationObservationKind::Phase {
                phase: stamp.phase,
                sequence: stamp.sequence,
            },
            stamp.unix_millis,
        );
        if stamp.phase == ActivationPhase::Admitted {
            if let Some(grant) = grant {
                if let Some(sample) = &mut self.canary {
                    sample.admitted();
                }
                self.emit(
                    ActivationObservationKind::AdmittedGrant(grant.clone()),
                    stamp.unix_millis,
                );
            }
        }
    }

    pub(super) fn cancellation(&mut self, disposition: CancelDisposition) {
        if self.cancellation {
            return;
        }
        self.cancellation = true;
        self.emit(
            ActivationObservationKind::Cancellation(disposition),
            self.services.clock.sample().unix_millis(),
        );
    }

    pub(super) fn cleanup(&mut self, disposition: ActivationCleanupDisposition) {
        if self.cleanup {
            return;
        }
        self.cleanup = true;
        self.emit(
            ActivationObservationKind::Cleanup(disposition),
            self.services.clock.sample().unix_millis(),
        );
    }

    pub(super) fn terminal(
        &mut self,
        outcome: &ActivationOutcome,
        stamp: JournalStamp,
        resolved: Option<&ResolvedRevision>,
    ) {
        self.refresh(resolved);
        self.last_phase = stamp.phase;
        self.sequence = stamp.sequence;
        let (class, platform_code) = match outcome {
            ActivationOutcome::Succeeded(_) => (ActivationOutcomeClass::GuestSuccess, None),
            ActivationOutcome::DeclaredError { .. } => {
                (ActivationOutcomeClass::GuestDomainError, None)
            }
            ActivationOutcome::Failed { error, .. } => {
                (ActivationOutcomeClass::PlatformFailure, Some(error.code))
            }
        };
        let terminal = ActivationTerminalObservation {
            class,
            terminal_state: outcome_terminal_state(outcome),
            platform_code,
            consumption: outcome_consumption(outcome),
            last_phase: self.last_phase,
            sequence: self.sequence,
        };
        if let Some(sample) = self.canary.take() {
            sample.finish(
                &terminal,
                self.services
                    .clock
                    .monotonic_now()
                    .saturating_duration_since(self.started),
            );
        }
        self.emit(
            ActivationObservationKind::Terminal(terminal),
            stamp.unix_millis,
        );
    }

    fn refresh(&mut self, resolved: Option<&ResolvedRevision>) {
        if let Some(resolved) = resolved {
            if let Some(sample) = &mut self.canary {
                sample.bind_selected(SelectedOutcomeRevision {
                    tenant: &resolved.target.tenant,
                    service: &resolved.target.service,
                    revision: &resolved.revision,
                    component: &resolved.release,
                    generation: resolved.route_generation,
                });
            }
            if let Some(context) = &mut self.context {
                context.release = Some(resolved.release.clone());
                context.revision = Some(resolved.revision.clone());
                context.route_generation = Some(resolved.route_generation);
            }
        }
    }

    fn emit(&self, kind: ActivationObservationKind, unix_millis: u64) {
        let (Some(observer), Some(context)) = (&self.services.observer, &self.context) else {
            return;
        };
        increment(&self.services.counters.attempted);
        let event = ActivationObservation {
            occurred_at_unix_millis: unix_millis,
            elapsed: self
                .services
                .clock
                .monotonic_now()
                .saturating_duration_since(self.started),
            kind,
        };
        let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            observer.on_observation(context, &event);
        }));
        if result.is_err() {
            increment(&self.services.counters.panics);
        }
    }
}

fn increment(counter: &AtomicU64) {
    let _ = counter.fetch_update(Ordering::Relaxed, Ordering::Relaxed, |value| {
        Some(value.saturating_add(1))
    });
}
