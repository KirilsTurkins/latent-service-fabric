use super::{control, model, phase4, transaction};

pub(super) fn invalid_failure(
    context: &super::Context,
    audit: Option<&crate::network::AuditAcknowledgement>,
    unsupported_audit: Option<i32>,
    identity: model::RecoveryIdentity,
    observed: Option<model::ObservedOutcome>,
) -> model::ClientFailure {
    let mut error = unsupported_audit
        .map_or_else(
            || super::RpcFailure::local(super::FailureKind::InvalidResponse),
            |status| super::RpcFailure::unsupported("audit.status", &status.to_string()),
        )
        .received(&context.transport_identity(), audit);
    error.outcome_known = observed.as_ref().is_some_and(known);
    model::ClientFailure {
        transport: Box::new(error.into()),
        identity: Box::new(identity),
        observed,
    }
}

pub(super) trait NativeReply: Sized {
    fn check(
        self,
        association: &phase4::Association,
    ) -> (
        Self,
        Result<(), phase4::ValidationError>,
        Option<model::ObservedOutcome>,
        Option<i32>,
    );
}

fn command(value: &transaction::CommandInspection) -> model::ObservedOutcome {
    model::ObservedOutcome::Command(Box::new(model::CommandObservation {
        command_id: value.command_id.clone(),
        attempt_id: value.attempt_id.clone(),
        outcome: model::CommandOutcome(value.outcome),
        metadata_durable: value.metadata_durable,
        application_state_committed: value.application_state_committed,
        fingerprint_sha256: value.fingerprint_sha256.clone(),
        commit: value.commit.clone().map(Into::into),
        proven_abort: value.proven_abort.clone().map(Into::into),
        source: value.source.clone().map(Into::into),
        retention: value.retention.clone().map(Into::into),
    }))
}

fn observe(value: &phase4::Response) -> Option<model::ObservedOutcome> {
    use phase4::Response;
    match value {
        Response::InvokeCommand(value) => value.command.as_ref().map(command),
        Response::LookupCommand(value) => value.command.as_ref().map(command),
        Response::LookupCommit(value) => value.command.as_ref().map(command),
        Response::CancelCommand(value) => value.command.as_ref().map(command),
        Response::GetEffect(value) => value
            .effect
            .clone()
            .map(|value| model::ObservedOutcome::Effect(Box::new(value.into()))),
        Response::MutateState(value) => value
            .receipt
            .clone()
            .map(|value| model::ObservedOutcome::State(Box::new(value.into()))),
        Response::MutateNamespace(value) => value
            .receipt
            .clone()
            .map(|value| model::ObservedOutcome::Namespace(Box::new(value.into()))),
        Response::GetStateOperationReceipt(value) => value
            .receipt
            .clone()
            .map(|value| model::ObservedOutcome::State(Box::new(value.into())))
            .or_else(|| {
                value
                    .namespace_receipt
                    .clone()
                    .map(|value| model::ObservedOutcome::Namespace(Box::new(value.into())))
            }),
        Response::ControlDispatcher(value) => value
            .receipt
            .clone()
            .map(|value| model::ObservedOutcome::Dispatcher(Box::new(value.into()))),
        Response::GetDispatcherOperation(value) => value
            .receipt
            .clone()
            .map(|value| model::ObservedOutcome::Dispatcher(Box::new(value.into()))),
        _ => None,
    }
}

pub(super) fn known(value: &model::ObservedOutcome) -> bool {
    match value {
        model::ObservedOutcome::Command(value) => {
            value.metadata_durable
                && matches!(
                    value.outcome,
                    model::CommandOutcome::COMMITTED
                        | model::CommandOutcome::REJECTED
                        | model::CommandOutcome::ABORTED
                )
        }
        model::ObservedOutcome::State(receipt) => matches!(
            receipt.disposition,
            model::StateOperationDisposition::COMMITTED
                | model::StateOperationDisposition::CONFLICT
                | model::StateOperationDisposition::REJECTED
        ),
        model::ObservedOutcome::Namespace(receipt) => matches!(
            receipt.disposition,
            model::StateOperationDisposition::COMMITTED
                | model::StateOperationDisposition::CONFLICT
                | model::StateOperationDisposition::REJECTED
        ),
        // A provider dispatch observation never establishes a command outcome.
        model::ObservedOutcome::Effect(_) => false,
        model::ObservedOutcome::Dispatcher(receipt) => {
            receipt.disposition == model::StateOperationDisposition::COMMITTED
        }
    }
}

pub(super) fn extend_identity(
    identity: &mut model::RecoveryIdentity,
    value: Option<&model::ObservedOutcome>,
) {
    match value {
        Some(model::ObservedOutcome::Command(value)) => {
            if !value.fingerprint_sha256.is_empty() {
                identity.fingerprint_sha256 = Some(value.fingerprint_sha256.clone());
            }
            if identity.attempt_id.is_none() && !value.attempt_id.is_empty() {
                identity.attempt_id = Some(value.attempt_id.clone());
            }
            if identity.receipt_id.is_none() {
                identity.receipt_id = value
                    .commit
                    .as_ref()
                    .map(|receipt| receipt.receipt_id.clone());
            }
        }
        Some(model::ObservedOutcome::State(receipt)) => {
            identity.receipt_id = Some(receipt.receipt_id.clone());
        }
        Some(model::ObservedOutcome::Namespace(receipt)) => {
            identity.receipt_id = Some(receipt.receipt_id.clone());
        }
        Some(model::ObservedOutcome::Dispatcher(receipt)) => {
            identity.receipt_id = Some(receipt.receipt_id.clone());
        }
        Some(model::ObservedOutcome::Effect(receipt)) => {
            identity.effect_id = Some(receipt.effect_id.clone());
            if identity.attempt_id.is_none() {
                identity.attempt_id = Some(receipt.command_attempt_id.clone());
            }
        }
        _ => {}
    }
}

fn audit_slot(value: &mut phase4::Response) -> Option<&mut Option<control::AuditAck>> {
    use phase4::Response;
    match value {
        Response::MutateState(value) => Some(&mut value.audit_ack),
        Response::MutateNamespace(value) => Some(&mut value.audit_ack),
        Response::InspectDispatcher(value) => Some(&mut value.audit_ack),
        Response::ControlDispatcher(value) => Some(&mut value.audit_ack),
        Response::GetDispatcherOperation(value) => Some(&mut value.audit_ack),
        _ => None,
    }
}

macro_rules! reply {
    ($(($variant:ident, $module:ident::$message:ident)),+ $(,)?) => {
        $(impl NativeReply for $module::$message {
            fn check(self, association: &phase4::Association) -> (Self, Result<(), phase4::ValidationError>, Option<model::ObservedOutcome>, Option<i32>) {
                let mut envelope = phase4::Response::$variant(Box::new(self));
                let audit = audit_slot(&mut envelope).and_then(Option::take);
                let primary = envelope.validate_association(association);
                let observation = if primary.is_ok() { observe(&envelope) } else { None };
                let bad_audit = audit.as_ref().filter(|audit| !(1..=4).contains(&audit.status)).map(|audit| audit.status);
                let validation = primary.and_then(|()| if bad_audit.is_some() { Err(phase4::ValidationError::Shape) } else { Ok(()) });
                if let Some(slot) = audit_slot(&mut envelope) { *slot = audit; }
                let phase4::Response::$variant(value) = envelope else { unreachable!() };
                (*value, validation, observation, bad_audit)
            }
        })+
    };
}
reply!(
    (InvokeCommand, transaction::InvokeCommandResponse),
    (Query, transaction::QueryResponse),
    (LookupCommand, transaction::LookupCommandResponse),
    (LookupCommit, transaction::LookupCommitResponse),
    (GetEffect, transaction::GetEffectResponse),
    (ListEffectHistory, transaction::ListEffectHistoryResponse),
    (CancelCommand, transaction::CancelCommandResponse),
    (MutateNamespace, control::MutateNamespaceResponse),
    (InspectNamespace, control::InspectNamespaceResponse),
    (SelectEntity, control::SelectEntityResponse),
    (MutateState, control::MutateStateResponse),
    (
        GetStateOperationReceipt,
        control::GetStateOperationReceiptResponse
    ),
    (InspectDispatcher, control::InspectDispatcherResponse),
    (ControlDispatcher, control::ControlDispatcherResponse),
    (
        GetDispatcherOperation,
        control::GetDispatcherOperationResponse
    )
);
