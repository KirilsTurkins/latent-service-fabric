//! Current authority and descriptive signed decoder bytes remain distinct.
use crate::config::state::{OperationSettings, StateSettings};
use latent_artifacts::{
    DirectoryArtifactRepository, ReleaseUseEligibility, SelectedTransactionAsset,
};
use latent_core::{
    native_capacity::{NativeBuffer, NativeCapacityOwner, NativeReservation},
    PlatformError,
};
use latent_manifest::DeploymentManifest;
use latent_routing::InvocationTarget;
use std::sync::Arc;

pub(super) struct RecoveryProfile {
    pub scope: latent_effects::authority::EffectScope,
    pub profile: latent_effects::authority::DispatchProfile,
}

pub(super) struct RecoverySource {
    pub target: InvocationTarget,
    pub contract_digest: String,
    pub result_policy: String,
    pub policies: Vec<String>,
    pub native: NativeCapacityOwner,
    pub original: Arc<NativeReservation>,
    input: OperationSettings,
    current_authority: bool,
    pub(super) asset: NativeBuffer<SelectedTransactionAsset>,
}
impl RecoverySource {
    pub fn target(&self) -> &InvocationTarget {
        &self.target
    }
    pub fn publication(&self) -> &ReleaseUseEligibility {
        self.asset.get().publication()
    }
    pub fn namespace(&self) -> &str {
        &self.asset.get().declaration().namespace
    }
    pub fn incarnation(&self) -> u64 {
        self.input.incarnation
    }
    pub fn binding(&self) -> &str {
        &self.input.binding
    }
    pub fn current(&self) -> Result<(), PlatformError> {
        self.asset.get().with_current(&mut |_| Ok(()))
    }
    pub fn supplies_current_authority(&self) -> bool {
        self.current_authority
    }
}

pub(super) fn profiles(
    operation: &RecoverySource,
    adapters: &[Arc<latent_http::deferred::HttpEffectAdapter>],
    event_adapters: &[Arc<latent_nats::deferred::JetStreamEffectAdapter>],
) -> Result<impl Iterator<Item = RecoveryProfile>, PlatformError> {
    let http = super::super::installations::http::recovery_profile(
        operation.asset.get(),
        &operation.input,
        adapters,
    )?;
    let event = super::super::installations::event::recovery_profile(
        operation.asset.get(),
        &operation.input,
        event_adapters,
    )?;
    Ok([http, event]
        .into_iter()
        .flatten()
        .map(|(scope, profile)| RecoveryProfile { scope, profile }))
}

pub(super) fn current_profiles(
    source: &RecoverySource,
    settings: &StateSettings,
    deployment: &DeploymentManifest,
    adapters: &[Arc<latent_http::deferred::HttpEffectAdapter>],
    event_adapters: &[Arc<latent_nats::deferred::JetStreamEffectAdapter>],
) -> Result<Vec<RecoveryProfile>, PlatformError> {
    let current = &source.input;
    let asset = source.asset.get();
    let mut profiles: Vec<RecoveryProfile> = Vec::new();
    // A publication's query can precede its command in the node configuration.
    // Every configured peer still uses the original signed installation and namespace.
    for peer in settings.operations.iter().filter(|peer| {
        peer.tenant == current.tenant
            && peer.publication == current.publication
            && peer.deployment == current.deployment
            && peer.binding == current.binding
            && peer.incarnation == current.incarnation
            && (peer.deferred_http.is_some() || peer.deferred_event.is_some())
    }) {
        super::super::installations::policy::check_asset(asset, peer, deployment)?;
        super::super::installations::policy::state_binding(settings, peer, deployment)?;
        let http = super::super::installations::http::recovery_profile(asset, peer, adapters)?;
        let event =
            super::super::installations::event::recovery_profile(asset, peer, event_adapters)?;
        for (scope, profile) in [http, event].into_iter().flatten() {
            if let Some(prior) = profiles.iter().find(|prior| prior.scope == scope) {
                if prior.profile != profile {
                    return Err(super::denied());
                }
            } else {
                if profiles.len() == 2 {
                    return Err(super::capacity());
                }
                profiles.push(RecoveryProfile { scope, profile });
            }
        }
    }
    Ok(profiles)
}

pub(super) fn capture_current(
    repository: &Arc<DirectoryArtifactRepository>,
    settings: &StateSettings,
    input: OperationSettings,
    deployment: &DeploymentManifest,
    native: NativeCapacityOwner,
    original: Arc<NativeReservation>,
) -> Result<Arc<RecoverySource>, PlatformError> {
    let asset = repository.capture_selected_transaction_asset_profile(
        &input.tenant,
        &input.component,
        &input.publication,
        &native,
        Arc::clone(&original),
        latent_artifacts::TransactionAssetProfile::Compact,
    )?;
    super::super::installations::policy::check_asset(asset.get(), &input, deployment)?;
    super::super::installations::policy::state_binding(settings, &input, deployment)?;
    retain(input, asset, native, original, true)
}

/// An eligible signed source can describe old bytes without claiming its old
/// deployment is currently installed. The requested current source still owns
/// every policy decision and native write fence.
pub(super) fn capture_decoder(
    repository: &Arc<DirectoryArtifactRepository>,
    current: &RecoverySource,
    selector: &super::request::DecoderSource,
) -> Result<Arc<RecoverySource>, PlatformError> {
    if !current.supplies_current_authority() {
        return Err(super::denied());
    }
    let mut input = current.input.clone();
    input.component = latent_core::ReleaseDigest(selector.component_digest.clone());
    input.publication = selector.publication.parse().map_err(|_| super::denied())?;
    let asset = repository.capture_selected_transaction_asset_profile(
        &input.tenant,
        &input.component,
        &input.publication,
        &current.native,
        Arc::clone(&current.original),
        latent_artifacts::TransactionAssetProfile::Compact,
    )?;
    check_decoder_asset(asset.get(), current, &input)?;
    input.companion_digest = asset.get().asset_digest().to_string();
    match (
        &mut input.deferred_http,
        asset.get().deferred_http_requirements(),
    ) {
        (Some(config), Some((digest, _))) => config.requirements_digest = digest.to_string(),
        (None, None) => {}
        _ => return Err(super::denied()),
    }
    match (
        &mut input.deferred_event,
        asset.get().deferred_event_requirements(),
    ) {
        (Some(config), Some((digest, _))) => config.requirements_digest = digest.to_string(),
        (None, None) => {}
        _ => return Err(super::denied()),
    }
    retain(
        input,
        asset,
        current.native.clone(),
        Arc::clone(&current.original),
        false,
    )
}

fn check_decoder_asset(
    asset: &SelectedTransactionAsset,
    current: &RecoverySource,
    input: &OperationSettings,
) -> Result<(), PlatformError> {
    let declaration = asset.declaration();
    declaration
        .check_links(
            &asset.metadata().manifest().metadata.name,
            &current.input.deployment,
            current.binding(),
        )
        .map_err(|_| super::denied())?;
    let export = declaration
        .operations
        .iter()
        .find(|export| export.operation == current.input.function)
        .ok_or_else(super::denied)?;
    if asset.metadata().verified_digest() != &input.component
        || asset.publication().publication() != &input.publication
        || asset.publication().tenant() != Some(&current.target.tenant)
        || declaration.capsule != current.target.service.0
        || declaration.namespace != current.namespace()
        || export.input_format != "lsf-wit-values-v1"
        || export.result_format != "lsf-wit-values-v1"
        || !asset
            .metadata()
            .manifest()
            .exports
            .iter()
            .any(|export| export.contract.0 == current.input.contract)
        || !asset.metadata().contracts().iter().any(|contract| {
            contract.id.0 == current.input.contract
                && contract.interfaces.iter().any(|interface| {
                    interface
                        .functions
                        .iter()
                        .any(|function| function.id.0 == current.input.function)
                })
        })
    {
        return Err(super::denied());
    }
    Ok(())
}

fn retain(
    input: OperationSettings,
    asset: NativeBuffer<SelectedTransactionAsset>,
    native: NativeCapacityOwner,
    original: Arc<NativeReservation>,
    current_authority: bool,
) -> Result<Arc<RecoverySource>, PlatformError> {
    let contract_digest = asset
        .get()
        .metadata()
        .contracts()
        .iter()
        .find(|contract| contract.id.0 == input.contract)
        .ok_or_else(super::denied)?
        .digest
        .clone();
    let target = InvocationTarget {
        tenant: input.tenant.clone(),
        service: latent_core::ServiceId(asset.get().declaration().capsule.clone()),
        contract: latent_core::ContractId(input.contract.clone()),
        function: latent_core::FunctionId(input.function.clone()),
        route: input.route.clone(),
    };
    Ok(Arc::new(RecoverySource {
        target,
        contract_digest,
        result_policy: input.result_policy.clone(),
        policies: input.policies.clone(),
        native,
        original,
        input,
        current_authority,
        asset,
    }))
}

#[cfg(all(test, target_os = "linux", target_arch = "x86_64"))]
mod fence_tests;
