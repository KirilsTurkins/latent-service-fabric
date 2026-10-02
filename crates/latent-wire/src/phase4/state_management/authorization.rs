use super::{
    c, capacity, contract, denied, error, expired, invalid, namespace_error, Arc,
    AuthenticatedInvocationContext, Instant, PlatformError, PlatformErrorCode,
    StateManagementBinding, StateManagementServices,
};
use latent_artifacts::ReleaseUseEligibility;
use latent_capabilities::namespace::{CallerScope, RecoverySelection, STATE_CONTRACT};
use latent_policy::capability::{
    CallRestrictions, CapabilityCeiling, EvaluationInput, OwnedPolicyDecision, ResourceTarget,
};

pub(super) struct Access {
    pub binding: Arc<StateManagementBinding>,
    pub caller: CallerScope,
    pub inspect: OwnedPolicyDecision,
    pub mutation: Option<OwnedPolicyDecision>,
}
/// A descriptive SHA-256 precondition over original sealed configuration, not a
/// permission. Every operation still rechecks its actual retained policy owner.
pub(super) fn policy_precondition(access: &Access) -> String {
    use sha2::{Digest, Sha256};
    let mut hash = Sha256::new();
    hash.update(b"lsf-namespace-policy-precondition-v1\0");
    hash.update(access.inspect.configuration_digest());
    for text in [
        &access.binding.namespace.0,
        &access.binding.result_policy,
        &access.binding.state_schema,
        &access.binding.state.profile,
        &access.binding.state.configuration_digest,
    ] {
        hash.update((text.len() as u64).to_be_bytes());
        hash.update(text.as_bytes());
    }
    hash.update(access.binding.incarnation.to_be_bytes());
    hash.update(access.binding.state.configuration_epoch.to_be_bytes());
    format!(
        "sha256:{:x}",
        latent_core::digest::HexDigest(hash.finalize())
    )
}
pub(super) fn validate_binding(value: &StateManagementBinding) -> Result<(), PlatformError> {
    if value.publication.scope.tenant().is_none()
        || value.incarnation == 0
        || value.state.configuration_epoch == 0
        || value.state.policies.is_empty()
        || value.state.policies.len() > 8
        || value.state.policies.capacity() > 8
        || value.state.operations.is_empty()
        || value.state.operations.len() > 32
        || value.state.operations.capacity() > 32
    {
        return Err(invalid());
    }
    for text in value
        .state
        .policies
        .iter()
        .chain(&value.state.operations)
        .chain([
            &value.namespace.0,
            &value.service.0,
            &value.result_policy,
            &value.state_schema,
            &value.state.binding,
            &value.state.profile,
            &value.state.configuration_digest,
        ])
    {
        latent_core::transaction_contract::identity(text).map_err(|_| invalid())?;
        if text.capacity() > 1024 || text.chars().any(char::is_control) {
            return Err(capacity());
        }
    }
    value.maximum_quota.validate().map_err(namespace_error)?;
    if !value
        .state
        .operations
        .iter()
        .any(|operation| operation == "namespace-inspect")
    {
        return Err(invalid());
    }
    Ok(())
}
pub(super) async fn authorize(
    services: &StateManagementServices,
    binding: &Arc<StateManagementBinding>,
    context: &AuthenticatedInvocationContext,
    request: &contract::Request,
    deadline: Instant,
) -> Result<Access, PlatformError> {
    let tenant = binding.publication.scope.tenant().ok_or_else(denied)?;
    let entry = services
        .artifacts
        .get_selected_catalog_entry(&binding.publication.scope, &binding.publication)
        .await?
        .ok_or_else(denied)?;
    if entry.publication.as_ref() != Some(&binding.publication.id)
        || entry.tenant.as_ref() != Some(tenant)
        || entry.service != binding.service
        || entry.descriptor.release_digest != binding.component
    {
        return Err(denied());
    }
    let publication = services
        .artifacts
        .execution_eligibility_selected(&binding.component, Some(&binding.publication.id))?
        .ok_or_else(denied)?;
    let caller = CallerScope::derive(context.principal(), &RecoverySelection::OriginalCaller)?;
    let original = OriginalAccess {
        services,
        binding,
        context,
        publication: &publication,
        caller: &caller,
        deadline,
        input_bytes: request.encoded_len(),
    };
    let mutation = match request {
        contract::Request::MutateNamespace(value) => {
            Some(original.seal(mutation_operation(value.mutation)?, binding.incarnation)?)
        }
        _ => None,
    };
    let response_incarnation = if matches!(request, contract::Request::MutateNamespace(value) if value.mutation == c::NamespaceMutationKind::Recreate as i32)
    {
        binding.incarnation.checked_add(1).ok_or_else(capacity)?
    } else {
        binding.incarnation
    };
    let inspect = original.seal("namespace-inspect", response_incarnation)?;
    if (inspect.requires_audit()
        || mutation
            .as_ref()
            .is_some_and(OwnedPolicyDecision::requires_audit))
        && services.audit.is_none()
    {
        return Err(error(
            PlatformErrorCode::Unavailable,
            "namespace-audit-owner-required",
        ));
    }
    Ok(Access {
        binding: Arc::clone(binding),
        caller,
        inspect,
        mutation,
    })
}
struct OriginalAccess<'a> {
    services: &'a StateManagementServices,
    binding: &'a StateManagementBinding,
    context: &'a AuthenticatedInvocationContext,
    publication: &'a ReleaseUseEligibility,
    caller: &'a CallerScope,
    deadline: Instant,
    input_bytes: usize,
}
impl OriginalAccess<'_> {
    fn seal(
        &self,
        operation: &str,
        incarnation: u64,
    ) -> Result<OwnedPolicyDecision, PlatformError> {
        let OriginalAccess {
            services,
            binding,
            context,
            publication,
            caller,
            deadline,
            input_bytes,
        } = *self;
        let now = services.clock.monotonic_now();
        if now >= deadline {
            return Err(expired());
        }
        let wall_time_millis = u64::try_from(deadline.saturating_duration_since(now).as_millis())
            .map_err(|_| expired())?
            .min(30000);
        let snapshot = services.policy.snapshot(
            binding.publication.scope.tenant().ok_or_else(denied)?,
            &binding.state.policies,
            &binding.state.binding,
            deadline,
        )?;
        let decision = snapshot.authorize(
            EvaluationInput {
                principal: context.principal(),
                service: &binding.service.0,
                publication: publication.publication().as_str(),
                capability: STATE_CONTRACT,
                operation,
                resource: ResourceTarget::State {
                    namespace: &binding.namespace.0,
                    incarnation,
                    entity: None,
                    recovery_kind: caller.kind,
                    recovery_scope: &caller.scope,
                    result_policy: &binding.result_policy,
                },
            },
            &CallRestrictions {
                imported_operations: &binding.state.operations,
                deployment: &binding.state.deployment,
                provider_configuration: &binding.state.provider_configuration,
                provider_profile: &binding.state.profile,
                configuration_digest: &binding.state.configuration_digest,
                configuration_epoch: binding.state.configuration_epoch,
                remaining: CapabilityCeiling {
                    operations: 1,
                    input_bytes: contract::MAX_REQUEST_BYTES as u64,
                    output_bytes: contract::MAX_RESPONSE_BYTES as u64,
                    wall_time_millis,
                },
                input_bytes: u64::try_from(input_bytes).map_err(|_| capacity())?,
                output_bytes: contract::MAX_RESPONSE_BYTES as u64,
            },
            publication,
        )?;
        services.policy.retain_decision(&decision)
    }
}
pub(super) fn mutation_operation(kind: i32) -> Result<&'static str, PlatformError> {
    match c::NamespaceMutationKind::try_from(kind) {
        Ok(c::NamespaceMutationKind::Create) => Ok("namespace-create"),
        Ok(c::NamespaceMutationKind::Quiesce) => Ok("namespace-quiesce"),
        Ok(c::NamespaceMutationKind::Retire) => Ok("namespace-retire"),
        Ok(c::NamespaceMutationKind::Destroy) => Ok("namespace-destroy"),
        Ok(c::NamespaceMutationKind::Recreate) => Ok("namespace-recreate"),
        _ => Err(invalid()),
    }
}
