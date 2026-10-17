use latent_core::PlatformError;
use serde::Deserialize;

use super::{invalid, ConfiguredProviders, HostBinding, ProviderIdentity, ScalarInstallation};

/// An explicit logical identity for an already installed stateless provider.
/// The original registration, implementation, epoch and resource limits remain.
#[derive(Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ScalarAlias {
    pub source: String,
    pub identity: ProviderIdentity,
}

impl ConfiguredProviders {
    fn scalar_sources(&self) -> [(Option<&ScalarInstallation>, &'static str); 5] {
        [
            (
                self.clock_monotonic.as_ref(),
                "latent:clock/monotonic@0.1.0",
            ),
            (self.clock_wall.as_ref(), "latent:clock/wall@0.1.0"),
            (self.random.as_ref(), "latent:random/random@0.1.0"),
            (self.context.as_ref(), "latent:context/context@0.1.0"),
            (self.log.as_ref(), "latent:log/log@0.1.0"),
        ]
    }

    fn scalar_source(
        &self,
        source: &str,
    ) -> Result<(&ProviderIdentity, &'static str), PlatformError> {
        let mut found = self
            .scalar_sources()
            .into_iter()
            .filter_map(|(value, contract)| {
                value
                    .filter(|value| value.identity.id == source)
                    .map(|value| (&value.identity, contract))
            });
        let selected = found
            .next()
            .ok_or_else(|| invalid("providers.scalarAliases.source"))?;
        if found.next().is_some()
            || self
                .installation_identities()
                .filter(|value| value.id == source)
                .count()
                != 1
        {
            return Err(invalid("providers.scalarAliases.source"));
        }
        Ok(selected)
    }

    fn installation_identities(&self) -> impl Iterator<Item = &ProviderIdentity> {
        [
            self.http.as_ref().map(|v| &v.identity),
            self.outbound_streams.as_ref().map(|v| &v.identity),
            self.http_streaming.as_ref().map(|v| &v.identity),
            self.activation_runtime.as_ref().map(|v| &v.identity),
            self.blob.as_ref().map(|v| &v.identity),
            self.secrets.as_ref().map(|v| &v.identity),
            self.metrics.as_ref().map(|v| &v.identity),
            self.local_service.as_ref().map(|v| &v.identity),
            self.events.as_ref().map(|v| &v.identity),
            self.clock_monotonic.as_ref().map(|v| &v.identity),
            self.clock_wall.as_ref().map(|v| &v.identity),
            self.random.as_ref().map(|v| &v.identity),
            self.context.as_ref().map(|v| &v.identity),
            self.log.as_ref().map(|v| &v.identity),
        ]
        .into_iter()
        .flatten()
    }

    pub(super) fn validate_scalar_aliases(&self) -> Result<(), PlatformError> {
        // Retain the original runtime's fourteen descriptor slots. Aliases do
        // not register another implementation or enlarge any original ledger.
        if self.scalar_aliases.capacity() > 16
            || self.installation_identities().count() + self.scalar_aliases.len() > 14
        {
            return Err(invalid("providers.scalarAliases.capacity"));
        }
        for (index, alias) in self.scalar_aliases.iter().enumerate() {
            alias.identity.validate()?;
            let (source, contract) = self.scalar_source(&alias.source)?;
            if alias.identity.epoch != source.epoch
                || self
                    .installation_identities()
                    .any(|value| value.id == alias.identity.id)
                || self.scalar_aliases[..index]
                    .iter()
                    .any(|value| value.identity.id == alias.identity.id)
            {
                return Err(invalid("providers.scalarAliases.identity"));
            }
            let same_scope = |value: &ProviderIdentity| {
                value.tenant == alias.identity.tenant && value.service == alias.identity.service
            };
            if self.scalar_sources().into_iter().any(|(value, other)| {
                other == contract && value.is_some_and(|value| same_scope(&value.identity))
            }) || self.scalar_aliases[..index].iter().any(|value| {
                same_scope(&value.identity)
                    && self
                        .scalar_source(&value.source)
                        .is_ok_and(|(_, other)| other == contract)
            }) {
                return Err(invalid("providers.scalarAliases.scope"));
            }
        }
        Ok(())
    }

    pub(super) fn scalar_alias_binding(
        &self,
        binding: &HostBinding,
    ) -> Result<Option<&ProviderIdentity>, PlatformError> {
        for alias in &self.scalar_aliases {
            let (_, contract) = self.scalar_source(&alias.source)?;
            if binding.contract == contract
                && binding.tenant == alias.identity.tenant
                && binding.provider_service == alias.identity.service
            {
                return Ok(Some(&alias.identity));
            }
        }
        Ok(None)
    }
}
