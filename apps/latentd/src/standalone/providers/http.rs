use std::{sync::Arc, time::Instant};

use latent_capabilities::broker::{pools::ProviderPools, secrets::CredentialScope};
use latent_core::{PlatformError, TenantId};
use latent_http::{HttpCredentialReference, HttpProvider};
use latent_secrets::{
    LocalSecretStore, SecretLimits, SecretPurpose, SecretSource, SecretSpec, SystemSecretClock,
};

use crate::config::HttpInstallation;

pub(super) async fn install(
    pools: &Arc<ProviderPools>,
    config: &HttpInstallation,
    deadline: Instant,
) -> Result<(HttpProvider, Option<LocalSecretStore>), PlatformError> {
    let mut references = Vec::with_capacity(config.credentials.len());
    let secrets = if let Some(directory) = &config.credential_directory {
        let store = LocalSecretStore::open_before(
            pools.clone(),
            directory.clone(),
            SecretLimits::default(),
            Vec::new(),
            Arc::new(SystemSecretClock),
            deadline,
        )
        .map_err(|_| super::unavailable())?
        .await
        .map_err(|_| super::unavailable())?;
        let specs = config
            .credentials
            .iter()
            .map(|credential| SecretSpec {
                tenant: TenantId(config.identity.tenant.clone()),
                reference: credential.reference.clone(),
                source: SecretSource::File {
                    name: credential.file.clone(),
                },
                purpose: SecretPurpose::ProviderCredential {
                    provider_id: config.identity.id.clone(),
                    origin: config.configuration.destinations[credential.destination]
                        .origin
                        .clone(),
                },
                media_type: "text/plain".into(),
                version: config.identity.epoch.to_string(),
                expires_at_unix_millis: None,
            })
            .collect();
        store
            .reload_before(0, specs, deadline)
            .map_err(|_| super::unavailable())?
            .await
            .map_err(|_| super::unavailable())?;
        for credential in &config.credentials {
            let binding = store
                .bind_credential(
                    CredentialScope {
                        tenant: TenantId(config.identity.tenant.clone()),
                        provider_id: config.identity.id.clone(),
                        origin: config.configuration.destinations[credential.destination]
                            .origin
                            .clone(),
                    },
                    credential.reference.clone(),
                )
                .map_err(|_| super::unavailable())?;
            references.push(HttpCredentialReference {
                destination: credential.destination,
                name: credential.header.clone(),
                binding,
            });
        }
        Some(store)
    } else {
        None
    };
    let provider = HttpProvider::install_with_secret_references(
        pools.clone(),
        &config.identity.id,
        config.identity.epoch,
        0,
        config.configuration.clone(),
        references,
    )
    .map_err(|_| super::unavailable())?;
    Ok((provider, secrets))
}
