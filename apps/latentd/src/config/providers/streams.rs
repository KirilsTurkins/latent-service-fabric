use super::{super::invalid, ConfiguredProviders, ProviderIdentity};
use latent_core::PlatformError;
use serde::Deserialize;
use std::path::{Component, Path};

/// Explicit immutable opaque TCP/direct host TLS installation. Guest TLS and
/// protocol secrets require their independent language/secret grants. Direct
/// host TLS accepts only protected pinned trust files, never client keys.
#[derive(Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct StreamInstallation {
    pub identity: ProviderIdentity,
    pub configuration: latent_streams::StreamProviderConfig,
}
impl StreamInstallation {
    pub(super) fn anchor(&mut self, parent: &Path) -> Result<(), PlatformError> {
        for destination in &mut self.configuration.destinations {
            if let Some(tls) = &mut destination.tls {
                for root in &mut tls.roots {
                    if root.file.as_os_str().is_empty()
                        || root.file.as_os_str().len() > 4096
                        || root
                            .file
                            .components()
                            .any(|part| matches!(part, Component::ParentDir | Component::CurDir))
                    {
                        return Err(invalid("providers.outboundStreams.tls.trustProtection"));
                    }
                    if root.file.is_relative() {
                        root.file = parent
                            .canonicalize()
                            .map_err(|_| invalid("configurationPath"))?
                            .join(&root.file);
                    }
                }
            }
        }
        Ok(())
    }
    pub(super) fn validate_installation(
        &self,
        all: &ConfiguredProviders,
    ) -> Result<(), PlatformError> {
        if !cfg!(feature = "development-outbound-streams") {
            return Err(invalid("providers.outboundStreams.profile-disabled"));
        }
        self.identity.validate()?;
        self.configuration
            .validate()
            .map_err(|_| invalid("providers.outboundStreams.configuration"))?;
        for identity in [
            all.http.as_ref().map(|v| &v.identity),
            all.activation_runtime.as_ref().map(|v| &v.identity),
            all.blob.as_ref().map(|v| &v.identity),
            all.secrets.as_ref().map(|v| &v.identity),
            all.metrics.as_ref().map(|v| &v.identity),
            all.local_service.as_ref().map(|v| &v.identity),
            all.events.as_ref().map(|v| &v.identity),
            all.clock_monotonic.as_ref().map(|v| &v.identity),
            all.clock_wall.as_ref().map(|v| &v.identity),
            all.random.as_ref().map(|v| &v.identity),
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
}
