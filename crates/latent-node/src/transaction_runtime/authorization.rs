//! Fresh policy intersection with the original captured namespace decision.
use latent_artifacts::ReleaseUseEligibility;
use latent_capabilities::namespace::{NamespaceAuthority, INTENT_CONTRACT, STATE_CONTRACT};
use latent_core::{ActivationBudget, InvocationPrincipal, PlatformError, PlatformErrorCode};
use latent_policy::capability::{
    CallRestrictions, CapabilityCeiling, EvaluationInput, PolicyStore,
    ResourceTarget,
};
use latent_state::namespace::catalog::NamespaceRead;
use std::{sync::Arc, time::Instant};

pub use crate::PolicyCallBinding;

pub struct StateAuthorization {
    policy: Arc<PolicyStore>,
    pub(super) authority: Arc<NamespaceAuthority>,
    pub(super) namespace: Arc<NamespaceRead>,
    principal: InvocationPrincipal,
    service: String,
    publication: ReleaseUseEligibility,
    state: PolicyCallBinding,
    intents: Option<PolicyCallBinding>,
    pub(super) budget: ActivationBudget,
}
impl StateAuthorization {
    pub(super) fn publication(&self) -> &str {
        self.publication.publication().as_str()
    }
    #[allow(
        clippy::too_many_arguments,
        reason = "Trusted admission supplies each independent real owner"
    )]
    pub fn new(
        policy: Arc<PolicyStore>,
        authority: Arc<NamespaceAuthority>,
        namespace: NamespaceRead,
        principal: InvocationPrincipal,
        service: String,
        publication: ReleaseUseEligibility,
        state: PolicyCallBinding,
        intents: Option<PolicyCallBinding>,
        budget: ActivationBudget,
    ) -> Result<Self, PlatformError> {
        let scope = authority.ownership();
        if principal.tenant.as_ref() != Some(&scope.tenant)
            || principal.subject != scope.caller.owner_subject
            || namespace.record().tenant != scope.tenant
            || namespace.record().id.0 != scope.namespace
            || namespace.record().version != authority.version()
            || publication.publication().as_str().is_empty()
            || budget.profile() != latent_core::BudgetProfile::Phase4
            || authority.requires_audit()
        {
            return Err(denied());
        }
        for binding in std::iter::once(&state).chain(intents.as_ref()) {
            if binding.policies.is_empty()
                || binding.policies.len() > 8
                || binding.operations.is_empty()
                || binding.operations.len() > 16
                || binding.configuration_epoch == 0
            {
                return Err(denied());
            }
            for text in binding
                .policies
                .iter()
                .chain(binding.operations.iter())
                .chain([
                    &binding.binding,
                    &binding.profile,
                    &binding.configuration_digest,
                    &service,
                ])
            {
                latent_core::transaction_contract::identity(text).map_err(|_| denied())?;
            }
        }
        Ok(Self {
            policy,
            authority,
            namespace: Arc::new(namespace),
            principal,
            service,
            publication,
            state,
            intents,
            budget,
        })
    }

    pub(super) fn authorize(
        &self,
        operation: &str,
        input_bytes: usize,
        output_bytes: usize,
        action: impl FnOnce() -> Result<(), PlatformError>,
    ) -> Result<(), PlatformError> {
        let intent = operation == "stage";
        let binding = if intent {
            self.intents.as_ref().ok_or_else(denied)?
        } else {
            &self.state
        };
        let now = Instant::now();
        if self.budget.deadline().is_expired_at(now) || self.budget.descendant_is_cancelled() {
            return Err(denied());
        }
        // Current data permission also fences already-owned terminal buffers
        // after guest accounting freezes. This creates no execution allocation;
        // actual byte/call counters remain charged by the original host ledger.
        let remaining = self.budget.granted();
        let wall_time_millis = u64::try_from(
            self.budget
                .deadline()
                .remaining_at(now)
                .ok_or_else(denied)?
                .as_millis(),
        )
        .map_err(|_| denied())?
        .min(30_000);
        if wall_time_millis == 0 {
            return Err(denied());
        }
        let snapshot = self.policy.snapshot(
            &self.authority.ownership().tenant,
            &binding.policies,
            &binding.binding,
            now + std::time::Duration::from_millis(wall_time_millis),
        )?;
        let ownership = self.authority.ownership();
        let decision = snapshot.authorize(
            EvaluationInput {
                principal: &self.principal,
                service: &self.service,
                publication: self.publication.publication().as_str(),
                capability: if intent {
                    INTENT_CONTRACT
                } else {
                    STATE_CONTRACT
                },
                operation,
                resource: ResourceTarget::State {
                    namespace: &ownership.namespace,
                    incarnation: ownership.incarnation,
                    entity: ownership.entity.as_deref(),
                    recovery_kind: ownership.caller.kind,
                    recovery_scope: &ownership.caller.scope,
                    result_policy: &ownership.result_policy,
                },
            },
            &CallRestrictions {
                imported_operations: &binding.operations,
                deployment: &binding.deployment,
                provider_configuration: &binding.provider_configuration,
                provider_profile: &binding.profile,
                configuration_digest: &binding.configuration_digest,
                configuration_epoch: binding.configuration_epoch,
                remaining: CapabilityCeiling {
                    operations: 256,
                    input_bytes: remaining
                        .state_read_bytes
                        .max(remaining.state_write_bytes)
                        .min(2_097_152),
                    output_bytes: remaining.state_read_bytes.min(2_097_152),
                    wall_time_millis,
                },
                input_bytes: u64::try_from(input_bytes).map_err(|_| denied())?,
                output_bytes: u64::try_from(output_bytes).map_err(|_| denied())?,
            },
            &self.publication,
        )?;
        if decision.requires_audit() {
            // A descriptive flag cannot stand in for a durable audit receipt.
            // The audit-enabled runtime must install an actual reservation owner.
            return Err(denied());
        }
        self.authority
            .with_operation(&self.policy, &decision, &self.namespace, operation, action)
    }
}
pub(super) fn denied() -> PlatformError {
    PlatformError {
        code: PlatformErrorCode::PermissionDenied,
        message: "namespace-access-denied".into(),
        retryable: false,
        details: Vec::new(),
    }
}
