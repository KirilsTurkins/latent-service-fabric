//! Installed native owners are captured before opening exclusive recovery.
use super::{
    authority::{Authority, NativeProfile},
    catalog::Catalog,
    codecs::Codecs,
    execution::{self, NativeRecoveryReport},
    request::NativeRecoveryRequest,
};
use crate::{config::NodeSettings, standalone::providers::ProviderRuntime};
use latent_artifacts::DirectoryArtifactRepository;
use latent_core::{ActivationClock, InvocationPrincipal, PlatformError, PrincipalKind};
use latent_effects::runtime::EffectTimeSource;
use latent_policy::capability::PolicyStore;
use latent_state::protected_store::ProtectedStoreConfig;
use std::sync::Arc;

/// Only the normal native catalog startup can provide these real owners.
pub(in crate::standalone) struct RecoveryOwners<'a> {
    pub artifacts: &'a Arc<DirectoryArtifactRepository>,
    pub providers: Option<&'a ProviderRuntime>,
    pub policy: &'a Arc<PolicyStore>,
    pub clock: Arc<dyn ActivationClock>,
}

pub(in crate::standalone) async fn recover(
    settings: &NodeSettings,
    principal: &InvocationPrincipal,
    request: NativeRecoveryRequest,
    owners: RecoveryOwners<'_>,
) -> Result<NativeRecoveryReport, PlatformError> {
    if !settings.credentials_from_protected_file || principal.kind != PrincipalKind::Administrator {
        return Err(super::super::denied());
    }
    let configuration = settings.state.as_ref().ok_or_else(super::super::denied)?;
    let installed =
        super::super::load_operations(owners.artifacts, configuration.operations.clone()).await?;
    let clock = super::super::clock::ProtectedCommandClock::load(settings, owners.clock)?;
    let time: Arc<dyn EffectTimeSource> = clock.clone();
    let effects = super::super::effects::recovery_profiles(
        settings,
        &installed,
        owners.providers,
        owners.policy,
        &time,
    )?;
    let catalog =
        Catalog::capture(owners.artifacts, &installed, effects, &request.publication).await?;
    // Derive exactly the ordinary configured profile before narrowing this
    // opening to an existing offline owner. Creation flags grant no authority.
    let mut store =
        ProtectedStoreConfig::bounded_linux(configuration.protected_root(&settings.data_directory));
    store.create_if_missing = configuration.create_if_missing;
    let (profile, digest) = store
        .inspection_profile()
        .map_err(|_| super::super::denied())?;
    let digest = format!("sha256:{:x}", latent_core::digest::HexDigest(digest));
    let authority = Authority::retain(
        Arc::clone(owners.policy),
        catalog.primary(),
        principal,
        &request.request,
        clock,
        &NativeProfile {
            profile,
            digest: &digest,
            epoch: configuration.configuration_epoch,
        },
    )?;
    let codecs = Codecs::new(catalog, authority, request.request)
        .map_err(|_| super::super::unavailable())?;
    store.create_if_missing = false;
    Ok(execution::execute(store, codecs, settings.shutdown_grace()).await)
}
