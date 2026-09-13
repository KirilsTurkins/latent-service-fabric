//! Actual engine identity and a closed compiler-only bootstrap.
mod hash;

use super::{blob, exhausted, frame, invalid, mismatch, AotCompilerLimits};
use crate::config::{CompilerEngineSettings, DispatchMode};
use crate::{WasmtimeConfig, WasmtimeEngineProfile};
use latent_core::PlatformError;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use wasmtime::{Config, Engine};

pub(crate) const MAX_BOOTSTRAP_BYTES: usize = 4096;

/// Immutable facts derived from validated host configuration and a real Engine.
/// This does not retain an Engine, pooling allocator, service Store or worker.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ValidatedAotProfile {
    identity: [u8; 32],
    engine: [u8; 32],
    policy: [u8; 32],
    capabilities: [u8; 32],
    bootstrap: Bootstrap,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Bootstrap {
    format_version: u32,
    target: Box<str>,
    engine_compatibility: String,
    settings: CompilerEngineSettings,
}

impl ValidatedAotProfile {
    pub fn from_config(
        config: &WasmtimeConfig,
        limits: AotCompilerLimits,
    ) -> Result<Self, PlatformError> {
        let limits = limits.validate()?;
        config.validate()?;
        limits.identity(&config.target_triple)?;
        limits.identity(&config.cpu_feature_set)?;
        let runtime = config.detected_runtime_profile()?;
        let declared = config.profile_with_runtime(DispatchMode::Generic, Some(&runtime));
        let policy = declared_digest(&declared, limits)?;
        let settings = CompilerEngineSettings::from_config(config);
        let engine = compiler_engine(&settings)?;
        let engine_identity = hash::engine(&engine);
        drop(engine);
        let capabilities = capabilities();
        let mut digest = Sha256::new();
        digest.update(b"lsf-validated-aot-profile-v1\0");
        for value in [&policy, &engine_identity, &capabilities, runtime.digest()] {
            frame(&mut digest, value);
        }
        Ok(Self {
            identity: digest.finalize().into(),
            engine: engine_identity,
            policy,
            capabilities,
            bootstrap: Bootstrap {
                format_version: 1,
                target: config.target_triple.as_str().into(),
                engine_compatibility: blob(engine_identity).into_string(),
                settings,
            },
        })
    }
    #[must_use]
    pub const fn digest(&self) -> &[u8; 32] {
        &self.identity
    }
    #[must_use]
    pub const fn engine_compatibility(&self) -> &[u8; 32] {
        &self.engine
    }
    #[must_use]
    pub const fn security_policy_digest(&self) -> &[u8; 32] {
        &self.policy
    }
    #[must_use]
    pub const fn capability_contract_digest(&self) -> &[u8; 32] {
        &self.capabilities
    }
    /// Checks an actual engine at the future native-loader boundary; caller
    /// labels and profile metadata cannot substitute for this comparison.
    pub fn check_engine(&self, engine: &Engine) -> Result<(), PlatformError> {
        if hash::engine(engine) != self.engine {
            return Err(mismatch());
        }
        Ok(())
    }

    /// Closed, bounded trusted-child input; decoding alone grants no authority.
    pub fn bootstrap(&self) -> Result<Vec<u8>, PlatformError> {
        // Private fields have fixed-size numbers and at most a native target and
        // SHA-256 string. No caller collection/string can grow this allocation.
        let bytes = serde_json::to_vec(&self.bootstrap).map_err(|_| invalid())?;
        if bytes.len() > MAX_BOOTSTRAP_BYTES {
            return Err(exhausted());
        }
        Ok(bytes)
    }
}

pub(crate) fn engine_from_bootstrap(
    bytes: &[u8],
    limits: AotCompilerLimits,
) -> Result<(Engine, [u8; 32]), PlatformError> {
    let limits = limits.validate()?;
    if bytes.len() > MAX_BOOTSTRAP_BYTES {
        return Err(exhausted());
    }
    // Every object is closed and each leaf is a scalar. Serde rejects duplicate
    // members, unknown fields, nulls and unexpected nested containers directly.
    let value: Bootstrap = serde_json::from_slice(bytes).map_err(|_| invalid())?;
    if value.format_version != 1 || value.target.as_ref() != env!("LATENT_WASMTIME_HOST_TARGET") {
        return Err(mismatch());
    }
    limits.identity(&value.target)?;
    let expected: latent_core::ArtifactBlobDigest =
        value.engine_compatibility.parse().map_err(|_| invalid())?;
    let engine = compiler_engine(&value.settings)?;
    let actual = hash::engine(&engine);
    if blob(actual) != expected {
        return Err(mismatch());
    }
    Ok((engine, actual))
}

fn compiler_engine(settings: &CompilerEngineSettings) -> Result<Engine, PlatformError> {
    settings.validate_compiler()?;
    let mut config = Config::new();
    settings.apply(&mut config);
    // The workspace pins Wasmtime without `parallel-compilation`; that feature's
    // setter is unavailable and compilation cannot create a Rayon worker pool.
    // Keep this dependency invariant when updating the pinned engine features.
    Engine::new(&config).map_err(|_| invalid())
}

fn declared_digest(
    profile: &WasmtimeEngineProfile,
    limits: AotCompilerLimits,
) -> Result<[u8; 32], PlatformError> {
    if profile.configuration.len() > limits.maximum_profile_entries {
        return Err(exhausted());
    }
    let mut remaining = limits.maximum_profile_bytes;
    let mut digest = Sha256::new();
    digest.update(b"lsf-aot-engine-profile-v1\0");
    for value in [
        &profile.id,
        &profile.wasmtime_version,
        &profile.target_triple,
        &profile.cpu_feature_set,
    ] {
        limits.identity(value)?;
        remaining = remaining.checked_sub(value.len()).ok_or_else(exhausted)?;
        frame(&mut digest, value.as_bytes());
    }
    digest.update([
        u8::from(profile.pooling_allocator),
        u8::from(profile.copy_on_write_images),
        u8::from(profile.async_support),
        u8::from(profile.fuel_enabled),
        u8::from(profile.epoch_interruption_enabled),
    ]);
    for (name, value) in &profile.configuration {
        limits.identity(name)?;
        limits.identity(value)?;
        remaining = remaining
            .checked_sub(name.len())
            .and_then(|left| left.checked_sub(value.len()))
            .ok_or_else(exhausted)?;
        frame(&mut digest, name.as_bytes());
        frame(&mut digest, value.as_bytes());
    }
    Ok(digest.finalize().into())
}

fn capabilities() -> [u8; 32] {
    let mut digest = Sha256::new();
    digest.update(b"lsf-aot-host-capability-contracts-v1\0");
    for bytes in [
        include_bytes!("../../../../wit/platform/context/package.wit").as_slice(),
        include_bytes!("../../../../wit/platform/log/package.wit").as_slice(),
        include_bytes!("../../../../wit/platform/clock/package.wit").as_slice(),
    ] {
        frame(&mut digest, bytes);
    }
    digest.finalize().into()
}
