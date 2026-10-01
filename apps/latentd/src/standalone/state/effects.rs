//! Real installed adapter and independent staging/dispatch policy purposes.
mod policy;
use super::InstalledTransactionOperation;
use crate::{config::NodeSettings, standalone::providers::ProviderRuntime};
use latent_core::{BoxFuture, PlatformError};
use latent_effects::{
    authority::{
        AuthorityError, DispatchGrant, DispatchProfile, DurableEffectAuthority,
        EffectAuthorityOwner, EffectRule,
    },
    dispatch::AttemptIdentity,
    payload::PayloadRecord,
    runtime::{AdapterOutcome, DeferredEffectAdapter, EffectTimeSource},
};
use latent_http::effects::{PutOnceContract, QualifiedHttpEffectAdapter};
use latent_node::transaction_runtime::{IntentPolicyBinding, PolicyCallBinding};
use latent_policy::capability::{GrantRestriction, PolicyStore};
use policy::DispatchPolicy;
use std::{sync::Arc, time::Instant};

pub(super) struct InstalledIntent {
    operation: Arc<InstalledTransactionOperation>,
    digest: String,
    profile: String,
    epoch: u64,
}
pub(super) struct Installation {
    pub adapters: Vec<Arc<dyn DeferredEffectAdapter>>,
    pub intents: Vec<InstalledIntent>,
}
struct AuthorizedHttp {
    inner: QualifiedHttpEffectAdapter,
    policies: Vec<DispatchPolicy>,
}

pub(in crate::standalone) fn observe(
    settings: &NodeSettings,
    installed: &[Arc<InstalledTransactionOperation>],
    providers: Option<&ProviderRuntime>,
    policy: &Arc<PolicyStore>,
    time: &Arc<dyn EffectTimeSource>,
) -> Result<Vec<super::NativeDeferredEffectHostInspection>, PlatformError> {
    let mut observations = Vec::new();
    for operation in installed
        .iter()
        .filter(|operation| operation.deferred_http.is_some())
    {
        let (_, _, dispatch) = prepare_operation(
            settings,
            operation,
            providers.ok_or_else(super::denied)?,
            policy,
            time,
        )?;
        observations.push(dispatch.observation()?);
    }
    Ok(observations)
}

pub(super) fn install(
    settings: &NodeSettings,
    installed: &[Arc<InstalledTransactionOperation>],
    providers: Option<&ProviderRuntime>,
    policy: &Arc<PolicyStore>,
    authority: &EffectAuthorityOwner,
    time: &Arc<dyn EffectTimeSource>,
) -> Result<Installation, PlatformError> {
    let mut adapters: Vec<AuthorizedHttp> = Vec::new();
    let mut intents = Vec::new();
    let deadline = Instant::now() + std::time::Duration::from_secs(30);
    for operation in installed {
        let Some(_) = &operation.deferred_http else {
            continue;
        };
        let (adapter, epoch, dispatch) = prepare_operation(
            settings,
            operation,
            providers.ok_or_else(super::denied)?,
            policy,
            time,
        )?;
        if adapters
            .iter()
            .flat_map(|adapter| &adapter.policies)
            .any(|other| other.scope == dispatch.scope)
        {
            // One actual scope has one unambiguous policy/credential installation.
            return Err(super::denied());
        }
        intents.push(activate_operation(
            operation, &adapter, epoch, &dispatch, policy, authority, deadline,
        )?);
        if let Some(existing) = adapters
            .iter_mut()
            .find(|existing| existing.inner.profile() == adapter.profile())
        {
            existing.policies.push(dispatch);
        } else {
            if adapters.len() >= 32 {
                return Err(super::capacity());
            }
            adapters.push(AuthorizedHttp {
                inner: adapter,
                policies: vec![dispatch],
            });
        }
    }
    Ok(Installation {
        adapters: adapters
            .into_iter()
            .map(|adapter| Arc::new(adapter) as Arc<dyn DeferredEffectAdapter>)
            .collect(),
        intents,
    })
}

fn prepare_operation(
    settings: &NodeSettings,
    operation: &Arc<InstalledTransactionOperation>,
    providers: &ProviderRuntime,
    policy: &Arc<PolicyStore>,
    time: &Arc<dyn EffectTimeSource>,
) -> Result<(QualifiedHttpEffectAdapter, u64, DispatchPolicy), PlatformError> {
    let (selected, requirements) = operation.deferred_http.as_ref().ok_or_else(super::denied)?;
    let http = settings
        .providers
        .as_ref()
        .and_then(|providers| providers.http.as_ref())
        .ok_or_else(super::denied)?;
    let origin = http
        .configuration
        .destinations
        .first()
        .ok_or_else(super::denied)?
        .origin
        .clone();
    let contract = PutOnceContract {
        tenant: operation.target.tenant.clone(),
        provider_id: selected.provider_id.clone(),
        origin,
        provider_incarnation: selected.provider_incarnation.clone(),
        retention_horizon_millis: requirements.retention_horizon_millis,
        maximum_body_bytes: requirements.maximum_body_bytes,
        retry_delay_millis: requirements.retry_delay_millis,
    };
    let (adapter, epoch) = ProviderRuntime::qualified_http(
        providers,
        contract,
        &selected.credential_reference,
        Arc::clone(time),
    )?;
    let dispatch = DispatchPolicy::new(Arc::clone(operation), Arc::clone(policy), &adapter, epoch)?;
    Ok((adapter, epoch, dispatch))
}
fn activate_operation(
    operation: &Arc<InstalledTransactionOperation>,
    adapter: &QualifiedHttpEffectAdapter,
    epoch: u64,
    dispatch: &DispatchPolicy,
    policy: &PolicyStore,
    authority: &EffectAuthorityOwner,
    deadline: Instant,
) -> Result<InstalledIntent, PlatformError> {
    let (selected, requirements) = operation.deferred_http.as_ref().ok_or_else(super::denied)?;
    dispatch.with_current(
        deadline,
        requirements.maximum_body_bytes as u64,
        |generation| {
            authority
                .publish(EffectRule {
                    scope: dispatch.scope.clone(),
                    profile: adapter.profile().clone(),
                    policy_revision: generation,
                    credential_epoch: epoch,
                    protected_credential_reference: selected.credential_reference.clone(),
                    ceiling: requirements.ceiling,
                    enabled: true,
                })
                .map_err(|_| super::denied())
        },
    )?;
    let staging = policy.snapshot(
        &operation.target.tenant,
        &selected.staging_policies,
        &selected.staging_binding,
        deadline,
    )?;
    staging.check_provider_configuration(
        latent_capabilities::namespace::INTENT_CONTRACT,
        &adapter.profile().adapter,
        adapter.configuration_digest(),
        epoch,
    )?;
    Ok(InstalledIntent {
        operation: Arc::clone(operation),
        digest: adapter.configuration_digest().into(),
        profile: adapter.profile().adapter.clone(),
        epoch,
    })
}

impl InstalledIntent {
    pub(super) fn binding(
        &self,
        operation: &InstalledTransactionOperation,
    ) -> Option<IntentPolicyBinding> {
        if !std::ptr::eq(self.operation.as_ref(), operation) {
            return None;
        }
        let (selected, requirements) = operation.deferred_http.as_ref()?;
        Some(IntentPolicyBinding {
            call: PolicyCallBinding {
                policies: selected.staging_policies.clone(),
                binding: selected.staging_binding.clone(),
                profile: self.profile.clone(),
                configuration_digest: self.digest.clone(),
                configuration_epoch: self.epoch,
                operations: vec!["stage".into()],
                deployment: unrestricted(),
                provider_configuration: unrestricted(),
            },
            binding: requirements.logical_binding.clone(),
            operation: requirements.operation.clone(),
            maximum_intents: requirements.count,
            payload_digest: requirements.payload_digest.clone(),
        })
    }
}
pub(super) fn unrestricted() -> GrantRestriction {
    GrantRestriction {
        operations: vec![],
        resources: None,
        ceiling: None,
    }
}

impl DeferredEffectAdapter for AuthorizedHttp {
    fn profile(&self) -> &DispatchProfile {
        self.inner.profile()
    }
    fn with_current_dispatch(
        &self,
        authority: &DurableEffectAuthority,
        deadline: Instant,
        accept: &mut dyn FnMut() -> Result<BoxFuture<'static, AdapterOutcome>, AuthorityError>,
    ) -> Result<BoxFuture<'static, AdapterOutcome>, AuthorityError> {
        let selected = self
            .policies
            .iter()
            .find(|policy| &policy.scope == authority.scope())
            .ok_or(AuthorityError::PolicyBlocked)?;
        if authority.profile() != self.profile()
            || authority.payload_bytes() > selected.ceiling.maximum_payload_bytes
        {
            return Err(AuthorityError::PolicyBlocked);
        }
        let mut accepted = None;
        selected
            .with_current(deadline, authority.payload_bytes(), |_| {
                accepted = Some(accept());
                Ok(())
            })
            .map_err(|_| AuthorityError::PolicyBlocked)?;
        accepted.ok_or(AuthorityError::PolicyBlocked)?
    }
    fn accept(
        &self,
        grant: DispatchGrant,
        payload: PayloadRecord,
        attempt: AttemptIdentity,
    ) -> Result<BoxFuture<'static, AdapterOutcome>, AuthorityError> {
        self.inner.accept(grant, payload, attempt)
    }
}
