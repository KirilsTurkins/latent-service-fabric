//! Protected incoming configuration is separate from guest publisher credentials.
use super::{invalid, NodeConfig};
use latent_core::{BudgetProfile, PlatformError};
use latent_nats::triggers::TriggerConfig;
use serde::Deserialize;
use std::path::{Component, Path, PathBuf};

#[derive(Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct TriggerInstallation {
    pub id: String,
    pub epoch: u64,
    pub configuration_file: PathBuf,
    pub credential_directory: PathBuf,
    pub credentials: Vec<TriggerCredentialFile>,
}
#[derive(Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct TriggerCredentialFile {
    pub tenant: String,
    pub reference: String,
    pub file: String,
    pub username: Option<String>,
}

#[derive(Clone)]
pub(crate) struct TriggerSettings {
    pub installation: TriggerInstallation,
    pub configuration: TriggerConfig,
}

pub(super) fn present<'de, D: serde::Deserializer<'de>>(
    source: D,
) -> Result<Option<TriggerInstallation>, D::Error> {
    TriggerInstallation::deserialize(source).map(Some)
}

pub(super) fn anchor(value: &mut TriggerInstallation, parent: &Path) -> Result<(), PlatformError> {
    for path in [
        &mut value.configuration_file,
        &mut value.credential_directory,
    ] {
        if path.as_os_str().is_empty() || path.as_os_str().len() > 4096 {
            return Err(invalid("transactionalTriggers.path"));
        }
        if path.is_relative() {
            *path = parent
                .canonicalize()
                .map_err(|_| invalid("configurationPath"))?
                .join(&*path);
        }
    }
    Ok(())
}

pub(super) fn derive(config: &NodeConfig) -> Result<Option<TriggerSettings>, PlatformError> {
    let Some(value) = &config.transactional_triggers else {
        return Ok(None);
    };
    if !cfg!(all(target_os = "linux", target_arch = "x86_64"))
        || !config.credentials_from_protected_file
        || config.budget_profile.profile() != BudgetProfile::Phase4
        || config.state.is_none()
        || config.audit.is_none()
        || config.capability_policies.is_none()
        || !matches!(
            config.supply_chain,
            super::SupplyChainConfig::Enforced { .. }
        )
        || !token(&value.id, 128)
        || value.epoch == 0
        || value.credentials.is_empty()
        || value.credentials.capacity() > 8
    {
        return Err(invalid("transactionalTriggers.runtimeOwners"));
    }
    for path in [&value.configuration_file, &value.credential_directory] {
        if !path.is_absolute()
            || path.as_os_str().len() > 4096
            || path
                .components()
                .any(|part| matches!(part, Component::ParentDir))
        {
            return Err(invalid("transactionalTriggers.path"));
        }
    }
    let bytes = super::protected_file::read(
        &value.configuration_file,
        524_288,
        super::protected_file::ProtectedFilePolicy::Secret,
        "transactionalTriggers.configurationProtection",
    )?;
    let configuration = TriggerConfig::from_json(&bytes)
        .map_err(|_| invalid("transactionalTriggers.configuration"))?;
    if configuration.maximum_payload_bytes > config.limits.maximum_payload_bytes
        || configuration.operation_timeout_millis > config.execution.maximum_wall_time_millis
        || configuration
            .bindings
            .iter()
            .any(|binding| binding.transaction.is_none())
    {
        return Err(invalid("transactionalTriggers.configuration"));
    }
    for (index, credential) in value.credentials.iter().enumerate() {
        if [&credential.tenant, &credential.reference, &credential.file]
            .iter()
            .any(|name| !token(name, 128))
            || credential.file.contains(['/', '\\', ':'])
            || matches!(credential.file.as_str(), "." | "..")
            || credential
                .username
                .as_ref()
                .is_some_and(|name| !token(name, 128))
            || value.credentials[..index]
                .iter()
                .any(|old| old.tenant == credential.tenant || old.reference == credential.reference)
            || !configuration
                .bindings
                .iter()
                .any(|binding| binding.tenant == credential.tenant)
        {
            return Err(invalid("transactionalTriggers.credentials"));
        }
    }
    if configuration.bindings.iter().any(|binding| {
        !value
            .credentials
            .iter()
            .any(|credential| credential.tenant == binding.tenant)
    }) {
        return Err(invalid("transactionalTriggers.credentials"));
    }
    if let Some(providers) = &config.providers {
        for identity in [
            providers.http.as_ref().map(|v| &v.identity),
            providers.http_streaming.as_ref().map(|v| &v.identity),
            providers.blob.as_ref().map(|v| &v.identity),
            providers.secrets.as_ref().map(|v| &v.identity),
            providers.metrics.as_ref().map(|v| &v.identity),
            providers.local_service.as_ref().map(|v| &v.identity),
            providers.events.as_ref().map(|v| &v.identity),
            providers.clock_monotonic.as_ref().map(|v| &v.identity),
            providers.clock_wall.as_ref().map(|v| &v.identity),
            providers.random.as_ref().map(|v| &v.identity),
            providers.context.as_ref().map(|v| &v.identity),
            providers.log.as_ref().map(|v| &v.identity),
        ]
        .into_iter()
        .flatten()
        {
            if identity.id == value.id {
                return Err(invalid("transactionalTriggers.providerIdentity"));
            }
        }
    }
    Ok(Some(TriggerSettings {
        installation: value.clone(),
        configuration,
    }))
}

fn token(value: &String, maximum: usize) -> bool {
    !value.is_empty()
        && value.capacity() <= maximum
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"-_.:@".contains(&byte))
}
