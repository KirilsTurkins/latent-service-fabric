//! One fresh guest call; affine runtime and instance ownership retire together.
use std::sync::Arc;
use std::time::Instant;

use latent_core::{BudgetConsumption, PlatformError, PlatformErrorCode};
use latent_executor::{ExecutionCancellation, ExecutionRequest, GuestOutcome};
use wasmtime::component::Val;

use super::{
    call_export, classify_call_result, elapsed_micros, input, invocation_accounting,
    is_memory_limit_error, reclamation, AccountedStore, PreparedRuntime, WasmtimeBackend,
};
use crate::cache::ActiveInstancePermit;
use crate::containment::{interrupted_outcome, platform_error, StopControl};
use crate::host::accounting::InvocationAccounting;
use crate::invocation_input_observer::{
    InputTrace, InvocationInputDropReason, InvocationInputPhase,
};
use crate::values;
use crate::Phase0InvocationTiming;

pub(super) struct ContainedInvocation<'a> {
    pub request: ExecutionRequest,
    pub runtime: Arc<PreparedRuntime>,
    pub instance_permit: ActiveInstancePermit,
    pub accounting: InvocationAccounting,
    pub stop: &'a Arc<StopControl>,
    pub setup_started: Instant,
    pub input_trace: Option<&'a InputTrace>,
}

impl WasmtimeBackend {
    pub(super) async fn invoke_contained(
        &self,
        invocation: ContainedInvocation<'_>,
        cancellation: &dyn ExecutionCancellation,
        timing: &mut Phase0InvocationTiming,
        capability_observer: &mut Option<latent_capabilities::broker::CapabilitySessionObserver>,
    ) -> Result<GuestOutcome, PlatformError> {
        let ContainedInvocation {
            mut request,
            instance_permit,
            runtime,
            accounting,
            stop,
            setup_started,
            input_trace,
        } = invocation;
        let function = self.requested_function(&runtime, &request)?;
        let transaction =
            self.invocation_transaction(&runtime, &request, &accounting, cancellation)?;
        let temporary_buffer_guard = self.shared.resources.temporary_buffer();
        let raw_input = input::RawInvocationInput::new(
            std::mem::take(&mut request.activation.input),
            input_trace,
        );
        let input = values::decode_params(
            &function.params,
            raw_input.bytes(),
            &request.activation.input_media_type,
            runtime.surface.value_codec_limits,
        )?;

        let capabilities =
            self.invocation_capabilities(&runtime, &request, &accounting, cancellation)?;
        *capability_observer = capabilities
            .as_ref()
            .map(latent_capabilities::broker::CapabilitySession::observer);
        if let Some(kind) = stop.observe() {
            return Ok(interrupted_outcome(
                kind,
                &stop.reason(kind),
                BudgetConsumption::default(),
            ));
        }

        let contained_execution_started = self.shared.clock.monotonic_now();
        let host_state_guard = self.shared.resources.host_state();
        let store_guard = self.shared.resources.store();
        let mut store = AccountedStore::new(self.invocation_store(
            request,
            stop,
            accounting,
            capabilities,
            transaction,
            runtime.surface.hostcall_fuel,
        )?);
        // Decoding and every borrowed validation have completed. The Store now
        // owns only the moved context; destroy the actual raw input before call.
        raw_input.release(InvocationInputDropReason::BeforeGuestCall);

        let component_instance_guard = self.shared.resources.component_instance();
        let mut output = vec![Val::Bool(false); function.results.len()];
        if let Some(trace) = input_trace {
            trace.stage(InvocationInputPhase::BeforeCallExport);
        }
        let call_result = call_export(
            &runtime,
            function,
            &mut store,
            &input,
            &mut output,
            timing,
            setup_started,
            input_trace,
        )
        .await;
        // Wasmtime 47's safe dynamic call completes canonical ABI post-return
        // before resolving, including propagation of post-return traps.
        let component_post_return_started = Instant::now();
        let wall_time_micros = self.execution_wall_time_micros(contained_execution_started);
        let (consumption, accounting_error) =
            invocation_accounting(&mut store, wall_time_micros, timing);
        let memory_exhausted = call_result
            .as_ref()
            .err()
            .is_some_and(is_memory_limit_error);
        timing.component_post_return_micros = elapsed_micros(component_post_return_started);

        let encoded = call_result.as_ref().ok().map(|()| {
            values::encode_result(&function.results, &output, runtime.surface.value_codec_limits)
        });
        // Cleanup order is intentional: after the guest call and its
        // component-model post-return complete, the actual component instance,
        // store/host state, temporary input, and all activation-owned guards
        // are reclaimed before a reusable proof escapes.
        let reclamation_started = Instant::now();
        drop(store);
        drop(component_instance_guard);
        drop(store_guard);
        drop(host_state_guard);
        drop(input);
        drop(output);
        drop(temporary_buffer_guard);
        timing.activation_resource_reclamation_micros = elapsed_micros(reclamation_started);

        reclamation::finish(runtime, instance_permit, timing, || {
            classify_call_result(
                call_result,
                encoded,
                stop,
                memory_exhausted,
                consumption,
                accounting_error,
            )
        })
    }

    fn execution_wall_time_micros(&self, started: Instant) -> u64 {
        u64::try_from(
            self.shared
                .clock
                .monotonic_now()
                .saturating_duration_since(started)
                .as_micros(),
        )
        .unwrap_or(u64::MAX)
    }

    fn invocation_transaction(
        &self,
        runtime: &PreparedRuntime,
        request: &ExecutionRequest,
        accounting: &InvocationAccounting,
        cancellation: &dyn ExecutionCancellation,
    ) -> Result<Option<Arc<dyn latent_executor::transaction::TransactionHost>>, PlatformError> {
        let transaction = cancellation.transaction_host();
        let needs_transaction = runtime
            .surface
            .imports
            .contains(crate::surface::transaction::STATE)
            || runtime
                .surface
                .imports
                .contains(crate::surface::transaction::INTENTS);
        if needs_transaction && transaction.is_none() {
            return Err(platform_error(
                PlatformErrorCode::PermissionDenied,
                "scoped transaction execution owner required",
                false,
            ));
        }
        if let Some(host) = &transaction {
            if !self.config.transactional_state
                || !needs_transaction
                || host.activation_id() != &request.activation.activation_id
                || !host.budget().is_same_instance(accounting.budget())
            {
                return Err(platform_error(
                    PlatformErrorCode::PermissionDenied,
                    "transaction execution owner mismatch",
                    false,
                ));
            }
        }
        Ok(transaction)
    }

    fn invocation_capabilities(
        &self,
        runtime: &PreparedRuntime,
        request: &ExecutionRequest,
        accounting: &InvocationAccounting,
        cancellation: &dyn ExecutionCancellation,
    ) -> Result<Option<latent_capabilities::broker::CapabilitySession>, PlatformError> {
        self.shared
            .capabilities
            .as_ref()
            .map(|owner| {
                let publication = runtime.eligibility.as_ref().ok_or_else(|| {
                    platform_error(
                        PlatformErrorCode::PermissionDenied,
                        "capability publication owner required",
                        false,
                    )
                })?;
                owner.open_session(request, cancellation, publication, accounting.deadline())
            })
            .transpose()
    }
}
