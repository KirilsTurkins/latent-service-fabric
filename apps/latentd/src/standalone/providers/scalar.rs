//! Configuration identities for the actual Wasmtime activation-clock imports.
//! Registrations are node-fixed; calls remain charged to the activation broker.
use latent_capabilities::broker::{
    ActivationCapabilityBroker, ProviderBudgetRequirement, ProviderConfiguration,
    ProviderRegistration,
};
use latent_core::{BudgetDimension, PlatformError};

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
