use std::sync::Arc;

use latent_activation::ActivationOutcome;
use latent_core::{
    ActivationBudget, ActivationClock, ActivationId, ActivationPhase, ActivationTerminalState,
    BudgetConsumption, Metadata, PlatformError, PlatformErrorCode,
};
use latent_routing::ResolvedRevision;
use latent_scheduler::ScheduledActivation;

use crate::activation_runner::{failure_for_platform_error, outcome_consumption};
use crate::budgeted_activation::{outcome_terminal_state, replace_consumption};
use crate::journal::JournalOwner;
use crate::CancellationRegistration;

use super::control::error;

/// Owns cleanup and terminal publication once. Every execution future borrows
/// this guard and is destroyed before its Drop can finalize accounting.
pub(super) struct Lifecycle {
    journal: Option<JournalOwner>,
    cancellation: Option<CancellationRegistration>,
    clock: Arc<dyn ActivationClock>,
    pub(super) budget: Option<ActivationBudget>,
    pub(super) resolved: Option<ResolvedRevision>,
    pub(super) scheduled: Option<ScheduledActivation>,
    pub(super) execution_started: bool,
    pub(super) quarantine_reason: Option<String>,
}

impl Lifecycle {
    pub(super) fn new(
        journal: JournalOwner,
        cancellation: CancellationRegistration,
        clock: Arc<dyn ActivationClock>,
    ) -> Self {
        Self {
            journal: Some(journal),
            cancellation: Some(cancellation),
            clock,
            budget: None,
            resolved: None,
            scheduled: None,
            execution_started: false,
            quarantine_reason: None,
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
        self.journal
            .as_mut()
            .expect("live lifecycle journal")
            .advance(phase, attributes)
    }

    fn reclaim(&mut self) {
        if let Some(scheduled) = self.scheduled.take() {
            if self.execution_started {
                // The backend/pool has not completed a reusable disposition.
                drop(scheduled);
            } else {
                scheduled.reclaim_before_execution();
            }
        }
    }

    pub(super) fn complete(mut self, outcome: ActivationOutcome) -> ActivationOutcome {
        self.reclaim();
        self.publish(outcome)
    }

    fn publish(&mut self, mut outcome: ActivationOutcome) -> ActivationOutcome {
        if let Some(budget) = &self.budget {
            let now = self.clock.monotonic_now();
            let deadline = budget.check_deadline_at(now).err();
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
        if publication.state == ActivationTerminalState::Cancelled {
            if let Some(reason) = publication.cancellation_reason {
                outcome = failure_for_platform_error(
                    error(PlatformErrorCode::Cancelled, &reason),
                    outcome_consumption(&outcome),
                );
            }
        }
        let outcome = self
            .journal
            .take()
            .expect("live terminal reservation")
            .finish(outcome);
        drop(self.cancellation.take());
        outcome
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
        } else {
            PlatformErrorCode::Cancelled
        };
        let outcome = failure_for_platform_error(
            error(
                code,
                "activation handle abandoned before terminal completion",
            ),
            BudgetConsumption::default(),
        );
        let _ = self.publish(outcome);
    }
}
