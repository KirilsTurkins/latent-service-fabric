//! Native host observations for policy provisioning. Descriptions grant nothing.
use super::{clock::ProtectedCommandClock, effects, load_operations};
use crate::{config::NodeSettings, standalone::providers::ProviderRuntime};
use latent_artifacts::DirectoryArtifactRepository;
use latent_core::{ActivationClock, PlatformError};
use latent_effects::runtime::EffectTimeSource;
use latent_policy::capability::{PolicyStore, RecoveryScopeKind};
use latent_state::protected_store::ProtectedStoreConfig;
use serde::Serialize;
use std::sync::Arc;

/// Derived from checked configuration and the actual native adapter constructor.
/// It is neither an effect rule nor a staged/dispatch grant.
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct NativeDeferredEffectHostInspection {
    pub tenant: String,
    pub service: String,
    pub publication: String,
    pub namespace: String,
    pub incarnation: u64,
    pub logical_binding: String,
    pub operation: String,
    pub staging_binding: String,
    pub dispatch_binding: String,
    pub provider_profile: String,
    pub configuration_digest: String,
    pub configuration_epoch: u64,
    pub dispatch_subject: String,
    pub dispatch_recovery_kind: RecoveryScopeKind,
    pub dispatch_recovery_scope: String,
    pub result_policy: String,
}

/// A pre-start observation of the selected state configuration and real signed
/// operation adapters. No state store, namespace or dispatcher is activated.
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct NativeTransactionHostInspection {
    pub schema_version: &'static str,
    pub configured_providers: Vec<crate::standalone::ProviderDescriptor>,
    pub state_provider_profile: String,
    pub state_configuration_digest: String,
    pub state_configuration_epoch: u64,
    pub deferred_http: Vec<NativeDeferredEffectHostInspection>,
}

pub(in crate::standalone) async fn inspect_host_configuration(
    settings: &NodeSettings,
    artifacts: &Arc<DirectoryArtifactRepository>,
    providers: Option<&ProviderRuntime>,
    policy: &Arc<PolicyStore>,
    clock: Arc<dyn ActivationClock>,
) -> Result<NativeTransactionHostInspection, PlatformError> {
    let configuration = settings.state.as_ref().ok_or_else(super::denied)?;
    let installed = load_operations(artifacts, configuration.operations.clone()).await?;
    let time: Arc<dyn EffectTimeSource> = ProtectedCommandClock::load(settings, clock)?;
    let mut store = ProtectedStoreConfig::bounded_linux(settings.data_directory.join("state"));
    store.create_if_missing = configuration.create_if_missing;
    let (profile, digest) = store.inspection_profile().map_err(|_| super::denied())?;
    Ok(NativeTransactionHostInspection {
        schema_version: "latent.transaction-host-inspection.v1",
        configured_providers: providers
            .map_or_else(Vec::new, |providers| providers.descriptors().to_vec()),
        state_provider_profile: profile.into(),
        state_configuration_digest: format!("sha256:{:x}", latent_core::digest::HexDigest(digest)),
        state_configuration_epoch: configuration.configuration_epoch,
        deferred_http: effects::observe(settings, &installed, providers, policy, &time)?,
    })
}
