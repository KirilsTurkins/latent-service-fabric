use super::{
    c, contract, invalid, unsupported, Access, Action, EffectManagementInput, Error, PlatformError,
    Request,
};
use prost::Message;
use sha2::{Digest, Sha256};

pub(super) fn original(
    request: &contract::Request,
) -> Result<&c::PlanEffectMutationRequest, PlatformError> {
    match request {
        contract::Request::PlanEffectMutation(value) => Ok(value),
        contract::Request::MutateState(value) => value
            .effect_plan
            .as_ref()
            .and_then(|plan| plan.original.as_ref())
            .ok_or_else(invalid),
        contract::Request::GetStateOperationReceipt(value) => value
            .original_effect_plan
            .as_ref()
            .and_then(|plan| plan.original.as_ref())
            .ok_or_else(invalid),
        _ => Err(unsupported()),
    }
}
pub(super) fn supplied_plan(request: &contract::Request) -> Option<&c::EffectManagementPlan> {
    match request {
        contract::Request::MutateState(value) => value.effect_plan.as_ref(),
        contract::Request::GetStateOperationReceipt(value) => value.original_effect_plan.as_ref(),
        _ => None,
    }
}
pub(super) fn action(value: i32) -> Result<Action, PlatformError> {
    match c::StateMutationKind::try_from(value) {
        Ok(c::StateMutationKind::RetryKnownFailedEffect) => Ok(Action::Redrive),
        Ok(c::StateMutationKind::ReconcileEffect) => Ok(Action::Reconcile),
        Ok(c::StateMutationKind::TerminateEffect) => Ok(Action::Terminate),
        _ => Err(invalid()),
    }
}
pub(super) const fn operation(action: Action) -> &'static str {
    match action {
        Action::Redrive => "effect-redrive",
        Action::Reconcile => "effect-reconcile",
        Action::Terminate => "effect-terminate",
    }
}
pub(super) fn actor(access: &Access) -> String {
    format!(
        "{}:{}",
        access.namespace.caller.owner_kind, access.namespace.caller.scope
    )
}
pub(super) fn digest(original: &c::PlanEffectMutationRequest) -> [u8; 32] {
    let mut hash = Sha256::new();
    hash.update(b"lsf-effect-management-original-request-v1\0");
    hash.update(original.encode_to_vec());
    hash.finalize().into()
}
pub(super) fn native_request(
    access: &Access,
    original: &c::PlanEffectMutationRequest,
    record: &latent_commit::atomic::CommandRecord,
) -> Result<Request, Error> {
    let effect = original.effect.as_ref().ok_or(Error::Invalid)?;
    Request::new(EffectManagementInput {
        actor_tenant: access
            .principal
            .tenant
            .as_ref()
            .ok_or(Error::PermissionDenied)?
            .0
            .clone(),
        actor_subject: actor(access),
        namespace: access.namespace.binding.namespace.0.clone(),
        incarnation: access.namespace.binding.incarnation,
        caller_scope: access.caller.scope.clone(),
        command: record.id().hex(),
        command_attempt: record.attempt(),
        effect: effect.effect_id.clone(),
        operation_id: original.operation_id.clone(),
        action: access.action,
        expected_version: original
            .expected_version
            .as_slice()
            .try_into()
            .map_err(|_| Error::Invalid)?,
        expected_policy_digest: original.expected_policy_digest.clone(),
        original_request_digest: digest(original),
        reason: original.reason.clone(),
        retry_delay_millis: original.retry_delay_millis,
    })
}
