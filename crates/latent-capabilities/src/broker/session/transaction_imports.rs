//! Scoped state imports are owned by the original transaction, not a provider plan.

use latent_core::{ActivationBudget, BudgetProfile};
use latent_executor::{ExecutionCancellation, ExecutionRequest};

use super::CompiledCapabilityPlan;
use crate::namespace::{INTENT_CONTRACT, STATE_CONTRACT};

pub(super) fn matches(
    plan: &CompiledCapabilityPlan,
    request: &ExecutionRequest,
    web_projection: bool,
    cancellation: &dyn ExecutionCancellation,
    budget: &ActivationBudget,
) -> bool {
    let scoped = |name: &str| matches!(name, STATE_CONTRACT | INTENT_CONTRACT);
    let count = request
        .imports
        .iter()
        .filter(|import| scoped(&import.contract))
        .count();
    if count == 0 {
        return super::imports_match(plan, request, web_projection);
    }
    let Some(host) = cancellation.transaction_host() else {
        return false;
    };
    if web_projection
        || budget.profile() != BudgetProfile::Phase4
        || host.activation_id() != &request.activation.activation_id
        || !host.budget().is_same_instance(budget)
        || request.activation.parent_activation_id.is_some()
        || budget.granted().child_calls != 0
        || budget.granted().outbound_requests != 0
        || plan
            .bindings
            .iter()
            .any(|binding| scoped(&binding.provider.capability))
        || ![STATE_CONTRACT, INTENT_CONTRACT].iter().all(|contract| {
            let imports = request
                .imports
                .iter()
                .filter(|import| import.contract == *contract);
            imports.clone().count() <= 1
                && imports.into_iter().all(|import| {
                    import.capability.0 == *contract && !import.opaque_handle.is_empty()
                })
        })
        || !request
            .imports
            .iter()
            .any(|import| import.contract == STATE_CONTRACT)
    {
        return false;
    }
    // Every ordinary import still matches one original sealed provider binding.
    // Descriptive transaction imports grant no state or staging call themselves.
    request.imports.len() == plan.bindings.len() + count
        && plan.bindings.iter().all(|binding| {
            request
                .imports
                .iter()
                .filter(|import| {
                    import.contract == binding.provider.capability
                        && import.capability.0 == binding.provider.capability
                })
                .count()
                == 1
        })
}
