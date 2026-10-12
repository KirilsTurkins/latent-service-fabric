//! Signed requirements constrain the existing HTTP provider and effect authority.
mod dispatch;
use crate::config::state::OperationSettings;
pub(in crate::standalone::state) use dispatch::DispatchRegistry;
use latent_artifacts::SelectedTransactionAsset;
use latent_capabilities::{broker::http::HTTP_CAPABILITY, namespace::INTENT_CONTRACT};
use latent_core::{InvocationPrincipal, Metadata, PlatformError, PrincipalKind, ServiceId};
use latent_effects::{
    authority::{DispatchCeiling, EffectAuthorityOwner, EffectScope},
    runtime::DeferredEffectAdapter,
};
use latent_http::deferred::HttpEffectAdapter;
use latent_manifest::{DeploymentManifest, TransactionOperationMode};
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

/// Retained decoder association only. This reads the same signed requirements
/// and current configured adapter; it installs no authority or dispatch rule.
pub(in crate::standalone::state) fn recovery_profile(
    asset: &SelectedTransactionAsset,
    operation: &OperationSettings,
    adapters: &[Arc<HttpEffectAdapter>],
) -> Result<Option<(EffectScope, latent_effects::authority::DispatchProfile)>, PlatformError> {
    let Some(config) = &operation.deferred_http else {
        return Ok(None);
    };
    let (digest, bytes) = asset.deferred_http_requirements().ok_or_else(denied)?;
    if digest.to_string() != config.requirements_digest || bytes.len() > 8192 {
        return Err(denied());
    }
    let requirement: Requirements = serde_json::from_slice(bytes).map_err(|_| denied())?;
    let declaration = asset.declaration();
    if requirement.format_version != 1
        || requirement.protocol != "lsf-atomic-idempotent-http-v1"
        || requirement.capsule != declaration.capsule
        || requirement.deployment != declaration.deployment
        || requirement.state_binding != declaration.binding
        || requirement.namespace != declaration.namespace
        || requirement.companion_digest != asset.asset_digest().to_string()
        || requirement.operation != "http"
        || requirement.adapter != "qualified-http-effect-v1"
        || requirement.payload_format != "http-body-value-v1"
    {
        return Err(denied());
    }
    let mut matching = adapters.iter().filter(|adapter| {
        adapter.profile().provider == config.provider_id
            && adapter.endpoint().endpoint_incarnation == config.provider_incarnation
            && adapter.profile().idempotency_profile == requirement.idempotency_profile
    });
    let adapter = matching.next().ok_or_else(denied)?;
    if matching.next().is_some() {
        return Err(denied());
    }
    let scope = EffectScope {
        tenant: operation.tenant.0.clone(),
        namespace: declaration.namespace.clone(),
        incarnation: operation.incarnation,
        publication: operation.publication.as_str().into(),
        binding: requirement.binding,
        operation: "http".into(),
    };
    let rule = adapter
        .rule(
            scope,
            1,
            adapter.provider_reference().configuration_epoch(),
            requirement.ceiling,
        )
        .map_err(|_| denied())?;
    if rule.protected_credential_reference != config.credential_reference {
        return Err(denied());
    }
    Ok(Some((rule.scope, rule.profile)))
}

#[allow(
    clippy::too_many_arguments,
    reason = "Each original installed owner remains explicit at the startup seal"
)]
#[expect(
    clippy::too_many_lines,
    reason = "Signed capture, policy generation, selected namespace and original native acceptance remain one visible seal"
)]
pub(super) fn install(
    asset: &SelectedTransactionAsset,
    operation: &OperationSettings,
    deployment: &DeploymentManifest,
    adapters: &[Arc<HttpEffectAdapter>],
    policy: &Arc<PolicyStore>,
    authority: &EffectAuthorityOwner,
    selected: Option<&latent_control_store::InstalledTransactionSelection>,
    original: &Arc<latent_core::native_capacity::NativeReservation>,
    deadline: std::time::Instant,
    registry: &DispatchRegistry,
    metadata: Arc<latent_core::native_capacity::NativeBufferPermit>,
) -> Result<Option<Arc<PolicyCallBinding>>, PlatformError> {
    let Some(config) = &operation.deferred_http else {
        return Ok(None);
    };
    let (digest, bytes) = asset.deferred_http_requirements().ok_or_else(denied)?;
    if digest.to_string() != config.requirements_digest || bytes.len() > 8192 {
        return Err(denied());
    }
    let requirements: Requirements = serde_json::from_slice(bytes).map_err(|_| denied())?;
    let declaration = asset.declaration();
    let export = declaration
        .operations
        .iter()
        .find(|e| e.operation == operation.function)
        .ok_or_else(denied)?;
    if requirements.format_version != 1
        || requirements.protocol != "lsf-atomic-idempotent-http-v1"
        || requirements.capsule != declaration.capsule
        || requirements.deployment != declaration.deployment
        || requirements.state_binding != declaration.binding
        || requirements.namespace != declaration.namespace
        || requirements.companion_digest != asset.asset_digest().to_string()
        || requirements.operation != "http"
        || requirements.adapter != "qualified-http-effect-v1"
        || requirements.payload_format != "http-body-value-v1"
        || export.mode != TransactionOperationMode::StrictCommand
    {
        return Err(denied());
    }
    latent_core::transaction_contract::identity(&requirements.binding).map_err(|_| denied())?;
    let mut matches = adapters.iter().filter(|a| {
        a.profile().provider == config.provider_id
            && a.endpoint().endpoint_incarnation == config.provider_incarnation
            && a.profile().idempotency_profile == requirements.idempotency_profile
    });
    let adapter = matches.next().ok_or_else(denied)?;
    if matches.next().is_some() {
        return Err(denied());
    }
    let reference = adapter.provider_reference();
    let generation = policy.capture_control_generation(deadline)?;
    let grants: Vec<_> = deployment
        .grants
        .iter()
        .filter(|g| g.capability.0 == INTENT_CONTRACT)
        .collect();
    if grants.len() != 1
        || config.staging_policies != [grants[0].policy.0.clone()]
        || !grants[0].constraints.is_empty()
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
                .strip_prefix("qualified-http-v1:")
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
    let scope = EffectScope {
        tenant: operation.tenant.0.clone(),
        namespace: declaration.namespace.clone(),
        incarnation: operation.incarnation,
        publication: operation.publication.as_str().into(),
        binding: requirements.binding,
        operation: "http".into(),
    };
    let rule = adapter
        .rule(
            scope,
            generation.persisted_generation(),
            reference.configuration_epoch(),
            requirements.ceiling,
        )
        .map_err(|_| denied())?;
    if rule.protected_credential_reference != config.credential_reference {
        return Err(denied());
    }
    let dispatch = dispatch_policy(
        Arc::clone(policy),
        asset,
        operation,
        deployment,
        adapter,
        rule.clone(),
        metadata,
    )?;
    dispatch.authorize(
        "POST",
        &adapter.endpoint().operation_path,
        requirements.ceiling.maximum_payload_bytes,
        deadline,
    )?;
    dispatch.authorize("GET", &adapter.endpoint().operation_path, 0, deadline)?;
    // An absent namespace is management-only. It cannot authorize staging or
    // dispatch until an actual current incarnation is captured on restart.
    if let Some(selected) = selected {
        let fresh = registry.register(dispatch)?;
        let mut rule = Some(rule);
        policy.with_control_generation(&generation, deadline, &mut |_| {
            selected.with_current(asset.publication(), &mut || {
                original
                    .with_live(|| {
                        if fresh {
                            authority
                                .publish(rule.take().ok_or_else(denied)?)
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

fn dispatch_policy(
    policy: Arc<PolicyStore>,
    asset: &SelectedTransactionAsset,
    operation: &OperationSettings,
    deployment: &DeploymentManifest,
    adapter: &HttpEffectAdapter,
    rule: latent_effects::authority::EffectRule,
    metadata: Arc<latent_core::native_capacity::NativeBufferPermit>,
) -> Result<dispatch::DispatchPolicy, PlatformError> {
    let config = operation.deferred_http.as_ref().ok_or_else(denied)?;
    let grants: Vec<_> = deployment
        .grants
        .iter()
        .filter(|g| g.capability.0 == HTTP_CAPABILITY)
        .collect();
    if grants.len() != 1
        || config.dispatch_policies != [grants[0].policy.0.clone()]
        || !grants[0].constraints.is_empty()
    {
        return Err(denied());
    }
    let restriction = GrantRestriction {
        operations: grants[0].operations.clone(),
        resources: None,
        ceiling: None,
    };
    let reference = adapter.provider_reference();
    let service = ServiceId(declaration_service(asset).into());
    let principal = InvocationPrincipal {
        subject: InvocationPrincipal::local_service_subject(&operation.tenant, &service),
        kind: PrincipalKind::Service,
        tenant: Some(operation.tenant.clone()),
        service: Some(service),
        claims: Metadata::new(),
    };
    Ok(dispatch::DispatchPolicy {
        rule,
        policy,
        publication: asset.publication().clone(),
        principal,
        service: declaration_service(asset).into(),
        policies: config.dispatch_policies.clone(),
        binding: config.dispatch_binding.clone(),
        restriction,
        reference: reference.clone(),
        origin: adapter.endpoint().origin.clone(),
        _metadata: metadata,
    })
}

fn declaration_service(asset: &SelectedTransactionAsset) -> &str {
    &asset.metadata().manifest().metadata.name
}
fn denied() -> PlatformError {
    crate::standalone::error(
        latent_core::PlatformErrorCode::PermissionDenied,
        "signed-http-effect-installation-refused",
    )
}
