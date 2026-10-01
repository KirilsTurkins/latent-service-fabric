//! Configuration identities for the actual Wasmtime activation-clock imports.
//! Registrations are node-fixed; calls remain charged to the activation broker.
use latent_capabilities::broker::{
    ActivationCapabilityBroker, ProviderBudgetRequirement, ProviderConfiguration,
    ProviderRegistration,
};
use latent_core::{BudgetDimension, PlatformError};

pub(super) fn activation_runtime(
    broker: &ActivationCapabilityBroker,
    installation: &crate::config::ActivationRuntimeInstallation,
) -> Result<ProviderRegistration, PlatformError> {
    let operations = latent_core::activation_runtime::OPERATIONS;
    let digest = installation.configuration_digest()?;
    let restriction = serde_json::to_vec(&serde_json::json!({"operations": operations}))
        .map_err(|_| super::unavailable())?;
    let charges = operations.map(|operation| ProviderBudgetRequirement {
        operation,
        dimension: BudgetDimension::CpuFuel,
        minimum: 100,
    });
    broker.register_provider(ProviderConfiguration {
        capability: latent_core::activation_runtime::CAPABILITY,
        profile: latent_core::activation_runtime::PROFILE,
        configuration_digest: digest.as_str(),
        configuration_epoch: installation.identity.epoch,
        restriction_json: &restriction,
        minimum_call_charges: &charges,
    })
}

pub(super) fn clock(
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
