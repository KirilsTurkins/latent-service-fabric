use latent_activation::{ActivationEvent, ActivationOutcome};
use latent_core::{
    ActivationId, ActivationPhase, ActivationTerminalState, BudgetConsumption, Metadata,
    PlatformError, PlatformErrorCode,
};

use super::{bytes, error, LocalActivationJournal, MAXIMUM_EVENTS, TERMINAL_RESERVE_BYTES};

/// The manager retains this token from synchronous start through cleanup. Its
/// Drop fallback covers a start abandoned before admission; the manager's guard
/// must finish every admitted activation with finalized consumption first.
pub(crate) struct JournalOwner {
    journal: LocalActivationJournal,
    id: ActivationId,
    serial: u64,
    finished: bool,
}

impl JournalOwner {
    pub(super) fn new(journal: LocalActivationJournal, id: ActivationId, serial: u64) -> Self {
        Self {
            journal,
            id,
            serial,
            finished: false,
        }
    }

    pub(crate) fn advance(
        &mut self,
        phase: ActivationPhase,
        attributes: Metadata,
    ) -> Result<(), PlatformError> {
        let sample = self.journal.inner.clock.sample();
        let mut state = self.journal.inner.lock();
        let record = state.records.get_mut(&self.id).expect("live journal owner");
        if record.serial != self.serial
            || record.status.terminal_state.is_some()
            || !legal(record.status.phase, phase)
        {
            return Err(error(
                PlatformErrorCode::StateConflict,
                "invalid-activation-phase-transition",
            ));
        }
        let available =
            self.journal.inner.config.maximum_record_bytes - record.bytes - TERMINAL_RESERVE_BYTES;
        let attribute_bytes = bytes::metadata(&attributes, available / 2)? * 2;
        let now = sample
            .unix_millis()
            .max(record.status.last_updated_unix_millis);
        record.status.metadata.extend(attributes.clone());
        record.status.phase = phase;
        record.status.last_updated_unix_millis = now;
        record.events.push(ActivationEvent {
            activation_id: self.id.clone(),
            phase,
            terminal_state: None,
            occurred_at_unix_millis: now,
            sequence: record.events.last().expect("received event").sequence + 1,
            attributes,
        });
        record.bytes += attribute_bytes;
        debug_assert!(record.events.len() < MAXIMUM_EVENTS);
        Ok(())
    }

    /// Call before publishing a terminal cancellation decision. A rejection can
    /// then be mapped to a small resource-exhausted outcome without changing an
    /// already-published terminal classification.
    pub(crate) fn validate_terminal(
        &self,
        outcome: &ActivationOutcome,
    ) -> Result<(), PlatformError> {
        let state = self.journal.inner.lock();
        let record = state.records.get(&self.id).expect("live journal owner");
        bytes::outcome(
            outcome,
            self.journal.inner.config.maximum_record_bytes - record.bytes,
        )
        .map(|_| ())
        .map_err(|_| {
            error(
                PlatformErrorCode::ResourceExhausted,
                "activation-terminal-record-too-large",
            )
        })
    }

    /// Completes event/status publication in one local transaction. No resource
    /// ledger is finalized here. The returned outcome is identical after prior
    /// validation; a defensive oversized-input fallback stays bounded.
    pub(crate) fn finish(mut self, outcome: ActivationOutcome) -> ActivationOutcome {
        let outcome = self.complete(outcome);
        self.finished = true;
        outcome
    }

    fn complete(&self, mut outcome: ActivationOutcome) -> ActivationOutcome {
        let mut state = self.journal.inner.lock();
        // Sample within the publication boundary so TTL timestamps follow the
        // same order as terminal FIFO insertion, even with contending owners.
        let sample = self.journal.inner.clock.sample();
        let record = state.records.get(&self.id).expect("live journal owner");
        let available = self.journal.inner.config.maximum_record_bytes - record.bytes;
        let terminal_bytes = if let Ok(bytes) = bytes::outcome(&outcome, available) {
            bytes
        } else {
            outcome = ActivationOutcome::Failed {
                terminal_state: ActivationTerminalState::ResourceExhausted,
                error: error(
                    PlatformErrorCode::ResourceExhausted,
                    "activation-terminal-record-too-large",
                ),
                consumption: consumption(&outcome).clone(),
            };
            bytes::outcome(&outcome, available).expect("reserved minimal terminal space")
        };
        while state.snapshot.terminal >= self.journal.inner.config.maximum_terminal {
            assert!(
                state.evict_oldest(),
                "terminal count has an evictable record"
            );
        }
        let record = state
            .records
            .get_mut(&self.id)
            .expect("active record cannot be evicted");
        debug_assert_eq!(record.serial, self.serial);
        let terminal_state = terminal_state(&outcome);
        let now = sample
            .unix_millis()
            .max(record.status.last_updated_unix_millis);
        record.status.terminal_state = Some(terminal_state);
        record.status.terminal_outcome = Some(outcome.retained_terminal_outcome());
        record.status.final_consumption = Some(consumption(&outcome).clone());
        record.status.last_updated_unix_millis = now;
        record.status.terminal_at_unix_millis = Some(now);
        record.events.push(ActivationEvent {
            activation_id: self.id.clone(),
            phase: record.status.phase,
            terminal_state: Some(terminal_state),
            occurred_at_unix_millis: now,
            sequence: record.events.last().expect("received event").sequence + 1,
            attributes: Metadata::new(),
        });
        record.terminal_at = Some(sample.monotonic());
        record.bytes += terminal_bytes;
        let retained = record.bytes;
        // Completions cannot outnumber begins, whose checked serial allocation
        // rejects exhaustion before publishing a record.
        let completion_order = state.snapshot.completed;
        state
            .terminal_order
            .insert(completion_order, (self.id.clone(), self.serial));
        state.snapshot.active -= 1;
        state.snapshot.reserved_bytes -= self.journal.inner.config.maximum_record_bytes;
        state.snapshot.retained_bytes += retained;
        state.snapshot.terminal += 1;
        state.snapshot.completed = state.snapshot.completed.saturating_add(1);
        outcome
    }
}

impl Drop for JournalOwner {
    fn drop(&mut self) {
        if !self.finished {
            self.complete(ActivationOutcome::Failed {
                terminal_state: ActivationTerminalState::Cancelled,
                error: error(PlatformErrorCode::Cancelled, "activation-handle-dropped"),
                consumption: BudgetConsumption::default(),
            });
        }
    }
}

fn legal(current: ActivationPhase, next: ActivationPhase) -> bool {
    matches!(
        (current, next),
        (ActivationPhase::Received, ActivationPhase::Resolved)
            | (ActivationPhase::Resolved, ActivationPhase::Admitted)
            | (ActivationPhase::Admitted, ActivationPhase::Queued)
            | (ActivationPhase::Queued, ActivationPhase::Materializing)
            | (ActivationPhase::Materializing, ActivationPhase::Running)
    )
}

fn consumption(outcome: &ActivationOutcome) -> &BudgetConsumption {
    match outcome {
        ActivationOutcome::Succeeded(success) => &success.consumption,
        ActivationOutcome::DeclaredError { consumption, .. }
        | ActivationOutcome::Failed { consumption, .. } => consumption,
    }
}

fn terminal_state(outcome: &ActivationOutcome) -> ActivationTerminalState {
    match outcome {
        ActivationOutcome::Succeeded(_) | ActivationOutcome::DeclaredError { .. } => {
            ActivationTerminalState::Completed
        }
        ActivationOutcome::Failed { terminal_state, .. } => *terminal_state,
    }
}
