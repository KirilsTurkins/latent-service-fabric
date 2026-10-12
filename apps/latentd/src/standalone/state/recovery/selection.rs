//! Exact current transaction asset constraints retained for one native action.
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

pub(super) struct InstalledTransactionOperation {
    pub target: InvocationTarget,
    pub contract_digest: String,
    pub result_policy: String,
    pub policies: Vec<String>,
    pub native: NativeCapacityOwner,
    pub original: Arc<NativeReservation>,
    input: OperationSettings,
    pub(super) asset: NativeBuffer<SelectedTransactionAsset>,
}
impl InstalledTransactionOperation {
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
}

pub(super) fn profile(
    operation: &InstalledTransactionOperation,
    input: &OperationSettings,
    adapters: &[Arc<latent_http::deferred::HttpEffectAdapter>],
) -> Result<Option<RecoveryProfile>, PlatformError> {
    super::super::installations::http::recovery_profile(operation.asset.get(), input, adapters)
        .map(|profile| profile.map(|(scope, profile)| RecoveryProfile { scope, profile }))
}

pub(super) fn capture(
    repository: &Arc<DirectoryArtifactRepository>,
    settings: &StateSettings,
    input: OperationSettings,
    deployment: &DeploymentManifest,
    native: NativeCapacityOwner,
    original: Arc<NativeReservation>,
) -> Result<Arc<InstalledTransactionOperation>, PlatformError> {
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
    Ok(Arc::new(InstalledTransactionOperation {
        target,
        contract_digest,
        result_policy: input.result_policy.clone(),
        policies: input.policies.clone(),
        native,
        original,
        input,
        asset,
    }))
}
