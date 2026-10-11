use latent_artifacts::{LifecycleScope, PublicationRef, SelectedTransactionAsset};
use latent_core::{PlatformError, ServiceId, StateNamespaceId};
use latent_manifest::{DeploymentManifest, TransactionBinding};
use latent_node::PolicyCallBinding;
use latent_policy::capability::GrantRestriction;
use latent_state::namespace::NamespaceQuota;
use latent_wire::phase4::StateManagementBinding;

use crate::config::state::{OperationSettings, StateSettings};

pub(super) fn state_binding(
    settings: &StateSettings,
    operation: &OperationSettings,
    deployment: &DeploymentManifest,
) -> Result<PolicyCallBinding, PlatformError> {
    let grants: Vec<_> = deployment
        .grants
        .iter()
        .filter(|grant| grant.capability.0 == latent_capabilities::namespace::STATE_CONTRACT)
        .collect();
    if grants.len() != 1
        || operation.policies != [grants[0].policy.0.clone()]
        || !grants[0].constraints.is_empty()
    {
        return Err(super::super::unavailable());
    }
    let (profile, digest) = settings
        .store
        .inspection_profile()
        .map_err(|_| super::super::unavailable())?;
    Ok(PolicyCallBinding {
        policies: operation.policies.clone(),
        binding: operation.binding.clone(),
        profile: profile.into(),
        configuration_digest: format!("sha256:{:x}", latent_core::digest::HexDigest(digest)),
        configuration_epoch: settings.configuration_epoch,
        operations: [
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
        .collect(),
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
    })
}

pub(super) fn maximum_quota(
    settings: &StateSettings,
    operation: &OperationSettings,
) -> Result<NamespaceQuota, PlatformError> {
    let limits = &settings
        .tenant_quotas
        .iter()
        .find(|quota| quota.tenant == operation.tenant.0)
        .ok_or_else(super::super::unavailable)?
        .limits;
    let quota = NamespaceQuota {
        state_keys: limits.state_keys,
        state_bytes: limits.state_bytes,
        result_rows: limits.result_rows,
        result_bytes: limits.result_bytes,
        effect_rows: limits.effect_rows,
        effect_bytes: limits.effect_bytes,
        payload_bytes: limits.payload_bytes,
        recovery_bytes: limits.recovery_bytes,
    };
    quota.validate().map_err(|_| super::super::unavailable())?;
    Ok(quota)
}

pub(super) fn check_asset(
    asset: &SelectedTransactionAsset,
    operation: &OperationSettings,
    deployment: &DeploymentManifest,
) -> Result<(), PlatformError> {
    let declaration = asset.declaration();
    declaration
        .check_links(
            &asset.metadata().manifest().metadata.name,
            &operation.deployment,
            &operation.binding,
        )
        .map_err(|_| super::super::unavailable())?;
    let export = declaration
        .operations
        .iter()
        .find(|export| export.operation == operation.function)
        .ok_or_else(super::super::unavailable)?;
    if asset.asset_digest().to_string() != operation.companion_digest
        || asset.metadata().verified_digest() != &operation.component
        || asset.publication().publication() != &operation.publication
        || asset.publication().tenant() != Some(&operation.tenant)
        || deployment.id.0 != operation.deployment
        || deployment.release != operation.component
        || deployment.publication.as_ref() != Some(&operation.publication)
        || deployment.metadata.tenant.as_ref() != Some(&operation.tenant)
        || deployment.service.0 != declaration.capsule
        || export.input_format != "lsf-wit-values-v1"
        || export.result_format != "lsf-wit-values-v1"
        || !asset
            .metadata()
            .manifest()
            .exports
            .iter()
            .any(|export| export.contract.0 == operation.contract)
        || !asset.metadata().contracts().iter().any(|contract| {
            contract.id.0 == operation.contract
                && contract.interfaces.iter().any(|interface| {
                    interface
                        .functions
                        .iter()
                        .any(|function| function.id.0 == operation.function)
                })
        })
    {
        return Err(super::super::unavailable());
    }
    Ok(())
}

pub(super) fn management_binding(
    operation: &OperationSettings,
    declaration: &TransactionBinding,
    maximum_quota: NamespaceQuota,
    mut state: PolicyCallBinding,
) -> StateManagementBinding {
    // Administrative and historical data reads have their own current policy;
    // they do not inherit execution-route lifetime or guest-operation narrowing.
    state.deployment = GrantRestriction {
        operations: Vec::new(),
        resources: None,
        ceiling: None,
    };
    state.operations = [
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
    StateManagementBinding {
        publication: PublicationRef {
            id: operation.publication.clone(),
            scope: LifecycleScope::Tenant(operation.tenant.clone()),
        },
        component: operation.component.clone(),
        service: ServiceId(declaration.capsule.clone()),
        namespace: StateNamespaceId(declaration.namespace.clone()),
        incarnation: operation.incarnation,
        state_schema: declaration.state_schema.clone(),
        result_policy: operation.result_policy.clone(),
        maximum_quota,
        state,
    }
}
