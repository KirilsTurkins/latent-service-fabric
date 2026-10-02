use std::path::{Component, Path, PathBuf};

use latent_core::PlatformError;
use serde::Deserialize;

use super::{invalid, token, ConfiguredProviders, ProviderIdentity};

/// One tenant's explicitly configured immediate publisher. Credentials remain
/// protected provider references; no guest authority is created by installation.
#[derive(Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct EventInstallation {
    pub identity: ProviderIdentity,
    pub configuration: latent_nats::NatsConfig,
    pub credential_directory: PathBuf,
    pub credential_reference: String,
    pub credential_file: String,
    #[serde(default)]
    pub deferred: Vec<DeferredEventInstallation>,
}

/// One operator-qualified unordered mapping retained for committed effects.
#[derive(Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct DeferredEventInstallation {
    pub topic: String,
    pub qualification: latent_nats::deferred::JetStreamQualification,
}

impl EventInstallation {
    pub(super) fn validate_installation(
        &self,
        providers: &ConfiguredProviders,
    ) -> Result<(), PlatformError> {
        self.identity.validate()?;
        self.configuration
            .validate()
            .map_err(|_| invalid("providers.events.configuration"))?;
        if !self.credential_directory.is_absolute()
            || self.credential_directory.capacity() > 4096
            || self
                .credential_directory
                .components()
                .any(|p| matches!(p, Component::ParentDir))
            || !token(&self.credential_reference, 128)
            || !token(&self.credential_file, 128)
            || self.credential_file.contains(['/', '\\', ':'])
            || matches!(self.credential_file.as_str(), "." | "..")
            || self
                .configuration
                .topics
                .iter()
                .any(|row| row.tenant != self.identity.tenant)
        {
            return Err(invalid("providers.events.credentialsOrScope"));
        }
        if self.deferred.capacity() > 16 {
            return Err(invalid("providers.events.deferred"));
        }
        for (index, deferred) in self.deferred.iter().enumerate() {
            let mapping = self
                .configuration
                .topics
                .iter()
                .find(|mapping| mapping.topic == deferred.topic)
                .ok_or_else(|| invalid("providers.events.deferred.topic"))?;
            if deferred.topic.capacity() > 128
                || self.deferred[..index]
                    .iter()
                    .any(|other| other.topic == deferred.topic)
            {
                return Err(invalid("providers.events.deferred.topic"));
            }
            deferred
                .qualification
                .validate(mapping, &self.configuration)
                .map_err(|_| invalid("providers.events.deferred.qualification"))?;
        }
        for identity in [
            providers.http.as_ref().map(|v| &v.identity),
            providers.blob.as_ref().map(|v| &v.identity),
            providers.secrets.as_ref().map(|v| &v.identity),
            providers.metrics.as_ref().map(|v| &v.identity),
            providers.local_service.as_ref().map(|v| &v.identity),
            providers.clock_monotonic.as_ref().map(|v| &v.identity),
            providers.clock_wall.as_ref().map(|v| &v.identity),
            providers.random.as_ref().map(|v| &v.identity),
        ]
        .into_iter()
        .flatten()
        {
            if identity.id == self.identity.id
                || (identity.tenant == self.identity.tenant
                    && identity.service == self.identity.service)
            {
                return Err(invalid("providers.identity"));
            }
        }
        Ok(())
    }

    pub(super) fn anchor(&mut self, parent: &Path) -> Result<(), PlatformError> {
        if self.credential_directory.as_os_str().is_empty()
            || self.credential_directory.as_os_str().len() > 4096
        {
            return Err(invalid("providers.events.credentialDirectory"));
        }
        if self.credential_directory.is_relative() {
            self.credential_directory = parent
                .canonicalize()
                .map_err(|_| invalid("configurationPath"))?
                .join(&self.credential_directory);
        }
        Ok(())
    }
}
