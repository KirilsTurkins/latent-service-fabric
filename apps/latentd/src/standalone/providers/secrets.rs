use std::{sync::Arc, time::Instant};

use latent_capabilities::broker::pools::ProviderPools;
use latent_core::{PlatformError, TenantId};
use latent_secrets::{
    LocalSecretProvider, LocalSecretStore, SecretLimits, SecretPurpose, SecretSource, SecretSpec,
    SystemSecretClock,
};

use crate::config::SecretInstallation;

pub(super) async fn install(
    pools: &Arc<ProviderPools>,
    config: &SecretInstallation,
    deadline: Instant,
) -> Result<(LocalSecretProvider, LocalSecretStore), PlatformError> {
    let store = LocalSecretStore::open_before(
        pools.clone(),
        config.directory.clone(),
        SecretLimits {
            maximum_references: 8,
            maximum_value_bytes: 4096,
            maximum_generation_bytes: 32768,
            maximum_generations: 2,
            maximum_environment_bytes: 1,
        },
        Vec::new(),
        Arc::new(SystemSecretClock),
        deadline,
    )
    .map_err(|_| super::unavailable())?
    .await
    .map_err(|_| super::unavailable())?;
    let specs = config
        .references
        .iter()
        .map(|entry| SecretSpec {
            tenant: TenantId(config.identity.tenant.clone()),
            reference: entry.reference.clone(),
            source: SecretSource::File {
                name: entry.file.clone(),
            },
            purpose: SecretPurpose::GuestValue,
            media_type: "application/octet-stream".into(),
            version: config.identity.epoch.to_string(),
            expires_at_unix_millis: entry.expires_at_unix_millis,
        })
        .collect();
    store
        .reload_before(0, specs, deadline)
        .map_err(|_| super::unavailable())?
        .await
        .map_err(|_| super::unavailable())?;
    let provider =
        LocalSecretProvider::install(&config.identity.id, config.identity.epoch, 0, &store)
            .map_err(|_| super::unavailable())?;
    Ok((provider, store))
}
