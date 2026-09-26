//! Register authority for the production context, log and clock implementations.
use super::{Binding, Call, DevelopmentTestArtifact, PolicyStore};
use latent_capabilities::broker::{
    ActivationCapabilityBroker, ProviderConfiguration, ProviderRegistration,
};
use latent_wasmtime::{CONTEXT_IMPORT, LOG_IMPORT, MONOTONIC_CLOCK_IMPORT, WALL_CLOCK_IMPORT};
use serde_json::json;

pub(super) fn install(
    broker: &ActivationCapabilityBroker,
    policies: &PolicyStore,
    artifact: &DevelopmentTestArtifact,
    calls: &[Call],
) -> Result<(Vec<Binding>, Vec<ProviderRegistration>), &'static str> {
    let declarations: &[(&str, &str, &[&str], serde_json::Value)] = &[
        (
            "context",
            CONTEXT_IMPORT,
            &[
                "activation-id",
                "root-activation-id",
                "parent-activation-id",
                "principal",
                "trace",
                "deadline-unix-millis",
                "remaining-budget",
                "metadata",
            ],
            json!({"kind":"context"}),
        ),
        (
            "log",
            LOG_IMPORT,
            &["write"],
            json!({"kind":"log","levels":["trace","debug","info","warn","error"]}),
        ),
        (
            "monotonic",
            MONOTONIC_CLOCK_IMPORT,
            &["now-nanos"],
            json!({"kind":"clock"}),
        ),
        (
            "wall",
            WALL_CLOCK_IMPORT,
            &["now-unix-millis"],
            json!({"kind":"clock"}),
        ),
    ];
    let mut bindings = Vec::new();
    let mut owners = Vec::new();
    for (name, capability, operations, resources) in declarations {
        let identity = latent_artifacts::content_digest(capability.as_bytes());
        let owner = broker
            .register_provider(ProviderConfiguration {
                capability,
                profile: "portable-production-builtin-v1",
                configuration_digest: &identity.0,
                configuration_epoch: 1,
                restriction_json: br#"{"operations":[]}"#,
                minimum_call_charges: &[],
            })
            .map_err(|_| "portable-builtin-registration")?;
        bindings.push(super::install(
            policies,
            artifact,
            calls,
            name,
            capability,
            owner.reference(),
            operations,
            resources,
        )?);
        owners.push(owner);
    }
    Ok((bindings, owners))
}
