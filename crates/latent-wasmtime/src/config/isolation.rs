//! Exact requirements; a name never supplies an admission or compiler owner.

use latent_core::{PlatformError, PlatformErrorCode};
use serde::{Deserialize, Serialize};

#[cfg(test)]
mod tests;

/// Supported node execution profiles from ADR-0026. The compiler/native
/// subprofiles are separate mechanisms, not stronger guest-process isolation.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Deserialize, Serialize)]
pub enum ExecutionIsolationProfile {
    #[default]
    #[serde(rename = "local-experimental-v1")]
    LocalExperimental,
    #[serde(rename = "external-capsule-v1")]
    ExternalCapsule,
}

impl ExecutionIsolationProfile {
    #[must_use]
    pub const fn name(self) -> &'static str {
        match self {
            Self::LocalExperimental => "local-experimental-v1",
            Self::ExternalCapsule => "external-capsule-v1",
        }
    }

    pub(crate) fn validate_platform(self) -> Result<(), PlatformError> {
        if self == Self::ExternalCapsule
            && (!cfg!(all(target_os = "linux", target_arch = "x86_64"))
                || super::WASMTIME_VERSION != "47.0.4")
        {
            return Err(failure("external-capsule-runtime-profile-unavailable"));
        }
        Ok(())
    }

    pub(crate) fn validate_owners(
        self,
        mode: super::DispatchMode,
        admission: bool,
        isolated_compiler: bool,
    ) -> Result<(), PlatformError> {
        self.validate_platform()?;
        if self == Self::ExternalCapsule
            && (mode != super::DispatchMode::Generic || !admission || !isolated_compiler)
        {
            return Err(failure(
                "external-capsule-requires-enforced-isolated-owners",
            ));
        }
        Ok(())
    }
}

fn failure(message: &'static str) -> PlatformError {
    PlatformError {
        code: PlatformErrorCode::IncompatibleContract,
        message: message.into(),
        retryable: false,
        details: Vec::new(),
    }
}
