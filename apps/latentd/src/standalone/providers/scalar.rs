//! Configuration identities for actual Wasmtime context, log and clock imports.
//! Registrations are node-fixed; calls remain charged to the activation broker.
use latent_capabilities::broker::{
    ActivationCapabilityBroker, ProviderBudgetRequirement, ProviderConfiguration,
    ProviderRegistration,
};
use latent_core::{BudgetDimension, PlatformError};

/// Authorizes the existing bounded host implementation through ordinary exact
/// bindings and grants. It creates no context, sink, process or worker; the
/// invocation Store still owns its original context and activation accounting.
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
