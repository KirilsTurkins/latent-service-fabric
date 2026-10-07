//! Explicit finite activation ownership installation. Configuration grants no
//! clock, scheduling, HTTP or stream authority and creates no language executor.
use latent_core::{activation_runtime::RuntimeLimits, ArtifactBlobDigest, PlatformError};
use serde::{Deserialize, Serialize};

use super::{invalid, ConfiguredProviders, ProviderIdentity};

#[derive(Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ActivationRuntimeInstallation {
    pub identity: ProviderIdentity,
    pub limits: ActivationRuntimeLimits,
}

/// Every category is required, including deliberately disabled zero categories.
/// There is no default, implicit expansion or new activation budget dimension.
#[derive(Clone, Copy, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ActivationRuntimeLimits {
    pub tasks: u32,
    pub executors: u32,
    pub queued_work: u32,
    pub waits: u32,
    pub timers: u32,
    pub results: u32,
    pub native_owners: u32,
}

impl ActivationRuntimeInstallation {
    pub(super) fn validate_installation(
        &self,
        providers: &ConfiguredProviders,
    ) -> Result<(), PlatformError> {
        self.identity.validate()?;
        self.runtime_limits()
            .validate()
            .map_err(|_| invalid("providers.activationRuntime.limits"))?;
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

    pub(crate) const fn runtime_limits(&self) -> RuntimeLimits {
        RuntimeLimits {
            tasks: self.limits.tasks,
            executors: self.limits.executors,
            queued_work: self.limits.queued_work,
            waits: self.limits.waits,
            timers: self.limits.timers,
            results: self.limits.results,
            native_owners: self.limits.native_owners,
        }
    }

    /// Fixed interface/profile plus all operator limits define the immutable
    /// provider identity. The epoch remains a separately pinned currentness key.
    pub(crate) fn configuration_digest(&self) -> Result<ArtifactBlobDigest, PlatformError> {
        let bytes = serde_json::to_vec(&serde_json::json!({
            "formatVersion": 1,
            "capability": latent_core::activation_runtime::CAPABILITY,
            "profile": latent_core::activation_runtime::PROFILE,
            "hostAbi": latent_core::host_profile::PHASE3_HOST_ABI_V5.id,
            "operations": latent_core::activation_runtime::OPERATIONS,
            "limits": self.limits
        }))
        .map_err(|_| invalid("providers.activationRuntime"))?;
        Ok(latent_artifacts::package::artifact_blob_digest(&bytes))
    }
}
