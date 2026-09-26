use std::{sync::Arc, time::Instant};

use latent_capabilities::broker::{pools::ProviderPools, secrets::TlsCredentialScope};
use latent_core::{PlatformError, TenantId};
use latent_nats::{NatsCredential, NatsPublisher};
use latent_secrets::{
    LocalSecretStore, SecretLimits, SecretPurpose, SecretSource, SecretSpec, SystemSecretClock,
};

use crate::config::providers::EventInstallation;

pub(super) async fn install(
    pools: &Arc<ProviderPools>,
    config: &EventInstallation,
    deadline: Instant,
) -> Result<(NatsPublisher, LocalSecretStore), PlatformError> {
    let store = LocalSecretStore::open_before(
        pools.clone(),
        config.credential_directory.clone(),
        SecretLimits::default(),
        Vec::new(),
        Arc::new(SystemSecretClock),
        deadline,
    )
    .map_err(|_| super::unavailable())?
    .await
    .map_err(|_| super::unavailable())?;
    let tenant = TenantId(config.identity.tenant.clone());
    let destination = config.configuration.endpoint.credential_destination();
    store
        .reload_before(
            0,
            vec![SecretSpec {
                tenant: tenant.clone(),
                reference: config.credential_reference.clone(),
                source: SecretSource::File {
                    name: config.credential_file.clone(),
                },
                purpose: SecretPurpose::TlsProviderCredential {
                    provider_id: config.identity.id.clone(),
                    destination: destination.clone(),
                },
                media_type: "text/plain".into(),
                version: config.identity.epoch.to_string(),
                expires_at_unix_millis: None,
            }],
            deadline,
        )
        .map_err(|_| super::unavailable())?
        .await
        .map_err(|_| super::unavailable())?;
    let secret = store
        .bind_tls_credential(
            TlsCredentialScope {
                tenant,
                provider_id: config.identity.id.clone(),
                destination,
            },
            config.credential_reference.clone(),
        )
        .map_err(|_| super::unavailable())?;
    let provider = NatsPublisher::install(
        pools.clone(),
        &config.identity.id,
        config.identity.epoch,
        0,
        config.configuration.clone(),
        vec![NatsCredential {
            username: None,
            secret,
        }],
    )
    .map_err(|_| super::unavailable())?;
    Ok((provider, store))
}
