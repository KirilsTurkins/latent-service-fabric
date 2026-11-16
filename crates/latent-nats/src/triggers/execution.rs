use super::{consumer::Ack, driver::stopped, InboxDelivery, TriggerBinding, TriggerTerminal};
use crate::EventError;
use latent_activation::{ActivationOutcome, ActivationRequest, TraceContext};
use latent_core::ClockSample;
use latent_core::{
    ActivationId, ContractId, FunctionId, IncomingDeadline, InvocationPrincipal, Metadata,
    PlatformErrorCode, PrincipalKind, ServiceId, SpanId, TenantId, TraceId,
};
use latent_node::transaction_runtime::{NativeTransactionAdmission, OwnedTransactionCompletion};
use latent_node::{
    ActivationTransportInterruption, InboundActivationReservation, LocalActivationManager,
};
use latent_routing::InvocationTarget;
use std::{sync::Arc, time::Duration};
use tokio::sync::watch;

pub(super) async fn execute(
    mut reservation: InboundActivationReservation,
    payload: &[u8],
    stop: &mut watch::Receiver<bool>,
    transaction: Option<(&InboxDelivery, Arc<NativeTransactionAdmission>)>,
) -> (
    TriggerTerminal,
    Ack,
    bool,
    Option<OwnedTransactionCompletion>,
) {
    reservation.input_buffer()[..payload.len()].copy_from_slice(payload);
    let Ok(mut activation) = reservation.start(payload.len()) else {
        return if transaction.is_some() {
            (TriggerTerminal::RecoveryRequired, Ack::Hold, false, None)
        } else {
            (TriggerTerminal::Rejected, Ack::Retry, false, None)
        };
    };
    let receipt = tokio::select! {
        biased;
        ()=stopped(stop)=>{
            let cleanup = activation.interrupt_for_cleanup(ActivationTransportInterruption::Disconnected);
            let _ = tokio::time::timeout(Duration::from_secs(3), cleanup).await;
            let (terminal, ack) = interrupted(transaction.is_some());
            return (terminal, ack, true, None);
        },
        receipt=&mut activation=>receipt,
    };
    if let Some((delivery, admission)) = transaction {
        let completion = admission.take_owned_completion().ok().flatten();
        let (terminal, ack, retained) = transaction_outcome(completion, delivery);
        (terminal, ack, false, retained)
    } else {
        let (terminal, ack) = outcome(&receipt.outcome);
        (terminal, ack, false, None)
    }
}

pub(super) fn interrupted(transactional: bool) -> (TriggerTerminal, Ack) {
    if transactional {
        // A detached cleanup does not prove whether the durable owner committed.
        (TriggerTerminal::RecoveryRequired, Ack::Hold)
    } else {
        (TriggerTerminal::Cancelled, Ack::Retry)
    }
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
        budget: binding.activation_budget(),
        // Display names are not part of the durable input identity. Including
        // them in transaction metadata would change the command fingerprint on
        // a compatible trigger rename and prevent recovery of a redelivery.
        metadata: if binding.transaction.is_some() {
            Metadata::new()
        } else {
            Metadata::from([("trigger.id".into(), binding.id.clone())])
        },
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

pub(super) fn transaction_outcome(
    completion: Option<OwnedTransactionCompletion>,
    delivery: &InboxDelivery,
) -> (TriggerTerminal, Ack, Option<OwnedTransactionCompletion>) {
    use latent_node::transaction_runtime::{
        CommandCompletionDisposition, TransactionCompletionResult,
    };
    let Some(completion) = completion else {
        return (TriggerTerminal::RecoveryRequired, Ack::Hold, None);
    };
    let record = match &completion.result {
        TransactionCompletionResult::Command(CommandCompletionDisposition::Durable {
            command,
            cleanup_failure: None,
            ..
        })
        | TransactionCompletionResult::Existing {
            command,
            result: Ok(_),
            ..
        } => Some(command),
        _ => None,
    };
    let terminal = record
        .filter(|record| delivery.matches(record))
        .and_then(|record| match record.outcome() {
            latent_commit::atomic::Outcome::Committed => Some(TriggerTerminal::Succeeded),
            latent_commit::atomic::Outcome::Rejected => Some(TriggerTerminal::DeclaredFailure),
            latent_commit::atomic::Outcome::Pending | latent_commit::atomic::Outcome::Aborted => {
                None
            }
        });
    if let Some(terminal) = terminal {
        if completion.authority.with_current(&mut || {}).is_ok() {
            return (terminal, Ack::Success, Some(completion));
        }
    }
    (TriggerTerminal::RecoveryRequired, Ack::Hold, None)
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
