//! The input and its diagnostic guard share one actual destruction boundary.

use std::future::Future;
use std::pin::Pin;
use std::task::{Context, Poll};

use latent_core::{BoxFuture, PlatformError};
use latent_executor::{ExecutionCancellation, ExecutionRequest, GuestOutcome};

use crate::invocation_input_observer::{InputTrace, InvocationObservation, RawGuard};
use crate::{InvocationInputDropReason, InvocationInputObserver, Phase0InvocationTiming};

use super::{
    elapsed_micros, validate_request_context, Instant, WasmtimeBackend, WasmtimePreparedUse,
};

impl WasmtimeBackend {
    /// Independent diagnostics; disabled for ordinary execution and profiling.
    #[must_use]
    pub fn invocation_input_observer(&self) -> InvocationInputObserver {
        self.shared.invocation_input_observer.clone()
    }

    /// Uses the exact borrowed context validator without creating a Store or call.
    pub fn invocation_context_charge(
        &self,
        request: &ExecutionRequest,
    ) -> Result<crate::InvocationContextCharge, PlatformError> {
        crate::host::request_context::context_charge(
            request,
            self.config.maximum_artifact_metadata_bytes,
        )
    }

    pub(super) async fn invoke_inner(
        &self,
        request: ExecutionRequest,
        cancellation: &dyn ExecutionCancellation,
        prepared: Option<WasmtimePreparedUse>,
    ) -> Result<GuestOutcome, PlatformError> {
        validate_request_context(&request, self.config.maximum_artifact_metadata_bytes)?;
        let activation_id = request.activation.activation_id.clone();
        let started = Instant::now();
        let mut timing = Phase0InvocationTiming::default();
        let outcome = if let Some(observation) =
            self.shared.invocation_input_observer.begin(&activation_id)
        {
            let trace = observation.trace();
            observe(
                self.invoke_inner_timed(request, cancellation, &mut timing, prepared, Some(&trace)),
                observation,
            )
            .await
        } else {
            self.invoke_inner_timed(request, cancellation, &mut timing, prepared, None)
                .await
        };
        timing.backend_total_micros = elapsed_micros(started);
        self.lock_timings().insert(activation_id.0, timing);
        outcome
    }
}

/// Field order releases the owned value before reporting its raw-owner release.
/// The type parameter permits destructor-order tests without an unsafe allocator.
pub(super) struct RawInvocationInput<T = Vec<u8>> {
    bytes: T,
    observation: Option<RawGuard>,
}

impl RawInvocationInput {
    pub(super) fn new(bytes: Vec<u8>, trace: Option<&InputTrace>) -> Self {
        let observation = trace.and_then(|trace| trace.raw_owner(bytes.len(), bytes.capacity()));
        Self { bytes, observation }
    }

    pub(super) fn bytes(&self) -> &[u8] {
        &self.bytes
    }
}

impl<T> RawInvocationInput<T> {
    /// Sets only the release label; field destruction still releases the actual
    /// bytes before the guard records that release.
    pub(super) fn release(mut self, reason: InvocationInputDropReason) {
        if let Some(observation) = &mut self.observation {
            observation.set_reason(reason);
        }
        drop(self);
    }
}

/// Only enabled proof calls allocate this extra wrapper. Ordinary invocation
/// polling uses the original future directly.
pub(super) async fn observe<'a, T>(
    future: impl Future<Output = T> + Send + 'a,
    observation: InvocationObservation,
) -> T {
    let mut observed = ObservedInvocation {
        future: Box::pin(future),
        observation,
    };
    let result = (&mut observed).await;
    drop(observed);
    result
}

struct ObservedInvocation<'a, T> {
    // A completed or abandoned future is destroyed before its retirement guard.
    future: BoxFuture<'a, T>,
    observation: InvocationObservation,
}

impl<T> Future for ObservedInvocation<'_, T> {
    type Output = T;

    fn poll(self: Pin<&mut Self>, context: &mut Context<'_>) -> Poll<T> {
        let this = self.get_mut();
        let result = this.future.as_mut().poll(context);
        if result.is_ready() {
            this.observation.completed();
        }
        result
    }
}

#[cfg(test)]
mod tests;
