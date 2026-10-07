//! Retain incoming TLS references on the existing node pools and secret owner.
use crate::config::triggers::TriggerSettings;
use crate::standalone::state::StateRuntime;
use latent_capabilities::broker::{pools::ProviderPools, secrets::TlsCredentialScope};
use latent_core::{PlatformError, TenantId};
use latent_nats::{triggers::NatsTriggers, NatsCredential};
use latent_secrets::{LocalSecretStore, SecretPurpose, SecretSource, SecretSpec};
use std::{sync::Arc, time::Instant};

pub(super) async fn install(
    pools: &Arc<ProviderPools>,
    store: &LocalSecretStore,
    settings: &TriggerSettings,
    state: Arc<StateRuntime>,
    deadline: Instant,
) -> Result<NatsTriggers, PlatformError> {
    let installation = &settings.installation;
    let destination = settings.configuration.endpoint.credential_destination();
    let specs = installation
        .credentials
        .iter()
        .map(|credential| SecretSpec {
            tenant: TenantId(credential.tenant.clone()),
            reference: credential.reference.clone(),
            source: SecretSource::File {
                name: credential.file.clone(),
            },
            purpose: SecretPurpose::TlsProviderCredential {
                provider_id: installation.id.clone(),
                destination: destination.clone(),
            },
            media_type: "text/plain".into(),
            version: installation.epoch.to_string(),
            expires_at_unix_millis: None,
        })
        .collect();
    store
        .reload_before(0, specs, deadline)
        .map_err(|_| super::unavailable())?
        .await
        .map_err(|_| super::unavailable())?;
    let credentials = installation
        .credentials
        .iter()
        .map(|credential| {
            let secret = store
                .bind_tls_credential(
                    TlsCredentialScope {
                        tenant: TenantId(credential.tenant.clone()),
                        provider_id: installation.id.clone(),
                        destination: destination.clone(),
                    },
                    credential.reference.clone(),
                )
                .map_err(|_| super::unavailable())?;
            Ok(NatsCredential {
                username: credential.username.clone(),
                secret,
            })
        })
        .collect::<Result<Vec<_>, PlatformError>>()?;
    NatsTriggers::install_with_transaction_admission(
        Arc::clone(pools),
        &installation.id,
        installation.epoch,
        0,
        settings.configuration.clone(),
        credentials,
        state,
    )
    .map_err(|_| super::unavailable())
}
