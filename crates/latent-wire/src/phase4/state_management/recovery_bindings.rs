use super::{
    capacity, contract, denied, invalid, AuthenticatedInvocationContext, Inner, PlatformError,
};
use latent_capabilities::namespace::{CallerScope, RecoverySelection};

/// Trusted installation data, never a delegation token or reusable grant.
pub struct StateManagementRecoveryBinding {
    pub selector: String,
    pub selection: RecoverySelection,
}

pub(super) fn validate(
    bindings: &Vec<StateManagementRecoveryBinding>,
) -> Result<(), PlatformError> {
    if bindings.len() > 128 || bindings.capacity() > 128 {
        return Err(capacity());
    }
    for (index, binding) in bindings.iter().enumerate() {
        identity(&binding.selector)?;
        if bindings[..index]
            .iter()
            .any(|other| other.selector == binding.selector)
        {
            return Err(invalid());
        }
        match &binding.selection {
            RecoverySelection::Delegated {
                delegation,
                service,
            } => {
                identity(delegation)?;
                identity(service)?;
            }
            RecoverySelection::Shared { name } => identity(name)?,
            RecoverySelection::OriginalCaller | RecoverySelection::ServiceIntegration => {}
        }
    }
    Ok(())
}
fn identity(value: &String) -> Result<(), PlatformError> {
    latent_core::transaction_contract::identity(value).map_err(|_| invalid())?;
    if value.capacity() > 1024 || value.chars().any(char::is_control) {
        return Err(capacity());
    }
    Ok(())
}
pub(super) fn scope(
    inner: &Inner,
    context: &AuthenticatedInvocationContext,
    selector: Option<&str>,
) -> Result<CallerScope, PlatformError> {
    let selection = match selector {
        None => &RecoverySelection::OriginalCaller,
        Some(name) => {
            &inner
                .recovery_bindings
                .as_ref()
                .ok_or_else(denied)?
                .iter()
                .find(|binding| binding.selector == name)
                .ok_or_else(denied)?
                .selection
        }
    };
    CallerScope::derive(context.principal(), selection)
}

pub(super) fn command(
    request: &contract::Request,
) -> Result<Option<&latent_rpc::transaction::v1::CommandSelector>, PlatformError> {
    let original = match request {
        contract::Request::PlanEffectMutation(value) => Some(value.as_ref()),
        contract::Request::MutateState(value) => value
            .effect_plan
            .as_ref()
            .and_then(|plan| plan.original.as_ref()),
        contract::Request::GetStateOperationReceipt(value) => value
            .original_effect_plan
            .as_ref()
            .and_then(|plan| plan.original.as_ref()),
        _ => None,
    };
    original
        .map(|value| {
            value
                .effect
                .as_ref()
                .ok_or_else(invalid)?
                .command
                .as_ref()
                .ok_or_else(invalid)
        })
        .transpose()
}
