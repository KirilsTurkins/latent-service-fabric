use std::{path::Path, sync::Arc, time::Instant};

use latent_capabilities::broker::{pools::ProviderPools, secrets::CredentialScope};
use latent_core::{PlatformError, TenantId};
use latent_http::{HttpCredentialReference, HttpProvider, HttpProviderConfig};
use latent_secrets::{
    LocalSecretStore, SecretLimits, SecretPurpose, SecretSource, SecretSpec, SystemSecretClock,
};

use crate::config::{HttpInstallation, ProviderIdentity, ProviderSecretFile};

pub(super) async fn install(
    pools: &Arc<ProviderPools>,
    config: &HttpInstallation,
    deadline: Instant,
) -> Result<(HttpProvider, Option<LocalSecretStore>), PlatformError> {
    let (references, secrets) = credential_references(
        pools,
        &config.identity,
        &config.configuration,
        config.credential_directory.as_deref(),
        &config.credentials,
        deadline,
    )
    .await?;
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

pub(super) async fn credential_references(
    pools: &Arc<ProviderPools>,
    identity: &ProviderIdentity,
    configuration: &HttpProviderConfig,
    directory: Option<&Path>,
    credentials: &[ProviderSecretFile],
    deadline: Instant,
) -> Result<(Vec<HttpCredentialReference>, Option<LocalSecretStore>), PlatformError> {
    let mut references = Vec::with_capacity(credentials.len());
    let secrets = if let Some(directory) = directory {
        let store = LocalSecretStore::open_before(
            pools.clone(),
            directory.to_path_buf(),
            SecretLimits::default(),
            Vec::new(),
            Arc::new(SystemSecretClock),
            deadline,
        )
        .map_err(|_| super::unavailable())?
        .await
        .map_err(|_| super::unavailable())?;
        let specs = credentials
            .iter()
            .map(|credential| SecretSpec {
                tenant: TenantId(identity.tenant.clone()),
                reference: credential.reference.clone(),
                source: SecretSource::File {
                    name: credential.file.clone(),
                },
                purpose: SecretPurpose::ProviderCredential {
                    provider_id: identity.id.clone(),
                    origin: configuration.destinations[credential.destination]
                        .origin
                        .clone(),
                },
                media_type: "text/plain".into(),
                version: identity.epoch.to_string(),
                expires_at_unix_millis: None,
            })
            .collect();
        store
            .reload_before(0, specs, deadline)
            .map_err(|_| super::unavailable())?
            .await
            .map_err(|_| super::unavailable())?;
        for credential in credentials {
            let binding = store
                .bind_credential(
                    CredentialScope {
                        tenant: TenantId(identity.tenant.clone()),
                        provider_id: identity.id.clone(),
                        origin: configuration.destinations[credential.destination]
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
    Ok((references, secrets))
}
