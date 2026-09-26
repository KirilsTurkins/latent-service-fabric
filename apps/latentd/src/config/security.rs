//! Validated deployment requirements and bounded non-secret observations.

use std::collections::BTreeMap;

use latent_core::{PlatformError, PHASE3_HOST_ABI_CURRENT};
use latent_wasmtime::ExecutionIsolationProfile;
use serde::Serialize;

use super::{invalid, NodeConfig, NodeSettings, SupplyChainConfig};

pub(super) fn validate(config: &NodeConfig) -> Result<(), PlatformError> {
    if config.security_profile == ExecutionIsolationProfile::ExternalCapsule
        && (!config.credentials_from_protected_file
            || !matches!(config.supply_chain, SupplyChainConfig::Enforced { .. })
            || config.isolated_aot.is_none())
    {
        return Err(invalid("securityProfile.externalCapsulePrerequisites"));
    }
    Ok(())
}

/// Configuration/startup observations, never a capability or native-code proof.
#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ExecutionProfileReport {
    schema_version: &'static str,
    profile: ExecutionIsolationProfile,
    threat_class: &'static str,
    guest_boundary: &'static str,
    admission: &'static str,
    protected_credential_file: bool,
    host_abi_profile: &'static str,
    wasmtime_version: &'static str,
    target: String,
    compiler: &'static str,
    compiler_sandbox: Option<&'static str>,
    authenticated_native_loading: bool,
    #[cfg(feature = "development-test-node")]
    #[serde(skip_serializing_if = "Option::is_none")]
    development_guest_clock: Option<GuestClockReport>,
}

#[cfg(feature = "development-test-node")]
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
struct GuestClockReport {
    monotonic_nanos: String,
    wall_unix_millis: String,
}

#[cfg(feature = "development-test-node")]
fn guest_clock_report(settings: &NodeSettings) -> Option<GuestClockReport> {
    settings
        .wasmtime
        .development_clock_readings
        .map(|readings| GuestClockReport {
            monotonic_nanos: readings.monotonic_nanos.to_string(),
            wall_unix_millis: readings.wall_unix_millis.to_string(),
        })
}

impl ExecutionProfileReport {
    pub(crate) fn matches(&self, settings: &NodeSettings) -> bool {
        #[cfg(feature = "development-test-node")]
        if self.development_guest_clock != guest_clock_report(settings) {
            return false;
        }
        self.profile == settings.wasmtime.execution_isolation_profile
            && self.authenticated_native_loading == settings.isolated_aot.is_some()
            && self.protected_credential_file == settings.credentials_from_protected_file
            && (self.admission == "enforced") == settings.supply_chain.is_enforced()
    }

    pub(crate) fn attributes(&self) -> BTreeMap<String, String> {
        [
            ("lsf.security.profile", self.profile.name()),
            ("lsf.security.admission", self.admission),
            ("lsf.security.guest-boundary", self.guest_boundary),
            ("lsf.security.compiler", self.compiler),
            ("lsf.host-abi", self.host_abi_profile),
        ]
        .into_iter()
        .map(|(key, value)| (key.to_owned(), value.to_owned()))
        .collect()
    }
}

pub(super) fn check(settings: &NodeSettings) -> Result<ExecutionProfileReport, PlatformError> {
    let profile = settings.wasmtime.execution_isolation_profile;
    check_marker(settings)?;
    if profile == ExecutionIsolationProfile::ExternalCapsule
        && (!settings.credentials_from_protected_file
            || !settings.supply_chain.is_enforced()
            || settings.isolated_aot.is_none())
    {
        return Err(invalid("securityProfile.externalCapsulePrerequisites"));
    }
    settings.wasmtime.validate()?;
    if let Some(aot) = &settings.isolated_aot {
        aot.verify_compiler_readiness(&settings.wasmtime)?;
    }
    Ok(ExecutionProfileReport {
        schema_version: "latent.standalone.config-check.v1",
        profile,
        threat_class: if profile == ExecutionIsolationProfile::ExternalCapsule {
            "T1"
        } else {
            "T0"
        },
        guest_boundary: "in-process-wasmtime",
        admission: if settings.supply_chain.is_enforced() {
            "enforced"
        } else {
            "trusted-local"
        },
        protected_credential_file: settings.credentials_from_protected_file,
        host_abi_profile: PHASE3_HOST_ABI_CURRENT.id,
        wasmtime_version: latent_wasmtime::WASMTIME_VERSION,
        target: settings.wasmtime.target_triple.clone(),
        compiler: if settings.isolated_aot.is_some() {
            "isolated-aot-compiler-v1"
        } else {
            "in-process"
        },
        compiler_sandbox: settings
            .isolated_aot
            .as_ref()
            .map(|_| latent_wasmtime::ISOLATED_AOT_SANDBOX_PROFILE),
        authenticated_native_loading: settings.isolated_aot.is_some(),
        #[cfg(feature = "development-test-node")]
        development_guest_clock: guest_clock_report(settings),
    })
}

fn check_marker(settings: &NodeSettings) -> Result<(), PlatformError> {
    if settings.wasmtime.execution_isolation_profile != ExecutionIsolationProfile::ExternalCapsule {
        match std::fs::symlink_metadata(settings.data_directory.join("EXECUTION_PROFILE")) {
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(()),
            _ => return Err(invalid("securityProfile.externalCapsuleRequired")),
        }
    }
    super::protected_file::execution_profile_marker(&settings.data_directory, false)?;
    Ok(())
}

pub(super) fn persist(settings: &NodeSettings) -> Result<(), PlatformError> {
    check_marker(settings)?;
    if settings.wasmtime.execution_isolation_profile == ExecutionIsolationProfile::ExternalCapsule {
        super::protected_file::execution_profile_marker(&settings.data_directory, true)?;
    }
    Ok(())
}
