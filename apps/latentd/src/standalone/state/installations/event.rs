//! Signed event requirements constrain the original provider and current policy.
mod dispatch;
pub(in crate::standalone::state) use dispatch::DispatchRegistry;

use crate::config::state::OperationSettings;
use latent_artifacts::SelectedTransactionAsset;
use latent_capabilities::{broker::events::EVENTS_CAPABILITY, namespace::INTENT_CONTRACT};
use latent_core::{InvocationPrincipal, Metadata, PlatformError, PrincipalKind, ServiceId};
use latent_effects::{
    authority::{DispatchCeiling, EffectAuthorityOwner, EffectScope},
    runtime::DeferredEffectAdapter,
};
use latent_manifest::{DeploymentManifest, TransactionOperationMode};
use latent_nats::deferred::{JetStreamEffectAdapter, NATS_DEFERRED_PROFILE};
use latent_node::{transaction_runtime::TransactionInstallationSelection, PolicyCallBinding};
use latent_policy::capability::{GrantRestriction, PolicyStore};
use serde::Deserialize;
use std::sync::Arc;

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Requirements {
    format_version: u32,
    protocol: String,
    capsule: String,
    deployment: String,
    state_binding: String,
    namespace: String,
    companion_digest: String,
    binding: String,
    operation: String,
    adapter: String,
    payload_format: String,
    idempotency_profile: String,
    ceiling: DispatchCeiling,
}

fn select<'a>(
    asset: &SelectedTransactionAsset,
    operation: &OperationSettings,
    adapters: &'a [Arc<JetStreamEffectAdapter>],
) -> Result<Option<(Requirements, &'a Arc<JetStreamEffectAdapter>)>, PlatformError> {
    let Some(config) = &operation.deferred_event else {
        return Ok(None);
    };
    let (digest, bytes) = asset.deferred_event_requirements().ok_or_else(denied)?;
    if digest.to_string() != config.requirements_digest || bytes.len() > 8192 {
        return Err(denied());
    }
    let requirements: Requirements = serde_json::from_slice(bytes).map_err(|_| denied())?;
    let declaration = asset.declaration();
    let export = declaration
        .operations
        .iter()
        .find(|export| export.operation == operation.function)
        .ok_or_else(denied)?;
    if requirements.format_version != 1
        || requirements.protocol != "lsf-jetstream-event-v1"
        || requirements.capsule != declaration.capsule
        || requirements.deployment != declaration.deployment
        || requirements.state_binding != declaration.binding
        || requirements.namespace != declaration.namespace
        || requirements.companion_digest != asset.asset_digest().to_string()
        || requirements.operation != "event"
        || requirements.adapter != NATS_DEFERRED_PROFILE
        || requirements.payload_format != "nats-event-value-v1"
        || export.mode != TransactionOperationMode::StrictCommand
    {
        return Err(denied());
    }
    latent_core::transaction_contract::identity(&requirements.binding).map_err(|_| denied())?;
    let mut matching = adapters.iter().filter(|adapter| {
        let reference = adapter.provider_reference();
        adapter.profile().provider == config.provider_id
            && reference.capability() == EVENTS_CAPABILITY
            && reference.configuration_digest().strip_prefix("sha256:")
                == Some(config.provider_incarnation.as_str())
            && adapter.profile().idempotency_profile == requirements.idempotency_profile
    });
    let adapter = matching.next().ok_or_else(denied)?;
    if matching.next().is_some() {
        return Err(denied());
    }
    Ok(Some((requirements, adapter)))
}

fn rule(
    asset: &SelectedTransactionAsset,
    operation: &OperationSettings,
    requirements: &Requirements,
    adapter: &JetStreamEffectAdapter,
    revision: u64,
) -> Result<latent_effects::authority::EffectRule, PlatformError> {
    let config = operation.deferred_event.as_ref().ok_or_else(denied)?;
    let scope = EffectScope {
        tenant: operation.tenant.0.clone(),
        namespace: asset.declaration().namespace.clone(),
        incarnation: operation.incarnation,
        publication: operation.publication.as_str().into(),
        binding: requirements.binding.clone(),
        operation: "event".into(),
    };
    let result = adapter
        .rule(
            scope,
            revision,
            adapter.provider_reference().configuration_epoch(),
            requirements.ceiling,
        )
        .map_err(|_| denied())?;
    if result.protected_credential_reference != config.credential_reference {
        return Err(denied());
    }
    Ok(result)
}

/// Descriptive retained association; it installs no policy or dispatch grant.
pub(in crate::standalone::state) fn recovery_profile(
    asset: &SelectedTransactionAsset,
    operation: &OperationSettings,
    adapters: &[Arc<JetStreamEffectAdapter>],
) -> Result<Option<(EffectScope, latent_effects::authority::DispatchProfile)>, PlatformError> {
    let Some((requirements, adapter)) = select(asset, operation, adapters)? else {
        return Ok(None);
    };
    let rule = rule(asset, operation, &requirements, adapter, 1)?;
    Ok(Some((rule.scope, rule.profile)))
}

#[allow(
    clippy::too_many_arguments,
    reason = "Keep the original signed, policy, provider and native owners explicit"
)]
#[expect(
    clippy::too_many_lines,
    reason = "Keep signed capture, current policy and original namespace acceptance in one visible seal"
)]
pub(super) fn install(
    asset: &SelectedTransactionAsset,
    operation: &OperationSettings,
    deployment: &DeploymentManifest,
    adapters: &[Arc<JetStreamEffectAdapter>],
    policy: &Arc<PolicyStore>,
    authority: &EffectAuthorityOwner,
    selected: Option<&latent_control_store::InstalledTransactionSelection>,
    original: &Arc<latent_core::native_capacity::NativeReservation>,
    deadline: std::time::Instant,
    registry: &DispatchRegistry,
    metadata: Arc<latent_core::native_capacity::NativeBufferPermit>,
) -> Result<Option<Arc<PolicyCallBinding>>, PlatformError> {
    let Some((requirements, adapter)) = select(asset, operation, adapters)? else {
        return Ok(None);
    };
    let config = operation.deferred_event.as_ref().ok_or_else(denied)?;
    let reference = adapter.provider_reference();
    let generation = policy.capture_control_generation(deadline)?;
    let grants: Vec<_> = deployment
        .grants
        .iter()
        .filter(|grant| grant.capability.0 == INTENT_CONTRACT)
        .collect();
    if grants.len() != 1
        || config.staging_policies != [grants[0].policy.0.clone()]
        || !grants[0].constraints.is_empty()
        || deployment
            .grants
            .iter()
            .any(|grant| grant.capability.0 == EVENTS_CAPABILITY)
        || !asset
            .metadata()
            .manifest()
            .imports
            .iter()
            .any(|import| import.contract.0 == INTENT_CONTRACT && !import.optional)
        || asset
            .metadata()
            .manifest()
            .imports
            .iter()
            .any(|import| import.contract.0 == EVENTS_CAPABILITY)
    {
        return Err(denied());
    }
    let binding = Arc::new(PolicyCallBinding {
        policies: config.staging_policies.clone(),
        binding: config.staging_binding.clone(),
        profile: adapter.profile().adapter.clone(),
        configuration_digest: format!(
            "sha256:{}",
            adapter
                .profile()
                .idempotency_profile
                .strip_prefix("js-window-v1:")
                .ok_or_else(denied)?
        ),
        configuration_epoch: reference.configuration_epoch(),
        operations: vec!["stage".into()],
        deployment: GrantRestriction {
            operations: grants[0].operations.clone(),
            resources: None,
            ceiling: None,
        },
        provider_configuration: GrantRestriction {
            operations: Vec::new(),
            resources: None,
            ceiling: None,
        },
    });
    let staging = policy.snapshot(
        &operation.tenant,
        &binding.policies,
        &binding.binding,
        deadline,
    )?;
    staging.check_provider_configuration(
        INTENT_CONTRACT,
        &binding.profile,
        &binding.configuration_digest,
        binding.configuration_epoch,
    )?;
    binding.deployment.validate(INTENT_CONTRACT)?;
    let rule = rule(
        asset,
        operation,
        &requirements,
        adapter,
        generation.persisted_generation(),
    )?;
    let service = ServiceId(asset.metadata().manifest().metadata.name.clone());
    let principal = InvocationPrincipal {
        subject: InvocationPrincipal::local_service_subject(&operation.tenant, &service),
        kind: PrincipalKind::Service,
        tenant: Some(operation.tenant.clone()),
        service: Some(service.clone()),
        claims: Metadata::new(),
    };
    let caller_scope = latent_capabilities::namespace::CallerScope::derive(
        &principal,
        &latent_capabilities::namespace::RecoverySelection::ServiceIntegration,
    )?;
    let dispatch = dispatch::DispatchPolicy {
        rule: rule.clone(),
        policy: Arc::clone(policy),
        publication: asset.publication().clone(),
        principal,
        caller_scope,
        service: service.0,
        policies: config.dispatch_policies.clone(),
        binding: config.dispatch_binding.clone(),
        restriction: GrantRestriction {
            operations: vec!["publish".into()],
            resources: None,
            ceiling: None,
        },
        reference,
        _metadata: metadata,
    };
    dispatch.authorize(
        &adapter.profile().destination,
        requirements.ceiling.maximum_payload_bytes,
        deadline,
    )?;
    if let Some(selected) = selected {
        let fresh = registry.register(dispatch)?;
        let mut pending = Some(rule);
        policy.with_control_generation(&generation, deadline, &mut |_| {
            selected.with_current(asset.publication(), &mut || {
                original
                    .with_live(|| {
                        if fresh {
                            authority
                                .publish(pending.take().ok_or_else(denied)?)
                                .map_err(|_| denied())
                        } else {
                            Ok(())
                        }
                    })
                    .map_err(|_| denied())?
            })
        })?;
    }
    Ok(Some(binding))
}

fn denied() -> PlatformError {
    crate::standalone::error(
        latent_core::PlatformErrorCode::PermissionDenied,
        "signed-event-effect-installation-refused",
    )
}
