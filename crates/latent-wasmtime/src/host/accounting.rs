//! Shares one activation ledger while sampling Wasmtime's native counters.

use std::time::Instant;

use latent_core::{
    ActivationBudget, ActivationClock, BudgetDimension, BudgetError, ClockSample,
    EffectiveActivationBudget, EffectiveDeadline, PlatformError, PlatformErrorCode, ResourceBudget,
};
use latent_executor::{ExecutionCancellation, ExecutionRequest};

/// A fuel watermark is observation state, not another resource allowance.
/// The activation owner alone finalizes the shared accounting handle.
#[derive(Debug)]
pub(crate) struct InvocationAccounting {
    budget: ActivationBudget,
    deadline: EffectiveDeadline,
    initial_fuel: u64,
    last_remaining_fuel: u64,
    confirmed_peak_memory: u64,
}

impl InvocationAccounting {
    pub(crate) fn new(
        request: &ExecutionRequest,
        cancellation: &dyn ExecutionCancellation,
        clock: &dyn ActivationClock,
    ) -> Result<Self, PlatformError> {
        if cancellation.activation_id() != &request.activation.activation_id {
            return Err(invalid(
                "execution cancellation belongs to another activation",
            ));
        }
        if request.budget != request.activation.budget {
            return Err(invalid("execution-budget-grant-mismatch"));
        }
        request
            .budget
            .validate_phase1_request()
            .map_err(|error| error.to_platform_error())?;
        let (budget, deadline) = if let Some(budget) = cancellation.budget_accounting() {
            if budget.granted() != &request.budget {
                return Err(invalid("execution-budget-grant-mismatch"));
            }
            ensure_live(budget)?;
            let mut deadline = budget.deadline().clone();
            if request
                .activation
                .deadline_unix_millis
                .is_some_and(|requested| {
                    deadline
                        .unix_millis()
                        .is_none_or(|current| requested < current)
                })
            {
                // Only a genuinely tighter explicit request needs conversion.
                // The ordinary path preserves the original precise deadline.
                deadline = grant(request, Some(&deadline), clock)?.deadline;
            }
            if let Some(supplied) = cancellation.effective_deadline() {
                tighten(&mut deadline, supplied);
            }
            (budget.clone(), deadline)
        } else {
            let grant = grant(request, cancellation.effective_deadline(), clock)?;
            let deadline = grant.deadline.clone();
            (ActivationBudget::new(grant), deadline)
        };
        let now = clock.monotonic_now();
        if let Some(observer) = clock.deadline_diagnostic_observer() {
            observer.record_for_activation(
                &request.activation.activation_id.0,
                latent_core::DeadlineDiagnosticObservation::ExecutionDeadline {
                    observed_at: now,
                    deadline: deadline.clone(),
                    budget: budget.granted().clone(),
                },
            );
        }
        check_deadline(&deadline, now)?;
        let initial_fuel = budget.remaining_at(now).cpu_fuel;
        if initial_fuel == 0 {
            return Err(BudgetError::Exhausted {
                dimension: BudgetDimension::CpuFuel,
                limit: budget.granted().cpu_fuel,
                consumed: budget.granted().cpu_fuel,
                requested: 1,
            }
            .to_platform_error());
        }
        Ok(Self {
            budget,
            deadline,
            initial_fuel,
            last_remaining_fuel: initial_fuel,
            confirmed_peak_memory: 0,
        })
    }

    pub(crate) fn budget(&self) -> &ActivationBudget {
        &self.budget
    }
    pub(crate) fn deadline(&self) -> &EffectiveDeadline {
        &self.deadline
    }
    pub(crate) fn initial_fuel(&self) -> u64 {
        self.initial_fuel
    }

    /// Call at store-aware host checkpoints and once after execution. Memory
    /// must exclude any growth that has not yet survived `memory_grow_failed`.
    pub(crate) fn observe_runtime(
        &mut self,
        remaining_fuel: u64,
        confirmed_peak_memory: u64,
    ) -> Result<(), PlatformError> {
        let fuel = self
            .last_remaining_fuel
            .checked_sub(remaining_fuel)
            .ok_or_else(|| invalid("execution fuel counter increased unexpectedly"))?;
        if confirmed_peak_memory > self.budget.granted().memory_bytes {
            return Err(BudgetError::Exhausted {
                dimension: BudgetDimension::MemoryBytes,
                limit: self.budget.granted().memory_bytes,
                consumed: self.confirmed_peak_memory,
                requested: confirmed_peak_memory,
            }
            .to_platform_error());
        }
        self.budget
            .observe_runtime_usage(fuel, confirmed_peak_memory)
            .map_err(|error| error.to_platform_error())?;
        // Both ledger dimensions commit together. Failed observations leave
        // both watermarks unchanged, so a valid retry charges exactly once.
        self.last_remaining_fuel = remaining_fuel;
        self.confirmed_peak_memory = self.confirmed_peak_memory.max(confirmed_peak_memory);
        Ok(())
    }

    /// `effective_cell_memory` is the TOTAL physical cell allowance. Subtract
    /// confirmed peak usage here; callers must not subtract it a second time.
    pub(crate) fn remaining_at(
        &self,
        now: Instant,
        effective_cell_memory: u64,
    ) -> Result<ResourceBudget, PlatformError> {
        ensure_live(&self.budget)?;
        let mut remaining = self.budget.remaining_at(now);
        remaining.memory_bytes = remaining
            .memory_bytes
            .min(effective_cell_memory.saturating_sub(self.confirmed_peak_memory));
        remaining.wall_time_limit_millis = self
            .deadline
            .remaining_at(now)
            .map(|duration| u64::try_from(duration.as_millis()).unwrap_or(u64::MAX));
        Ok(remaining)
    }
}

fn grant(
    request: &ExecutionRequest,
    original: Option<&EffectiveDeadline>,
    clock: &dyn ActivationClock,
) -> Result<EffectiveActivationBudget, PlatformError> {
    let sample = original.map_or_else(
        || clock.sample(),
        |deadline| {
            ClockSample::new(
                deadline.admitted_at_unix_millis(),
                deadline.admitted_at_monotonic(),
            )
        },
    );
    let absolute = request.activation.deadline_unix_millis.filter(|requested| {
        original
            .and_then(EffectiveDeadline::unix_millis)
            .is_none_or(|current| *requested < current)
    });
    let mut grant = EffectiveActivationBudget::admit_at(
        &request.budget,
        &request.budget,
        &request.budget,
        absolute,
        sample,
    )
    .map_err(|error| error.to_platform_error())?;
    if let Some(original) = original {
        // A token's Unix value is diagnostic: after a wall-clock jump it may
        // precede its admission sample. Only a new stricter explicit request
        // above is converted; the admitted precise token remains authoritative.
        tighten(&mut grant.deadline, original);
    }
    grant
        .require_executable_capacity()
        .map_err(|error| error.to_platform_error())?;
    Ok(grant)
}

fn tighten(deadline: &mut EffectiveDeadline, supplied: &EffectiveDeadline) {
    if supplied.monotonic().is_some_and(|supplied| {
        deadline
            .monotonic()
            .is_none_or(|current| supplied < current)
    }) {
        *deadline = supplied.clone();
    }
}

fn ensure_live(budget: &ActivationBudget) -> Result<(), PlatformError> {
    if budget.finalization().is_some() {
        Err(BudgetError::AccountingFinalized.to_platform_error())
    } else {
        Ok(())
    }
}

fn check_deadline(deadline: &EffectiveDeadline, now: Instant) -> Result<(), PlatformError> {
    if deadline.is_expired_at(now) {
        return Err(BudgetError::DeadlineExceeded {
            deadline_unix_millis: deadline
                .unix_millis()
                .expect("expired deadline has wall representation"),
            admitted_at_unix_millis: deadline.admitted_at_unix_millis(),
        }
        .to_platform_error());
    }
    Ok(())
}

fn invalid(message: &str) -> PlatformError {
    PlatformError {
        code: PlatformErrorCode::InvalidArgument,
        message: message.to_owned(),
        retryable: false,
        details: Vec::new(),
    }
}

#[cfg(test)]
mod tests;
