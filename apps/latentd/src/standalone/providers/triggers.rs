//! Retain incoming TLS references on the existing node pools and secret owner.
use crate::config::triggers::TriggerSettings;
use latent_capabilities::broker::{pools::ProviderPools, secrets::TlsCredentialScope};
use latent_core::{PlatformError, TenantId};
use latent_nats::triggers::{BrokerInputProgress, InboxAdmissionFactory, NatsTriggerInspector};
use latent_nats::{triggers::NatsTriggers, NatsCredential};
use latent_secrets::{LocalSecretStore, SecretPurpose, SecretSource, SecretSpec};
use std::{sync::Arc, time::Instant};

pub(super) async fn install(
    pools: &Arc<ProviderPools>,
    store: &LocalSecretStore,
    settings: &TriggerSettings,
    admission: Arc<dyn InboxAdmissionFactory>,
    deadline: Instant,
) -> Result<NatsTriggers, PlatformError> {
    let credentials = credentials(store, settings, deadline).await?;
    let installation = &settings.installation;
    let mut incoming = NatsTriggers::install_with_transaction_admission(
        Arc::clone(pools),
        &installation.id,
        installation.epoch,
        0,
        settings.configuration.clone(),
        credentials,
        admission,
    )
    .map_err(|_| super::unavailable())?;
    Box::pin(incoming.qualify_startup(deadline))
        .await
        .map_err(inspection_error)?;
    Ok(incoming)
}

pub(super) async fn inspect(
    pools: &Arc<ProviderPools>,
    settings: &TriggerSettings,
    tenant: &str,
    binding: &str,
    deadline: Instant,
) -> Result<BrokerInputProgress, PlatformError> {
    let installation = &settings.installation;
    let store = LocalSecretStore::open_before(
        Arc::clone(pools),
        installation.credential_directory.clone(),
        latent_secrets::SecretLimits::default(),
        Vec::new(),
        Arc::new(latent_secrets::SystemSecretClock),
        deadline,
    )
    .map_err(|_| super::unavailable())?
    .await
    .map_err(|_| super::unavailable())?;
    let observation = async {
        let credentials = credentials(&store, settings, deadline).await?;
        let inspection = NatsTriggerInspector::install(
            Arc::clone(pools),
            &installation.id,
            installation.epoch,
            settings.configuration.clone(),
            credentials,
        )
        .map_err(|_| super::unavailable())?;
        inspection
            .inspect(tenant, binding, deadline)
            .await
            .map_err(inspection_error)
    }
    .await;
    store.close();
    observation
}

fn inspection_error(error: latent_nats::EventError) -> PlatformError {
    let reason = match error {
        latent_nats::EventError::PermissionDenied => "transactional-input-broker-identity-changed",
        _ => "transactional-input-broker-inspection-unavailable",
    };
    crate::standalone::error(latent_core::PlatformErrorCode::Unavailable, reason)
}

async fn credentials(
    store: &LocalSecretStore,
    settings: &TriggerSettings,
    deadline: Instant,
) -> Result<Vec<NatsCredential>, PlatformError> {
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
    installation
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
        .collect()
}
