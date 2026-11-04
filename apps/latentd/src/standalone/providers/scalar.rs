//! Configuration identities for actual Wasmtime context, log and clock imports.
//! Registrations are node-fixed; calls remain charged to the activation broker.
use latent_capabilities::broker::{
    ActivationCapabilityBroker, ProviderBudgetRequirement, ProviderConfiguration,
    ProviderRegistration,
};
use latent_core::{BudgetDimension, PlatformError};

pub(super) fn core(
    broker: &ActivationCapabilityBroker,
    epoch: u64,
    logging: bool,
) -> Result<ProviderRegistration, PlatformError> {
    let (capability, profile, restriction, identity) = if logging {
        (
            "latent:log/log@0.1.0",
            "activation-log-v1",
            br#"{"operations":["write"]}"#.as_slice(),
            b"latent-activation-log-v1:original-ledger:message256:fields16:name64:value256:bounded-node-sink".as_slice(),
        )
    } else {
        (
            "latent:context/context@0.1.0",
            "activation-context-v1",
            br#"{"operations":["activation-id","root-activation-id","parent-activation-id","principal","trace","deadline-unix-millis","remaining-budget","metadata"]}"#.as_slice(),
            b"latent-activation-context-v1:original-invocation:host-preflight:context-policy:bounded-canonical-lowering".as_slice(),
        )
    };
    let digest = latent_artifacts::package::artifact_blob_digest(identity);
    broker.register_provider(ProviderConfiguration {
        capability,
        profile,
        configuration_digest: digest.as_str(),
        configuration_epoch: epoch,
        restriction_json: restriction,
        minimum_call_charges: &[],
    })
}

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

pub(super) fn native_threads(
    broker: &ActivationCapabilityBroker,
    installation: &crate::config::ActivationRuntimeInstallation,
) -> Result<ProviderRegistration, PlatformError> {
    let digest = installation.native_configuration_digest()?;
    broker.register_provider(ProviderConfiguration {
        capability: "latent:runtime-native/threads@0.1.0",
        profile: "conservative-native-total-starts-v1",
        configuration_digest: digest.as_str(),
        configuration_epoch: installation.identity.epoch,
        restriction_json: br#"{"operations":["start"]}"#,
        minimum_call_charges: &[ProviderBudgetRequirement {
            operation: "start",
            dimension: BudgetDimension::CpuFuel,
            minimum: 100,
        }],
    })
}

pub(super) fn clock(
    broker: &ActivationCapabilityBroker,
    epoch: u64,
    monotonic: bool,
) -> Result<ProviderRegistration, PlatformError> {
    latent_capabilities::broker::scalar_configuration::register_clock(broker, epoch, monotonic)
}
