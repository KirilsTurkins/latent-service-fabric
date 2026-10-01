use super::{
    runtime::{Inner, StateRuntime},
    InstalledTransactionOperation,
};
use latent_activation::ActivationEnvelope;
use latent_capabilities::namespace::{
    CallerScope, NamespaceAdmission, NamespaceAuthority, RecoverySelection, STATE_CONTRACT,
};
use latent_core::{ActivationBudget, PlatformError, StateNamespaceId};
use latent_node::transaction_runtime::{CommandTimeSource, PolicyCallBinding, StateAuthorization};
use latent_policy::capability::{
    CallRestrictions, CapabilityCeiling, EvaluationInput, GrantRestriction, OwnedPolicyDecision,
    ResourceTarget,
};
use latent_state::{
    embedded::StoreError,
    namespace::catalog::{NamespaceCatalog, NamespaceRead},
    store_io::StoreIoKind,
};
use std::{sync::Arc, time::Instant};

impl StateRuntime {
    pub(super) fn seal_original_result(
        &self,
        op: &InstalledTransactionOperation,
        envelope: &ActivationEnvelope,
        budget: &ActivationBudget,
        original: &mut latent_node::transaction_runtime::command_completion::OriginalCommandMetadata,
        decision: OwnedPolicyDecision,
    ) -> Result<Arc<StateAuthorization>, PlatformError> {
        let history = original.take_result_history();
        let namespace = original.take_namespace()?;
        let Some(history) = history else {
            return self.seal(op, envelope, budget, namespace, decision);
        };
        let lifecycle = self
            .0
            .namespaces
            .lifecycle()
            .pin(&namespace)
            .map_err(|_| super::unavailable())?;
        let authority = NamespaceAuthority::seal_result_retained(
            &self.0.policy,
            decision,
            &namespace,
            NamespaceAdmission {
                activation: envelope.activation_id.clone(),
                deadline: budget.deadline().monotonic().ok_or_else(super::denied)?,
                recovery: &RecoverySelection::OriginalCaller,
                state_schema: op.state_schema(),
            },
            lifecycle,
            history,
        )?;
        Ok(Arc::new(StateAuthorization::new(
            Arc::clone(&self.0.policy),
            Arc::new(authority),
            namespace,
            envelope.principal.clone(),
            op.target.service.0.clone(),
            op.publication.clone(),
            self.binding(op),
            None,
            budget.clone(),
        )?))
    }

    pub(super) fn binding(&self, installed: &InstalledTransactionOperation) -> PolicyCallBinding {
        binding(&self.0, installed)
    }
    pub(super) fn accepts(
        &self,
        installed: &InstalledTransactionOperation,
        envelope: &ActivationEnvelope,
        budget: &ActivationBudget,
    ) -> Result<(), PlatformError> {
        if !self
            .0
            .installed
            .iter()
            .any(|selected| std::ptr::eq(selected.as_ref(), installed))
        {
            return Err(super::denied());
        }
        let revision = envelope
            .resolved_revision
            .as_ref()
            .ok_or_else(super::denied)?;
        if installed.target != envelope.target
            || revision.target != envelope.target
            || installed.publication.release() != &revision.release
            || revision.publication.as_ref() != Some(installed.publication.publication())
            || envelope.principal.tenant.as_ref() != Some(&installed.target.tenant)
            || envelope.parent_activation_id.is_some()
            || envelope.retry_attempt != 0
            || envelope.input_media_type != "application/vnd.latent.wit-values.v1+json"
            || budget.profile() != latent_core::BudgetProfile::Phase4
            || budget.descendant_is_cancelled()
        {
            return Err(super::denied());
        }
        installed.publication.check_current()
    }
    pub(super) fn retain(
        &self,
        op: &InstalledTransactionOperation,
        envelope: &ActivationEnvelope,
        budget: &ActivationBudget,
        operation: &'static str,
    ) -> Result<OwnedPolicyDecision, PlatformError> {
        let caller = CallerScope::derive(&envelope.principal, &RecoverySelection::OriginalCaller)?;
        let binding = self.binding(op);
        let deadline = budget.deadline().monotonic().ok_or_else(super::denied)?;
        let wall = u64::try_from(
            deadline
                .saturating_duration_since(Instant::now())
                .as_millis(),
        )
        .map_err(|_| super::denied())?
        .min(30_000);
        if wall == 0 {
            return Err(super::denied());
        }
        let snapshot = self.0.policy.snapshot(
            &op.target.tenant,
            &binding.policies,
            &binding.binding,
            deadline,
        )?;
        let granted = budget.granted();
        let decision = snapshot.authorize(
            EvaluationInput {
                principal: &envelope.principal,
                service: &op.target.service.0,
                publication: op.publication.publication().as_str(),
                capability: STATE_CONTRACT,
                operation,
                resource: ResourceTarget::State {
                    namespace: op.namespace(),
                    incarnation: op.incarnation,
                    entity: op.entity.as_deref(),
                    recovery_kind: caller.kind,
                    recovery_scope: &caller.scope,
                    result_policy: &op.result_policy,
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
                    input_bytes: granted
                        .state_read_bytes
                        .max(granted.state_write_bytes)
                        .min(2_097_152),
                    output_bytes: granted.state_read_bytes.min(2_097_152),
                    wall_time_millis: wall,
                },
                input_bytes: 0,
                output_bytes: 0,
            },
            &op.publication,
        )?;
        self.0.policy.retain_decision(&decision)
    }
    pub(super) async fn namespaces(
        &self,
        op: &InstalledTransactionOperation,
        budget: &ActivationBudget,
        time: Arc<dyn CommandTimeSource>,
        kind: StoreIoKind,
    ) -> Result<(NamespaceRead, NamespaceRead), PlatformError> {
        let memory = Arc::new(
            budget
                .reserve_host_memory(65_536)
                .map_err(|_| super::capacity())?,
        );
        let tenant = op.target.tenant.clone();
        let namespace = StateNamespaceId(op.namespace().into());
        let incarnation = op.incarnation;
        let schema = op.state_schema().to_owned();
        let job = self
            .0
            .store
            .with_store(kind, 65_536, move |store| {
                let value = (|| {
                    let view = store.snapshot()?;
                    latent_state::recovery::require_namespace_ready(
                        &view,
                        &tenant,
                        &namespace,
                        incarnation,
                    )?;
                    let first = NamespaceCatalog::read_in(&view, &tenant, &namespace)
                        .map_err(|_| StoreError::Unavailable)?
                        .ok_or(StoreError::Unavailable)?;
                    if first.record().state_schema != schema {
                        return Err(StoreError::Unavailable);
                    }
                    let second = NamespaceCatalog::read_in(&view, &tenant, &namespace)
                        .map_err(|_| StoreError::Unavailable)?
                        .ok_or(StoreError::Unavailable)?;
                    Ok((first, second))
                })();
                Ok((value, time, memory))
            })
            .map_err(|_| super::unavailable())?;
        let (value, _time, _memory) = job
            .await
            .map_err(|_| super::unavailable())?
            .map_err(|_| super::unavailable())?;
        value.map_err(|_| super::unavailable())
    }
    pub(super) fn seal(
        &self,
        op: &InstalledTransactionOperation,
        envelope: &ActivationEnvelope,
        budget: &ActivationBudget,
        namespace: NamespaceRead,
        decision: OwnedPolicyDecision,
    ) -> Result<Arc<StateAuthorization>, PlatformError> {
        let lifecycle = self
            .0
            .namespaces
            .lifecycle()
            .pin(&namespace)
            .map_err(|_| super::unavailable())?;
        let authority = NamespaceAuthority::seal_retained(
            &self.0.policy,
            decision,
            &namespace,
            NamespaceAdmission {
                activation: envelope.activation_id.clone(),
                deadline: budget.deadline().monotonic().ok_or_else(super::denied)?,
                recovery: &RecoverySelection::OriginalCaller,
                state_schema: op.state_schema(),
            },
            lifecycle,
        )?;
        Ok(Arc::new(StateAuthorization::new(
            Arc::clone(&self.0.policy),
            Arc::new(authority),
            namespace,
            envelope.principal.clone(),
            op.target.service.0.clone(),
            op.publication.clone(),
            self.binding(op),
            self.0.intents.iter().find_map(|intent| intent.binding(op)),
            budget.clone(),
        )?))
    }
}
pub(super) fn binding(inner: &Inner, op: &InstalledTransactionOperation) -> PolicyCallBinding {
    let operations = [
        "acquire-command",
        "acquire-query",
        "info",
        "query-info",
        "get",
        "get-query",
        "scan",
        "scan-query",
        "describe-page",
        "page-next",
        "put",
        "delete",
        "commit",
        "read-result",
    ]
    .into_iter()
    .map(String::from)
    .collect();
    PolicyCallBinding {
        policies: op.policies.clone(),
        binding: op.binding().into(),
        profile: inner.profile.clone(),
        configuration_digest: inner.configuration_digest.clone(),
        configuration_epoch: inner.epoch,
        operations,
        deployment: GrantRestriction {
            operations: vec![],
            resources: None,
            ceiling: None,
        },
        provider_configuration: GrantRestriction {
            operations: vec![],
            resources: None,
            ceiling: None,
        },
    }
}
pub(super) fn management_binding(
    inner: &Inner,
    op: &InstalledTransactionOperation,
) -> PolicyCallBinding {
    let mut binding = binding(inner, op);
    binding.operations = [
        "namespace-create",
        "namespace-inspect",
        "namespace-list",
        "namespace-quiesce",
        "namespace-retire",
        "namespace-destroy",
        "namespace-recreate",
        "read-result",
        "inspect-effect",
        "cancel-command",
    ]
    .into_iter()
    .map(String::from)
    .collect();
    binding
}
