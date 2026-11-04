//! Canonical configuration for the actual activation and host-clock adapters.
//! These documents and registrations grant no authority by themselves.
use super::{
    ActivationCapabilityBroker, ProviderBudgetRequirement, ProviderConfiguration,
    ProviderRegistration,
};
use latent_core::{BudgetDimension, PlatformError};

/// Preserve the normal node's complete activation configuration document.
#[must_use]
pub fn activation_configuration(
    limits: impl serde::Serialize,
    native_threads: bool,
) -> serde_json::Value {
    let mut document = serde_json::json!({
        "formatVersion": 1,
        "capability": latent_core::activation_runtime::CAPABILITY,
        "profile": latent_core::activation_runtime::PROFILE,
        "hostAbi": latent_core::host_profile::PHASE3_HOST_ABI_V5.id,
        "operations": latent_core::activation_runtime::OPERATIONS,
        "limits": limits
    });
    if native_threads {
        document["nativeThreads"] = serde_json::json!({
            "capability": "latent:runtime-native/threads@0.1.0",
            "profile": "conservative-native-total-starts-v1",
            "hostAbi": latent_core::host_profile::PHASE3_HOST_ABI_V6.id,
            "operations": ["start"],
        });
    }
    document
}

/// Register the same activation-origin monotonic or system wall-clock adapter.
pub fn register_clock(
    broker: &ActivationCapabilityBroker,
    epoch: u64,
    monotonic: bool,
) -> Result<ProviderRegistration, PlatformError> {
    let (capability, profile, operation, restriction, identity) = if monotonic {
        (
            "latent:clock/monotonic@0.1.0",
            "activation-monotonic-v1",
            "now-nanos",
            br#"{"operations":["now-nanos"]}"#.as_slice(),
            b"latent-clock-monotonic-v1:activation-origin:clamped:u64:output8:fuel100".as_slice(),
        )
    } else {
        (
            "latent:clock/wall@0.1.0",
            "activation-wall-v1",
            "now-unix-millis",
            br#"{"operations":["now-unix-millis"]}"#.as_slice(),
            b"latent-clock-wall-v1:system-unix-millis:u64:output8:fuel100".as_slice(),
        )
    };
    let digest = latent_artifacts::package::artifact_blob_digest(identity);
    broker.register_provider(ProviderConfiguration {
        capability,
        profile,
        configuration_digest: digest.as_str(),
        configuration_epoch: epoch,
        restriction_json: restriction,
        minimum_call_charges: &[ProviderBudgetRequirement {
            operation,
            dimension: BudgetDimension::CpuFuel,
            minimum: 100,
        }],
    })
}
