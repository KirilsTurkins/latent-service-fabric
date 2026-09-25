use super::{invalid, token, ConfiguredProviders, ProviderIdentity};
use latent_core::PlatformError;
use serde::Deserialize;

/// One explicitly installed dispatcher to a configured local deployment.
/// Publication, exported ABI, policy and route currentness are checked by the
/// ordinary binding compiler and activation manager, never granted here.
#[derive(Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct LocalServiceInstallation {
    pub identity: ProviderIdentity,
    pub deployment: String,
    pub contract: String,
}

impl LocalServiceInstallation {
    pub(super) fn validate_installation(
        &self,
        providers: &ConfiguredProviders,
    ) -> Result<(), PlatformError> {
        self.validate()?;
        for identity in [
            providers.http.as_ref().map(|v| &v.identity),
            providers.blob.as_ref().map(|v| &v.identity),
            providers.secrets.as_ref().map(|v| &v.identity),
            providers.metrics.as_ref().map(|v| &v.identity),
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

    pub(super) fn validate(&self) -> Result<(), PlatformError> {
        self.identity.validate()?;
        if !token(&self.deployment, 128)
            || !token(&self.contract, 128)
            || self.contract == latent_capabilities::broker::SERVICE_INVOCATION_CAPABILITY
        {
            return Err(invalid("providers.localService"));
        }
        Ok(())
    }
}
