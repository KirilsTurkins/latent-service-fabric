use super::{super::invalid, ConfiguredProviders, ProviderIdentity};
use latent_core::PlatformError;
use serde::Deserialize;

/// Explicit immutable opaque TCP installation. TLS, if used by the selected
/// language runtime, and protocol secrets stay guest-visible and require their
/// own grants. This profile accepts no host trust/key paths or secret strings.
#[derive(Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct StreamInstallation {
    pub identity: ProviderIdentity,
    pub configuration: latent_streams::StreamProviderConfig,
}
impl StreamInstallation {
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
