use std::{sync::Arc, time::Instant};

use latent_activation::ActivationEnvelope;
use latent_capabilities::namespace::{
    CallerScope, NamespaceAdmission, NamespaceAuthority, STATE_CONTRACT,
};
use latent_core::{ActivationBudget, BoxFuture, BudgetProfile, PlatformError};
use latent_policy::capability::{
    CallRestrictions, CapabilityCeiling, EvaluationInput, PolicyStore, ResourceTarget,
};
use latent_state::{
    embedded::StoreError,
    namespace::{catalog::NamespaceCatalog, NamespaceError},
    protected_store::ProtectedStoreOwner,
    session::{StateMode, StateScope},
};

use super::super::{
    authorization::denied, CommandTimeSource, PolicyCallBinding, StateAuthorization,
    StateTransactionHost,
};
use super::{completion::QueryCompletion, QuerySelection};
use crate::activation_manager::{
    TransactionActivationAdmission, TransactionAdmission, TransactionExecution,
};

/// These are the existing node owners, not a second database or executor.
pub struct QueryOwners {
    pub store: Arc<ProtectedStoreOwner>,
    pub policy: Arc<PolicyStore>,
    pub namespaces: Arc<NamespaceCatalog>,
    pub time: Arc<dyn CommandTimeSource>,
}

pub struct QueryAdmission {
    owners: QueryOwners,
    selection: QuerySelection,
    binding: PolicyCallBinding,
}

impl QueryAdmission {
    pub fn new(
        owners: QueryOwners,
        selection: QuerySelection,
        binding: PolicyCallBinding,
    ) -> Result<Self, PlatformError> {
        if binding.binding != selection.binding
            || binding.policies.is_empty()
            || binding.policies.len() > 8
            || binding.operations.len() > 16
            || !binding
                .operations
                .iter()
                .any(|name| name == "acquire-query")
        {
            return Err(denied());
        }
        Ok(Self {
            owners,
            selection,
            binding,
        })
    }

    async fn open(
        &self,
        envelope: &ActivationEnvelope,
        budget: &ActivationBudget,
    ) -> Result<TransactionExecution, PlatformError> {
        self.selection.accepts(envelope)?;
        let granted = budget.granted();
        if budget.profile() != BudgetProfile::Phase4
            || granted.state_write_bytes != 0
            || granted.effect_count != 0
            || granted.child_calls != 0
            || granted.outbound_requests != 0
            || budget.descendant_is_cancelled()
        {
            return Err(denied());
        }
        let caller = CallerScope::derive(&envelope.principal, &self.selection.recovery)?;
        let now = Instant::now();
        let deadline = budget.deadline().monotonic().ok_or_else(denied)?;
        let wall = u64::try_from(deadline.saturating_duration_since(now).as_millis())
            .map_err(|_| denied())?
            .min(30_000);
        if wall == 0 {
            return Err(denied());
        }
        let snapshot = self.owners.policy.snapshot(
            &self.selection.target.tenant,
            &self.binding.policies,
            &self.binding.binding,
            deadline,
        )?;
        let decision = snapshot.authorize(
            EvaluationInput {
                principal: &envelope.principal,
                service: &self.selection.target.service.0,
                publication: self.selection.publication.publication().as_str(),
                capability: STATE_CONTRACT,
                operation: "acquire-query",
                resource: ResourceTarget::State {
                    namespace: &self.selection.namespace.0,
                    incarnation: self.selection.incarnation,
                    entity: self.selection.entity.as_deref(),
                    recovery_kind: caller.kind,
                    recovery_scope: &caller.scope,
                    result_policy: &self.selection.result_policy,
                },
            },
            &CallRestrictions {
                imported_operations: &self.binding.operations,
                deployment: &self.binding.deployment,
                provider_configuration: &self.binding.provider_configuration,
                provider_profile: &self.binding.profile,
                configuration_digest: &self.binding.configuration_digest,
                configuration_epoch: self.binding.configuration_epoch,
                remaining: CapabilityCeiling {
                    operations: 256,
                    input_bytes: granted.state_read_bytes.min(2_097_152),
                    output_bytes: granted.state_read_bytes.min(2_097_152),
                    wall_time_millis: wall,
                },
                input_bytes: 0,
                output_bytes: 0,
            },
            &self.selection.publication,
        )?;
        let retained = self.owners.policy.retain_decision(&decision)?;
        drop(decision);
        drop(snapshot);
        // Authorize before reading native metadata, then retain the same original
        // authority while the fixed worker reads one bounded current namespace.
        let memory = Arc::new(budget.reserve_host_memory(65_536).map_err(|_| denied())?);
        let worker_memory = Arc::clone(&memory);
        let tenant = self.selection.target.tenant.clone();
        let id = self.selection.namespace.clone();
        let view = self
            .owners
            .store
            .open_view()
            .map_err(store_error)?
            .await
            .map_err(|_| denied())?
            .map_err(store_error)?;
        let job = self
            .owners
            .store
            .with_view(view, 65_536, move |view| {
                let read =
                    NamespaceCatalog::read_in(view, &tenant, &id).map_err(namespace_error)?;
                // The actual worker/result owner retains the original activation
                // memory charge if the transport detaches while native I/O lives.
                Ok((read, worker_memory))
            })
            .map_err(store_error)?;
        let (view, namespace) = job.await.map_err(|_| denied())?;
        view.retire().await;
        let (namespace, result_memory) = namespace.map_err(store_error)?;
        let namespace = namespace.ok_or_else(denied)?;
        if self
            .selection
            .minimum_generation
            .is_some_and(|minimum| namespace.record().version.generation < minimum)
        {
            return Err(super::failure(
                latent_executor::transaction::StateFailure::Conflict,
            ));
        }
        let lifecycle = self
            .owners
            .namespaces
            .lifecycle()
            .pin(&namespace)
            .map_err(|_| denied())?;
        let authority = Arc::new(NamespaceAuthority::seal_retained(
            &self.owners.policy,
            retained,
            &namespace,
            NamespaceAdmission {
                activation: envelope.activation_id.clone(),
                deadline,
                recovery: &self.selection.recovery,
                state_schema: &self.selection.schema,
            },
            lifecycle,
        )?);
        let binding = copy_binding(&self.binding)?;
        let auth = Arc::new(StateAuthorization::new(
            Arc::clone(&self.owners.policy),
            authority,
            namespace,
            envelope.principal.clone(),
            self.selection.target.service.0.clone(),
            self.selection.publication.clone(),
            binding,
            None,
            budget.clone(),
        )?);
        let host = StateTransactionHost::open(
            Arc::clone(&self.owners.store),
            auth,
            envelope.activation_id.clone(),
            StateScope {
                tenant: self.selection.target.tenant.clone(),
                namespace: self.selection.namespace.clone(),
                incarnation: self.selection.incarnation,
                state_schema: self.selection.schema.clone(),
                entity: self.selection.entity.clone(),
                mode: StateMode::Query,
            },
            None,
            None,
            Arc::clone(&self.owners.time),
            Vec::new(),
        )
        .await
        .map_err(super::failure)?;
        drop(result_memory);
        drop(memory);
        let completion = Arc::new(QueryCompletion::new(Arc::clone(&host)));
        TransactionExecution::query(host, completion)
    }
}

impl TransactionActivationAdmission for QueryAdmission {
    fn admit<'a>(
        &'a self,
        envelope: &'a ActivationEnvelope,
        budget: &'a ActivationBudget,
    ) -> BoxFuture<'a, Result<TransactionAdmission, PlatformError>> {
        Box::pin(async move {
            self.open(envelope, budget)
                .await
                .map(TransactionAdmission::Execute)
        })
    }
}

fn copy_binding(source: &PolicyCallBinding) -> Result<PolicyCallBinding, PlatformError> {
    use latent_policy::capability::GrantRestriction;
    Ok(PolicyCallBinding {
        policies: source.policies.clone(),
        binding: source.binding.clone(),
        profile: source.profile.clone(),
        configuration_digest: source.configuration_digest.clone(),
        configuration_epoch: source.configuration_epoch,
        operations: source.operations.clone(),
        deployment: GrantRestriction::parse(
            &source.deployment.canonical_bytes(STATE_CONTRACT)?,
            STATE_CONTRACT,
        )?,
        provider_configuration: GrantRestriction::parse(
            &source
                .provider_configuration
                .canonical_bytes(STATE_CONTRACT)?,
            STATE_CONTRACT,
        )?,
    })
}

fn namespace_error(error: NamespaceError) -> StoreError {
    match error {
        NamespaceError::Corrupt => StoreError::Corrupt,
        NamespaceError::UnsupportedFormat => StoreError::UnsupportedFormat,
        _ => StoreError::Unavailable,
    }
}
fn store_error(error: latent_state::protected_store::ProtectedStoreError) -> PlatformError {
    super::failure(super::super::io::protected_error(error))
}
