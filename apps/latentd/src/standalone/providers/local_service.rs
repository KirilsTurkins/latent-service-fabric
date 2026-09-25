use latent_capabilities::broker::{
    ActivationCapabilityBroker, ProviderConfiguration, ProviderRegistration,
    LOCAL_SERVICE_INVOCATION_PROFILE, SERVICE_INVOCATION_CAPABILITY,
};
use latent_core::PlatformError;

pub(super) fn install(
    broker: &ActivationCapabilityBroker,
    config: &crate::config::LocalServiceInstallation,
) -> Result<ProviderRegistration, PlatformError> {
    let bytes = serde_json::to_vec(&(
        LOCAL_SERVICE_INVOCATION_PROFILE,
        &config.identity.tenant,
        &config.identity.service,
        &config.deployment,
        &config.contract,
    ))
    .map_err(|_| super::unavailable())?;
    let digest = latent_artifacts::package::artifact_blob_digest(&bytes);
    broker.register_provider(ProviderConfiguration {
        capability: SERVICE_INVOCATION_CAPABILITY,
        profile: LOCAL_SERVICE_INVOCATION_PROFILE,
        configuration_digest: digest.as_str(),
        configuration_epoch: config.identity.epoch,
        restriction_json: br#"{"operations":["call"]}"#,
        minimum_call_charges: &[],
    })
}
