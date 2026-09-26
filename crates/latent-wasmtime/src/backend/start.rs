//! Bounded currentness observations before any Store or guest is created.

use latent_core::{BudgetConsumption, PlatformError};
use latent_executor::{ExecutionCancellation, ExecutionRequest, GuestOutcome};

use super::admission::ExecutionEligibility;
use super::{cancellation_before_execution, PreparedRuntime, WasmtimeBackend};
use crate::containment::{interrupted_outcome, StopControl};

impl WasmtimeBackend {
    pub(super) async fn execution_eligibility(
        &self,
        runtime: &PreparedRuntime,
        request: &ExecutionRequest,
        cancellation: &dyn ExecutionCancellation,
        stop: &StopControl,
    ) -> Result<Result<ExecutionEligibility, GuestOutcome>, PlatformError> {
        let window =
            super::readiness::wait::Window::new(self.shared.currentness_read_wait.as_deref());
        // Only the pure final authorization decision is repeated. The caller
        // retains one original prepared use and its capacity permit. No cache
        // lookup, re-verification, grant renewal, capability session, Store or
        // guest invocation is inside this loop. Timer-less callers fail closed.
        let result = window
            .check(|| {
                if let Some(outcome) =
                    cancellation_before_execution(&request.activation.activation_id, cancellation)?
                {
                    return Ok(Err(outcome));
                }
                if let Some(kind) = stop.observe() {
                    return Ok(Err(interrupted_outcome(
                        kind,
                        stop.reason(kind),
                        BudgetConsumption::default(),
                    )));
                }
                self.shared
                    .preparation_context
                    .start_execution(runtime, request)
                    .map(Ok)
            })
            .await;
        // The original stop wins even when the finite read window expires at
        // the same instant. Never report contention in place of cancellation.
        if let Some(outcome) =
            cancellation_before_execution(&request.activation.activation_id, cancellation)?
        {
            return Ok(Err(outcome));
        }
        if let Some(kind) = stop.observe() {
            return Ok(Err(interrupted_outcome(
                kind,
                stop.reason(kind),
                BudgetConsumption::default(),
            )));
        }
        result
    }
}
