use super::{
    authorization, PlatformError, TransactionAdmissionOwners, TransactionInstallation,
    TransactionSelection,
};
use latent_activation::ActivationEnvelope;
use latent_capabilities::namespace::{CallerScope, STATE_CONTRACT};
use latent_core::ActivationBudget;
use latent_policy::capability::{
    CallRestrictions, CapabilityCeiling, EvaluationInput, OwnedPolicyDecision, ResourceTarget,
};
use std::time::Instant;

pub(super) struct Initial {
    pub before: OwnedPolicyDecision,
    pub after: OwnedPolicyDecision,
    pub caller: CallerScope,
}
pub(super) fn initial(
    owners: &TransactionAdmissionOwners,
    installation: &TransactionInstallation,
    selection: &TransactionSelection,
    envelope: &ActivationEnvelope,
    budget: &latent_core::ActivationBudget,
) -> Result<Initial, PlatformError> {
    let caller = CallerScope::derive(&envelope.principal, &installation.recovery)?;
    if envelope.principal.tenant.as_ref() != Some(&envelope.target.tenant)
        || budget.profile() != latent_core::BudgetProfile::Phase4
        || budget.deadline().is_expired_at(Instant::now())
        || budget.descendant_is_cancelled()
        || selection.operation != envelope.target.function.0
        || (selection.mode == latent_manifest::TransactionOperationMode::FreshQuery
            && (budget.granted().state_write_bytes != 0 || budget.granted().effect_count != 0))
    {
        return Err(authorization::denied());
    }
    let binding = &installation.state;
    let snapshot = owners.policy.snapshot(
        &envelope.target.tenant,
        &binding.policies,
        &binding.binding,
        budget
            .deadline()
            .monotonic()
            .ok_or_else(authorization::denied)?,
    )?;
    let remaining = ceiling(budget)?;
    let decision = snapshot.authorize(
        EvaluationInput {
            principal: &envelope.principal,
            service: &envelope.target.service.0,
            publication: installation.publication.publication().as_str(),
            capability: STATE_CONTRACT,
            operation: if selection.mode == latent_manifest::TransactionOperationMode::StrictCommand
            {
                "acquire-command"
            } else {
                "acquire-query"
            },
            resource: ResourceTarget::State {
                namespace: &selection.namespace,
                incarnation: selection.incarnation,
                entity: selection.entity.as_deref(),
                recovery_kind: caller.kind,
                recovery_scope: &caller.scope,
                result_policy: &installation.result_read_policy,
            },
        },
        &CallRestrictions {
            imported_operations: &binding.operations,
            deployment: &binding.deployment,
            provider_configuration: &binding.provider_configuration,
            provider_profile: &binding.profile,
            configuration_digest: &binding.configuration_digest,
            configuration_epoch: binding.configuration_epoch,
            remaining,
            input_bytes: u64::try_from(envelope.input.len())
                .map_err(|_| authorization::denied())?,
            output_bytes: 0,
        },
        &installation.publication,
    )?;
    if decision.requires_audit() {
        return Err(authorization::denied());
    }
    // Both capabilities retain the identical original stamp/deadline. The
    // second is consumed against the post-Pending generation, without renewal.
    Ok(Initial {
        before: owners.policy.retain_decision(&decision)?,
        after: owners.policy.retain_decision(&decision)?,
        caller,
    })
}
fn ceiling(budget: &ActivationBudget) -> Result<CapabilityCeiling, PlatformError> {
    let wall_time_millis = u64::try_from(
        budget
            .deadline()
            .remaining_at(Instant::now())
            .ok_or_else(authorization::denied)?
            .as_millis(),
    )
    .map_err(|_| authorization::denied())?
    .min(30_000);
    if wall_time_millis == 0 {
        return Err(authorization::denied());
    }
    let remaining = budget.granted();
    Ok(CapabilityCeiling {
        operations: 256,
        input_bytes: remaining
            .state_read_bytes
            .max(remaining.state_write_bytes)
            .min(2_097_152),
        output_bytes: remaining.state_read_bytes.min(2_097_152),
        wall_time_millis,
    })
}
