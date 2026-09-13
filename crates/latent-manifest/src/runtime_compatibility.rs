//! Closed manifest requirements and immutable, bounded host facts.

pub(crate) mod model;
mod profile;
#[cfg(test)]
mod tests;

pub use model::{RuntimeRequirement, RuntimeRequirements, CPU_FEATURES};
pub use profile::RuntimeCompatibilityProfile;

use latent_core::{PlatformError, PlatformErrorCode};

use crate::{validation::SemanticVersion, CapsuleManifest, PHASE1_FABRIC_VERSION};

/// Checks explicit requirements against a configured host. Omitted requirements
/// remain valid for legacy embeddings that do not configure a host profile.
pub fn check_runtime_compatibility(
    manifest: &CapsuleManifest,
    profile: Option<&RuntimeCompatibilityProfile>,
) -> Result<(), PlatformError> {
    manifest.runtime_requirements.validate()?;
    let required = version(&manifest.minimum_fabric_version)?;
    if required > version(PHASE1_FABRIC_VERSION)? {
        return Err(incompatible("fabric-contract-version-incompatible"));
    }
    match profile {
        Some(profile) => profile.check_capsule(manifest),
        None if manifest.runtime_requirements.is_empty() => Ok(()),
        None => Err(incompatible("runtime-profile-unavailable")),
    }
}

fn error(code: PlatformErrorCode, message: &'static str) -> PlatformError {
    PlatformError {
        code,
        message: message.into(),
        retryable: false,
        details: Vec::new(),
    }
}

fn incompatible(message: &'static str) -> PlatformError {
    error(PlatformErrorCode::IncompatibleContract, message)
}

fn invalid() -> PlatformError {
    error(
        PlatformErrorCode::InvalidArgument,
        "invalid-runtime-compatibility",
    )
}

fn exhausted() -> PlatformError {
    error(
        PlatformErrorCode::ResourceExhausted,
        "runtime-compatibility-limit",
    )
}

fn version(value: &str) -> Result<SemanticVersion, PlatformError> {
    if value.len() > 128 {
        return Err(exhausted());
    }
    SemanticVersion::parse(value).ok_or_else(invalid)
}
