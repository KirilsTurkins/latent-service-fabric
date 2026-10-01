//! Native dispatch authenticates the actual retained source service separately
//! from the original caller's staging authority. No claims or config flag grant it.
use super::{super::InstalledTransactionOperation, unrestricted};
use latent_capabilities::namespace::{CallerScope, RecoverySelection, INTENT_CONTRACT};
use latent_core::{InvocationPrincipal, Metadata, PlatformError, PrincipalKind};
use latent_effects::{
    authority::{DispatchCeiling, EffectScope},
    runtime::DeferredEffectAdapter,
};
use latent_http::effects::QualifiedHttpEffectAdapter;
use latent_policy::capability::{
    CallRestrictions, CapabilityCeiling, EvaluationInput, PolicyStore, ResourceTarget,
};
use std::{sync::Arc, time::Instant};

pub(super) struct DispatchPolicy {
    pub scope: EffectScope,
    pub ceiling: DispatchCeiling,
    operation: Arc<InstalledTransactionOperation>,
    policy: Arc<PolicyStore>,
    principal: InvocationPrincipal,
    caller: CallerScope,
    profile: String,
    digest: String,
    epoch: u64,
}
impl DispatchPolicy {
    pub fn new(
        operation: Arc<InstalledTransactionOperation>,
        policy: Arc<PolicyStore>,
        adapter: &QualifiedHttpEffectAdapter,
        epoch: u64,
    ) -> Result<Self, PlatformError> {
        let (_, requirements) = operation
            .deferred_http
            .as_ref()
            .ok_or_else(super::super::denied)?;
        let principal = InvocationPrincipal {
            subject: InvocationPrincipal::local_service_subject(
                &operation.target.tenant,
                &operation.target.service,
            ),
            kind: PrincipalKind::Service,
            tenant: Some(operation.target.tenant.clone()),
            service: Some(operation.target.service.clone()),
            claims: Metadata::new(),
        };
        let caller = CallerScope::derive(&principal, &RecoverySelection::ServiceIntegration)?;
        let scope = EffectScope {
            tenant: operation.target.tenant.0.clone(),
            namespace: operation.namespace().into(),
            incarnation: operation.incarnation,
            publication: operation.publication.publication().as_str().into(),
            binding: requirements.logical_binding.clone(),
            operation: requirements.operation.clone(),
        };
        let ceiling = requirements.ceiling;
        Ok(Self {
            scope,
            ceiling,
            operation,
            policy,
            principal,
            caller,
            profile: adapter.profile().adapter.clone(),
            digest: adapter.configuration_digest().into(),
            epoch,
        })
    }
    pub fn with_current<T>(
        &self,
        deadline: Instant,
        input_bytes: u64,
        action: impl FnOnce(u64) -> Result<T, PlatformError>,
    ) -> Result<T, PlatformError> {
        let (selected, _) = self
            .operation
            .deferred_http
            .as_ref()
            .ok_or_else(super::super::denied)?;
        let now = Instant::now();
        let remaining = deadline.saturating_duration_since(now);
        // Round up: a millisecond policy ceiling must cover the entire original
        // remaining instant interval, including its fractional final millisecond.
        let required =
            remaining.as_millis() + u128::from(!remaining.subsec_nanos().is_multiple_of(1_000_000));
        let wall = u64::try_from(required)
            .map_err(|_| super::super::denied())?
            .min(self.ceiling.attempt_timeout_millis);
        if wall == 0 {
            return Err(super::super::denied());
        }
        let snapshot = self.policy.snapshot(
            &self.operation.target.tenant,
            &selected.dispatch_policies,
            &selected.dispatch_binding,
            deadline,
        )?;
        let decision = snapshot.authorize(
            EvaluationInput {
                principal: &self.principal,
                service: &self.operation.target.service.0,
                publication: self.scope.publication.as_str(),
                capability: INTENT_CONTRACT,
                operation: "dispatch",
                resource: ResourceTarget::State {
                    namespace: &self.scope.namespace,
                    incarnation: self.scope.incarnation,
                    entity: self.operation.entity.as_deref(),
                    recovery_kind: self.caller.kind,
                    recovery_scope: &self.caller.scope,
                    result_policy: &self.operation.result_policy,
                },
            },
            &CallRestrictions {
                imported_operations: &["dispatch".into()],
                deployment: &unrestricted(),
                provider_configuration: &unrestricted(),
                provider_profile: &self.profile,
                configuration_digest: &self.digest,
                configuration_epoch: self.epoch,
                remaining: CapabilityCeiling {
                    operations: 1,
                    input_bytes: self.ceiling.maximum_payload_bytes,
                    output_bytes: self.ceiling.maximum_response_bytes,
                    wall_time_millis: wall,
                },
                input_bytes,
                output_bytes: self.ceiling.maximum_response_bytes,
            },
            &self.operation.publication,
        )?;
        if decision.requires_audit() || decision.ceiling().wall_time_millis < wall {
            return Err(super::super::denied());
        }
        let generation = snapshot.generation();
        let mut action = Some(action);
        let mut result = None;
        self.policy.with_current(&decision, &mut |_, _| {
            if Instant::now() >= deadline {
                return Err(super::super::denied());
            }
            result = Some(action.take().ok_or_else(super::super::denied)?(generation)?);
            Ok(())
        })?;
        result.ok_or_else(super::super::denied)
    }
}
