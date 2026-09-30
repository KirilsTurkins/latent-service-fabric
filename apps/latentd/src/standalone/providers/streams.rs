use crate::config::StreamInstallation;
use latent_capabilities::broker::pools::ProviderPools;
use latent_core::PlatformError;
use latent_streams::StreamLifecycle;
use std::sync::Arc;

#[cfg(feature = "development-outbound-streams")]
pub(super) fn install(
    pools: &Arc<ProviderPools>,
    config: &StreamInstallation,
) -> Result<StreamLifecycle, PlatformError> {
    StreamLifecycle::install_for_qualification(
        pools.clone(),
        &config.identity.id,
        config.identity.epoch,
        config.configuration.clone(),
    )
    .map_err(|_| super::unavailable())
}
#[cfg(not(feature = "development-outbound-streams"))]
pub(super) fn install(
    _pools: &Arc<ProviderPools>,
    _config: &StreamInstallation,
) -> Result<StreamLifecycle, PlatformError> {
    Err(super::unavailable())
}
