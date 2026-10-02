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
        self.before_guest_currentness(request, cancellation, stop, || {
            self.shared
                .preparation_context
                .start_execution(runtime, request)
        })
        .await
    }

    pub(super) async fn capability_session(
        &self,
        runtime: &PreparedRuntime,
        request: &ExecutionRequest,
        cancellation: &dyn ExecutionCancellation,
        stop: &StopControl,
        deadline: &latent_core::EffectiveDeadline,
    ) -> Result<
        Result<Option<latent_capabilities::broker::CapabilitySession>, GuestOutcome>,
        PlatformError,
    > {
        let Some(owner) = &self.shared.capabilities else {
            return Ok(Ok(None));
        };
        let publication = runtime.eligibility.as_ref().ok_or_else(|| {
            crate::containment::platform_error(
                latent_core::PlatformErrorCode::PermissionDenied,
                "capability publication owner required",
                false,
            )
        })?;
        // All admission-currentness checks in open_session precede the session
        // registration and its allocation. A successful original session is
        // returned once; no guest call or accepted provider operation is here.
        self.before_guest_currentness(request, cancellation, stop, || {
            owner
                .open_session(request, cancellation, publication, deadline)
                .map(Some)
        })
        .await
    }

    async fn before_guest_currentness<T>(
        &self,
        request: &ExecutionRequest,
        cancellation: &dyn ExecutionCancellation,
        stop: &StopControl,
        mut check: impl FnMut() -> Result<T, PlatformError>,
    ) -> Result<Result<T, GuestOutcome>, PlatformError> {
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
                check().map(Ok)
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
