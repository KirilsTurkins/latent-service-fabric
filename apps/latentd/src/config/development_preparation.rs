//! Closed, consented reproduction of a former preparation policy. Compiled out
//! of product binaries; never provides supply-chain or execution authority.
use super::{invalid, ExecutionIsolationProfile, NodeConfig};
use latent_core::PlatformError;
use latent_wasmtime::WasmtimeConfig;
use serde::{Deserialize, Deserializer};

#[derive(Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct DevelopmentPreparationProfile {
    format_version: u32,
    consent: bool,
    purpose: String,
    profile: String,
}

pub(super) fn present<'de, D: Deserializer<'de>>(
    input: D,
) -> Result<Option<DevelopmentPreparationProfile>, D::Error> {
    // Required object; a present null/array must not silently disable a fixture.
    super::development::object(input).map(Some)
}

impl DevelopmentPreparationProfile {
    pub(super) fn apply(
        &self,
        node: &NodeConfig,
        runtime: &mut WasmtimeConfig,
    ) -> Result<(), PlatformError> {
        if self.format_version != 1
            || !self.consent
            || self.purpose != "disposable-development-tests"
            || self.profile != "former-http-global-values-v1"
            || node.security_profile != ExecutionIsolationProfile::LocalExperimental
            || node.isolated_aot.is_some()
            || node.renderer_profile.is_some()
            || node.http_ingress.is_some()
            || !node.bind.ip().is_loopback()
        {
            return Err(invalid("developmentPreparation.explicitLocalTestRequired"));
        }
        runtime.hostcall_fuel = 2 * 1024 * 1024;
        runtime.value_codec_limits.max_lifted_bytes = 64 * 1024 * 1024;
        runtime.buffered_web_value_profile = None;
        Ok(())
    }
}
