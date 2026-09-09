use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

use latent_activation::{ActivationEnvelope, ActivationOutcome};
use latent_core::{
    ActivationBudget, ActivationClock, ActivationId, ActivationPhase, ActivationTerminalState,
    BudgetConsumption, CancelDisposition, Metadata, PlatformError, PlatformErrorCode,
};
use latent_routing::ResolvedRevision;
use latent_scheduler::ScheduledActivation;
use latent_telemetry::ActivationCleanupDisposition;

use crate::activation_runner::{failure_for_platform_error, outcome_consumption};
use crate::budgeted_activation::{outcome_terminal_state, replace_consumption};
use crate::journal::JournalOwner;
use crate::CancellationRegistration;

use super::control::error;
use super::observation::{Observation, ObservationServices};

/// Owns cleanup and terminal publication once. Every execution future borrows
/// this guard and is destroyed before its Drop can finalize accounting.
pub(super) struct Lifecycle {
    journal: Option<JournalOwner>,
    cancellation: Option<CancellationRegistration>,
    clock: Arc<dyn ActivationClock>,
    deadline_abort: Arc<AtomicBool>,
    pub(super) budget: Option<ActivationBudget>,
    pub(super) resolved: Option<ResolvedRevision>,
    pub(super) scheduled: Option<ScheduledActivation>,
    pub(super) execution_started: bool,
    pub(super) quarantine_reason: Option<String>,
    pub(super) assigned: bool,
    observation: Option<Observation>,
}

impl Lifecycle {
    pub(super) fn new(
        journal: JournalOwner,
        cancellation: CancellationRegistration,
        clock: Arc<dyn ActivationClock>,
        deadline_abort: Arc<AtomicBool>,
    ) -> Self {
        Self {
            journal: Some(journal),
            cancellation: Some(cancellation),
            clock,
            deadline_abort,
            budget: None,
            resolved: None,
            scheduled: None,
            execution_started: false,
            quarantine_reason: None,
            assigned: false,
            observation: None,
        }
    }

    pub(super) fn begin_observation(
        &mut self,
        services: Option<&ObservationServices>,
        envelope: &ActivationEnvelope,
    ) {
        if let Some(services) = services {
            let journal = self.journal.as_ref().expect("accepted journal owner");
            self.observation = Some(Observation::new(
                services.clone(),
                journal.serial(),
                envelope,
                journal.stamp(),
            ));
        }
    }

    pub(super) fn observe_cancellation(&mut self) {
        if self.registration().token().is_cancelled() {
            if let Some(observation) = &mut self.observation {
                observation.cancellation(CancelDisposition::Accepted);
            }
        }
    }

    pub(super) fn observe_cleanup(&mut self, disposition: ActivationCleanupDisposition) {
        if let Some(observation) = &mut self.observation {
            observation.cleanup(disposition);
        }
    }

    pub(super) fn registration(&self) -> &CancellationRegistration {
        self.cancellation
            .as_ref()
            .expect("live cancellation registration")
    }
    pub(super) fn activation_id(&self) -> &ActivationId {
        self.registration().activation_id()
    }

    pub(super) fn advance(
        &mut self,
        phase: ActivationPhase,
        attributes: Metadata,
    ) -> Result<(), PlatformError> {
        let stamp = self
            .journal
            .as_mut()
            .expect("live lifecycle journal")
            .advance(phase, attributes)?;
        if let Some(observer) = self.clock.deadline_diagnostic_observer() {
            observer.record_for_activation(
                &self.activation_id().0,
                latent_core::DeadlineDiagnosticObservation::LifecyclePhase {
                    observed_at: self.clock.monotonic_now(),
                    phase,
                },
            );
        }
        if let Some(observation) = &mut self.observation {
            observation.advance(
                stamp,
                self.resolved.as_ref(),
                self.budget.as_ref().map(ActivationBudget::granted),
            );
        }
        Ok(())
    }

    fn reclaim(&mut self) {
        self.observe_cancellation();
        let mut disposition = if self.assigned {
            ActivationCleanupDisposition::Abandoned
        } else {
            ActivationCleanupDisposition::NoCell
        };
        if let Some(scheduled) = self.scheduled.take() {
            if self.execution_started {
                // The backend/pool has not completed a reusable disposition.
                drop(scheduled);
            } else {
                scheduled.reclaim_before_execution();
                disposition = ActivationCleanupDisposition::ReclaimedBeforeExecution;
            }
        }
        self.observe_cleanup(disposition);
    }

    pub(super) fn complete(mut self, outcome: ActivationOutcome) -> ActivationOutcome {
        self.reclaim();
        self.publish(outcome)
    }

    fn publish(&mut self, mut outcome: ActivationOutcome) -> ActivationOutcome {
        if let Some(budget) = &self.budget {
            let now = self.clock.monotonic_now();
            let deadline = budget.check_deadline_at(now).err();
            self.record_deadline_decision(now, budget.deadline().monotonic(), deadline.is_some());
            let finalized = budget.finalize_at(Some(&outcome_consumption(&outcome)), now);
            let consumption = finalized.consumption().clone();
            outcome = if let Some(error) = deadline.or_else(|| finalized.violation().cloned()) {
                failure_for_platform_error(error.to_platform_error(), consumption)
            } else {
                replace_consumption(outcome, consumption)
            };
        }
        let journal = self.journal.as_ref().expect("one terminal publication");
        if let Err(failure) = journal.validate_terminal(&outcome) {
            outcome = failure_for_platform_error(failure, outcome_consumption(&outcome));
        }
        // Linearize the winner before recording the result. Registration stays
        // present until the journal's status and terminal event are committed.
        let publication = self
            .registration()
            .publish_terminal(outcome_terminal_state(&outcome));
        let cancellation_accepted = publication.cancellation_reason.is_some();
        if publication.state == ActivationTerminalState::Cancelled {
            if let Some(reason) = publication.cancellation_reason {
                outcome = failure_for_platform_error(
                    error(PlatformErrorCode::Cancelled, &reason),
                    outcome_consumption(&outcome),
                );
            }
        }
        let (outcome, stamp) = self
            .journal
            .take()
            .expect("live terminal reservation")
            .finish_with_stamp(outcome);
        if let Some(observer) = self.clock.deadline_diagnostic_observer() {
            observer.record_for_activation(
                &self.activation_id().0,
                latent_core::DeadlineDiagnosticObservation::TerminalWinner {
                    observed_at: self.clock.monotonic_now(),
                    terminal_state: outcome_terminal_state(&outcome),
                },
            );
        }
        drop(self.cancellation.take());
        if let Some(observation) = &mut self.observation {
            if cancellation_accepted {
                observation.cancellation(CancelDisposition::Accepted);
            }
            observation.terminal(&outcome, stamp, self.resolved.as_ref());
        }
        outcome
    }

    fn record_deadline_decision(
        &self,
        now: std::time::Instant,
        expires_at: Option<std::time::Instant>,
        expired: bool,
    ) {
        if let Some(observer) = self.clock.deadline_diagnostic_observer() {
            observer.record_for_activation(
                &self.activation_id().0,
                latent_core::DeadlineDiagnosticObservation::TerminalDecision {
                    observed_at: now,
                    expires_at,
                    decision: if expired {
                        latent_core::DeadlineDiagnosticDecision::DeadlineExceeded
                    } else {
                        latent_core::DeadlineDiagnosticDecision::Accepted
                    },
                },
            );
        }
    }
}

impl Drop for Lifecycle {
    fn drop(&mut self) {
        if self.journal.is_none() {
            return;
        }
        // Inner async work (including a Wasmtime store and prepared-use token)
        // has already been dropped. Dispose cell then quota before accounting.
        self.reclaim();
        let code = if std::thread::panicking() {
            PlatformErrorCode::Internal
        } else if self.deadline_abort.load(Ordering::Acquire) {
            PlatformErrorCode::DeadlineExceeded
        } else {
            PlatformErrorCode::Cancelled
        };
        let message = if code == PlatformErrorCode::DeadlineExceeded {
            "activation transport deadline exceeded"
        } else {
            "activation handle abandoned before terminal completion"
        };
        let outcome =
            failure_for_platform_error(error(code, message), BudgetConsumption::default());
        let _ = self.publish(outcome);
    }
}
