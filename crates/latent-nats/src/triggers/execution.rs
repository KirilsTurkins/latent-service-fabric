use super::{consumer::Ack, driver::stopped, TriggerBinding, TriggerTerminal};
use crate::EventError;
use latent_activation::{ActivationOutcome, ActivationRequest, TraceContext};
use latent_core::ClockSample;
use latent_core::{
    ActivationId, ContractId, FunctionId, IncomingDeadline, InvocationPrincipal, Metadata,
    PlatformErrorCode, PrincipalKind, ServiceId, SpanId, TenantId, TraceId,
};
use latent_node::{
    ActivationTransportInterruption, InboundActivationReservation, LocalActivationManager,
};
use latent_routing::InvocationTarget;
use std::time::Duration;
use tokio::sync::watch;

pub(super) async fn execute(
    mut reservation: InboundActivationReservation,
    payload: &[u8],
    stop: &mut watch::Receiver<bool>,
) -> (TriggerTerminal, Ack, bool) {
    reservation.input_buffer()[..payload.len()].copy_from_slice(payload);
    let Ok(mut activation) = reservation.start(payload.len()) else {
        return (TriggerTerminal::Rejected, Ack::Retry, false);
    };
    let receipt = tokio::select! {
        biased;
        ()=stopped(stop)=>{
            let cleanup = activation.interrupt_for_cleanup(ActivationTransportInterruption::Disconnected);
            let _ = tokio::time::timeout(Duration::from_secs(3), cleanup).await;
            return (TriggerTerminal::Cancelled, Ack::Retry, true);
        },
        receipt=&mut activation=>receipt,
    };
    let (terminal, ack) = outcome(&receipt.outcome);
    (terminal, ack, false)
}
pub(super) fn root_request(
    binding: &TriggerBinding,
    id: ActivationId,
    deadline: IncomingDeadline,
) -> ActivationRequest {
    ActivationRequest {
        activation_id: Some(id.clone()),
        parent_activation_id: None,
        root_activation_id: None,
        principal: InvocationPrincipal {
            subject: binding.principal_subject.clone(),
            kind: PrincipalKind::Trigger,
            tenant: Some(TenantId(binding.tenant.clone())),
            service: None,
            claims: Metadata::new(),
        },
        target: InvocationTarget {
            tenant: TenantId(binding.tenant.clone()),
            service: ServiceId(binding.service.clone()),
            contract: ContractId(binding.contract.clone()),
            function: FunctionId(binding.function.clone()),
            route: binding.route.clone(),
        },
        deadline_unix_millis: Some(deadline.unix_millis()),
        priority: 0,
        trace: TraceContext {
            trace_id: TraceId(id.0.clone()),
            span_id: SpanId(id.0),
            trace_flags: 0,
            baggage: Metadata::new(),
        },
        idempotency_key: None,
        retry_attempt: 0,
        budget: binding.budget.budget(),
        metadata: Metadata::from([("trigger.id".into(), binding.id.clone())]),
        input: Vec::new(),
        input_media_type: "application/vnd.latent.wit-values.v1+json".into(),
    }
}
pub(super) fn outcome(outcome: &ActivationOutcome) -> (TriggerTerminal, Ack) {
    match outcome {
        ActivationOutcome::Succeeded(_) => (TriggerTerminal::Succeeded, Ack::Success),
        ActivationOutcome::DeclaredError { .. } => {
            (TriggerTerminal::DeclaredFailure, Ack::Terminate)
        }
        ActivationOutcome::Failed { error, .. } => match error.code {
            PlatformErrorCode::PermissionDenied
            | PlatformErrorCode::Unauthenticated
            | PlatformErrorCode::InvalidArgument
            | PlatformErrorCode::IncompatibleContract => {
                (TriggerTerminal::Rejected, Ack::Terminate)
            }
            PlatformErrorCode::DeadlineExceeded => (TriggerTerminal::TimedOut, Ack::Retry),
            PlatformErrorCode::Cancelled => (TriggerTerminal::Cancelled, Ack::Retry),
            _ => (TriggerTerminal::Failed, Ack::Retry),
        },
    }
}

impl super::NatsTriggers {
    pub(super) fn reserve(
        &mut self,
        manager: &LocalActivationManager,
        index: usize,
    ) -> crate::Result<(InboundActivationReservation, IncomingDeadline, String)> {
        self.sequence = self
            .sequence
            .checked_add(1)
            .ok_or(EventError::BudgetExhausted)?;
        let inbox = format!("{}.{:016x}", self.namespace, self.sequence);
        let id = ActivationId(format!(
            "trigger-{}-{:016x}",
            &self.namespace[11..],
            self.sequence
        ));
        let binding = &self.config.bindings[index];
        let arrival = ClockSample::system_now();
        let duration = Duration::from_millis(self.config.operation_timeout_millis);
        let deadline = IncomingDeadline::new(
            arrival.monotonic() + duration,
            arrival.unix_millis() + self.config.operation_timeout_millis,
        );
        let reservation = manager.reserve_inbound(
            root_request(binding, id, deadline),
            self.config.maximum_payload_bytes,
            deadline,
        )?;
        reservation.publication_eligibility()?;
        Ok((reservation, deadline, inbox))
    }
}
