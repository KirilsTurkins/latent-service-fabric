//! Typed private RPCs reuse the installed transaction and activation owners.
mod projection;
mod selection;
use super::{StateRequest, StateRuntime};
use latent_core::{ActivationClock, BoxFuture, IncomingDeadline, PlatformError};
use latent_node::{
    transaction_runtime::command_completion::{CanonicalCommandResult, CommandResultCodec},
    LocalActivationManager,
};
use latent_wire::{
    invocation::{
        ActivationCleanupHandle, InvocationLimits, InvocationTraceSource, LocalPrincipalPolicy,
        PrincipalPolicy, SystemInvocationTraceSource,
    },
    phase4::{contract, OwnedPhase4Response, Phase4Call, Phase4Runtime},
};
use std::sync::Arc;

pub(super) struct InstalledTransactionRpc {
    state: Arc<StateRuntime>,
    manager: LocalActivationManager,
    cleanup: ActivationCleanupHandle,
    management: Arc<dyn Phase4Runtime>,
    limits: InvocationLimits,
    clock: Arc<dyn ActivationClock>,
    traces: SystemInvocationTraceSource,
}
impl StateRuntime {
    pub(crate) fn transaction_rpc(
        self: &Arc<Self>,
        manager: LocalActivationManager,
        cleanup: ActivationCleanupHandle,
        limits: InvocationLimits,
        clock: Arc<dyn ActivationClock>,
    ) -> Result<Arc<dyn Phase4Runtime>, PlatformError> {
        limits.validate()?;
        if limits.budget_profile != latent_core::BudgetProfile::Phase4 {
            return Err(unavailable());
        }
        let management = self.management().ok_or_else(unavailable)?;
        Ok(Arc::new(InstalledTransactionRpc {
            state: Arc::clone(self),
            manager,
            cleanup,
            management: Arc::new(management),
            limits,
            clock,
            traces: SystemInvocationTraceSource::default(),
        }))
    }
}
impl InstalledTransactionRpc {
    fn start(
        &self,
        call: Phase4Call,
    ) -> Result<BoxFuture<'_, Result<OwnedPhase4Response, PlatformError>>, PlatformError> {
        call.request().validate().map_err(|_| denied())?;
        let (context, message) = call.into_parts();
        LocalPrincipalPolicy.authenticate(context.principal())?;
        let expires = context.transport_expires_at().ok_or_else(denied)?;
        let unix = context
            .transport_deadline_unix_millis()
            .ok_or_else(denied)?;
        if expires <= self.clock.monotonic_now() {
            return Err(unavailable());
        }
        let mut selected = selection::select(message)?;
        let invocation = std::mem::take(&mut selected.invocation);
        let mut request = latent_wire::invocation::transaction_activation_request(
            invocation,
            &context,
            self.traces.next_trace()?,
            &self.limits,
            &LocalPrincipalPolicy,
        )?;
        let payload = std::mem::take(&mut request.input);
        if payload.is_empty() || payload.len() > self.limits.max_payload_bytes {
            return Err(denied());
        }
        let slot = self.cleanup.reserve_activation()?;
        let mut reservation = self.manager.reserve_inbound(
            request,
            payload.len(),
            IncomingDeadline::new(expires, unix),
        )?;
        let proof = reservation.publication_eligibility()?;
        let installed = self
            .state
            .installed(&reservation.revision().target, &proof)?;
        selected.check(&installed)?;
        let query = selected.query;
        let original_command = selected.original_command.clone();
        let admission = self.state.admission(
            Arc::clone(&installed),
            selected.request,
            Arc::new(RpcResultCodec),
        )?;
        reservation.bind_transaction(admission)?;
        reservation.input_buffer().copy_from_slice(&payload);
        let handle = reservation.start(payload.len())?;
        let retained = slot.own(handle, installed);
        let limits = &self.limits;
        let clock = self.clock.as_ref();
        Ok(Box::pin(async move {
            let (receipt, installed) = retained.await;
            projection::response(
                receipt,
                &installed,
                query,
                original_command.as_ref(),
                limits,
                clock,
            )
        }))
    }
}
impl Phase4Runtime for InstalledTransactionRpc {
    fn execute(
        &self,
        call: Phase4Call,
    ) -> BoxFuture<'_, Result<OwnedPhase4Response, PlatformError>> {
        if !matches!(
            call.request(),
            contract::Request::InvokeCommand(_) | contract::Request::Query(_)
        ) {
            return self.management.execute(call);
        }
        match self.start(call) {
            Ok(future) => future,
            Err(error) => Box::pin(std::future::ready(Err(error))),
        }
    }
}
struct RpcResultCodec;
impl CommandResultCodec for RpcResultCodec {
    fn format(&self) -> &str {
        CanonicalCommandResult.format()
    }
    fn validate(
        &self,
        outcome: &latent_activation::ActivationOutcome,
    ) -> Result<latent_node::transaction_runtime::command_completion::CommandOutput, PlatformError>
    {
        bounded_result(outcome)?;
        CanonicalCommandResult.validate(outcome)
    }
    fn replay(
        &self,
        record: &latent_commit::atomic::CommandRecord,
        result: &latent_commit::atomic::DurableResult,
        consumption: latent_core::BudgetConsumption,
    ) -> Result<latent_activation::ActivationOutcome, PlatformError> {
        let outcome = CanonicalCommandResult.replay(record, result, consumption)?;
        bounded_result(&outcome)?;
        Ok(outcome)
    }
}
fn bounded_result(outcome: &latent_activation::ActivationOutcome) -> Result<(), PlatformError> {
    let bytes = match outcome {
        latent_activation::ActivationOutcome::Succeeded(value) => value.output.len(),
        latent_activation::ActivationOutcome::DeclaredError { error, .. } => error.payload.len(),
        latent_activation::ActivationOutcome::Failed { error, .. } => return Err(error.clone()),
    };
    // Two typed projections plus encoding temporaries fit the original native
    // response reservation; refuse before commitment, without enlarging it.
    if bytes > 64 * 1024 {
        return Err(denied());
    }
    Ok(())
}
fn denied() -> PlatformError {
    super::denied()
}
fn unavailable() -> PlatformError {
    super::unavailable()
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn rpc_result_codec_refuses_unrepresentable_output_before_the_business_writer() {
        let make = |size| {
            latent_activation::ActivationOutcome::Succeeded(latent_activation::ActivationSuccess {
                output: vec![b'x'; size],
                output_media_type: "application/vnd.latent.wit-values.v1+json".into(),
                metadata: Default::default(),
                consumption: Default::default(),
                committed_state_version: None,
                effect_ids: vec![],
            })
        };
        assert!(RpcResultCodec.validate(&make(64 * 1024)).is_ok());
        assert!(RpcResultCodec.validate(&make(64 * 1024 + 1)).is_err());
    }
}
