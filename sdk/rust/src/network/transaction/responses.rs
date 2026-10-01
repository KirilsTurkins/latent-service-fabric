use super::{control, model, phase4, transaction};

pub(super) trait NativeReply: Sized {
    fn check(
        self,
        association: &phase4::Association,
    ) -> (
        Self,
        Result<(), phase4::ValidationError>,
        Option<model::ObservedOutcome>,
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
        Some(model::ObservedOutcome::Effect(receipt)) => {
            identity.effect_id = Some(receipt.effect_id.clone());
            if identity.attempt_id.is_none() {
                identity.attempt_id = Some(receipt.command_attempt_id.clone());
            }
        }
        _ => {}
    }
}

macro_rules! reply {
    ($(($variant:ident, $module:ident::$message:ident)),+ $(,)?) => {
        $(impl NativeReply for $module::$message {
            fn check(self, association: &phase4::Association) -> (Self, Result<(), phase4::ValidationError>, Option<model::ObservedOutcome>) {
                let envelope = phase4::Response::$variant(Box::new(self));
                let validation = envelope.validate_association(association);
                let observation = if validation.is_ok() { observe(&envelope) } else { None };
                let phase4::Response::$variant(value) = envelope else { unreachable!() };
                (*value, validation, observation)
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
    )
);
