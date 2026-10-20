use std::path::{Component, Path, PathBuf};

use latent_core::PlatformError;
use latent_http::{HttpProviderConfig, HttpStreamLimits};
use serde::Deserialize;

use super::{
    invalid, present, validate_http_credentials, ConfiguredProviders, HostBinding,
    ProviderIdentity, ProviderSecretFile,
};

/// Explicit installation of the existing typed HTTP 0.3 provider. Neither its
/// endpoint configuration nor its limits confer a guest capability grant.
#[derive(Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct HttpStreamingInstallation {
    pub identity: ProviderIdentity,
    pub configuration: HttpProviderConfig,
    pub limits: HttpStreamLimits,
    /// Explicitly select the new V7/HTTP0.4 profile; absence keeps HTTP0.3.
    #[serde(default)]
    pub phase_timing: bool,
    #[serde(default, deserialize_with = "present")]
    pub credential_directory: Option<PathBuf>,
    #[serde(default)]
    pub credentials: Vec<ProviderSecretFile>,
}

impl HttpStreamingInstallation {
    pub(super) fn validate_installation(
        &self,
        providers: &ConfiguredProviders,
    ) -> Result<(), PlatformError> {
        self.identity.validate()?;
        self.configuration
            .validate()
            .map_err(|_| invalid("providers.httpStreaming.configuration"))?;
        self.limits
            .validate()
            .map_err(|_| invalid("providers.httpStreaming.limits"))?;
        validate_http_credentials(
            &self.configuration,
            self.credential_directory.is_some(),
            &self.credentials,
            "providers.httpStreaming.credentials",
        )?;
        if self.credential_directory.as_ref().is_some_and(|directory| {
            !directory.is_absolute()
                || directory.capacity() > 4096
                || directory
                    .components()
                    .any(|part| matches!(part, Component::ParentDir))
        }) {
            return Err(invalid("providers.httpStreaming.credentialDirectory"));
        }
        for identity in [
            providers.http.as_ref().map(|v| &v.identity),
            providers.blob.as_ref().map(|v| &v.identity),
            providers.secrets.as_ref().map(|v| &v.identity),
            providers.metrics.as_ref().map(|v| &v.identity),
            providers.local_service.as_ref().map(|v| &v.identity),
            providers.events.as_ref().map(|v| &v.identity),
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
        if let Some(directory) = &mut self.credential_directory {
            if directory.as_os_str().is_empty() || directory.as_os_str().len() > 4096 {
                return Err(invalid("providers.httpStreaming.credentialDirectory"));
            }
            if directory.is_relative() {
                *directory = parent
                    .canonicalize()
                    .map_err(|_| invalid("configurationPath"))?
                    .join(&*directory);
            }
        }
        Ok(())
    }
}

impl ConfiguredProviders {
    pub(crate) fn http_streaming_installations(
        &self,
    ) -> impl Iterator<Item = &HttpStreamingInstallation> {
        self.http_streaming
            .iter()
            .chain(&self.additional_http_streaming)
    }

    pub(crate) fn validate_http_streaming_installations(&self) -> Result<(), PlatformError> {
        if self.additional_http_streaming.capacity() > 16
            || self.installation_identities().count() + self.scalar_aliases.len() > 14
        {
            return Err(invalid("providers.additionalHttpStreaming.capacity"));
        }
        for http in self.http_streaming_installations() {
            http.validate_installation(self)?;
        }
        for http in &self.additional_http_streaming {
            if self
                .installation_identities()
                .filter(|other| other.id == http.identity.id)
                .count()
                != 1
                || self.installation_identities().any(|other| {
                    other.id != http.identity.id
                        && other.tenant == http.identity.tenant
                        && other.service == http.identity.service
                })
                || self
                    .scalar_aliases
                    .iter()
                    .any(|alias| alias.identity.id == http.identity.id)
            {
                return Err(invalid("providers.identity"));
            }
        }
        Ok(())
    }

    pub(super) fn http_streaming_binding(
        &self,
        binding: &HostBinding,
        phase: bool,
    ) -> Option<&ProviderIdentity> {
        let matching = || {
            self.http_streaming_installations()
                .filter(move |http| http.phase_timing == phase)
        };
        // Prefer the exact installation scope; the fallback retains the original
        // singleton scope refusal when no installation matches this tenant.
        matching()
            .find(|http| {
                http.identity.tenant == binding.tenant
                    && http.identity.service == binding.provider_service
            })
            .or_else(|| matching().next())
            .map(|http| &http.identity)
    }
}
