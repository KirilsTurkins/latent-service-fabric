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
        self.read_before_store(request, cancellation, stop, || {
            self.shared
                .preparation_context
                .start_execution(runtime, request)
        })
        .await
    }

    pub(super) async fn capability_session(
        &self,
        owner: &latent_capabilities::broker::ActivationCapabilityRuntime,
        request: &ExecutionRequest,
        cancellation: &dyn ExecutionCancellation,
        publication: &latent_artifacts::ReleaseUseEligibility,
        deadline: &latent_core::EffectiveDeadline,
        stop: &StopControl,
    ) -> Result<Result<latent_capabilities::broker::CapabilitySession, GuestOutcome>, PlatformError>
    {
        // The exact admission.currentness busy error can arise only during
        // plan/publication observations, before the broker allocates a session.
        // Successful session opening is never repeated. Capacity, revocation,
        // provider publication, policy and all other errors remain immediate.
        self.read_before_store(request, cancellation, stop, || {
            owner.open_session(request, cancellation, publication, deadline)
        })
        .await
    }

    async fn read_before_store<T>(
        &self,
        request: &ExecutionRequest,
        cancellation: &dyn ExecutionCancellation,
        stop: &StopControl,
        mut read: impl FnMut() -> Result<T, PlatformError>,
    ) -> Result<Result<T, GuestOutcome>, PlatformError> {
        let window =
            super::readiness::wait::Window::new(self.shared.currentness_read_wait.as_deref());
        // The caller retains one original prepared use, publication, ledger
        // and capacity permit. An unsuccessful authority observation allocates
        // no session or Store and starts no provider or guest work. Timer-less
        // callers fail closed. The read window does not extend the original stop.
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
                read().map(Ok)
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
