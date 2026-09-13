use latent_core::PlatformError;
use latent_policy::capability::PolicyStoreLimits;
use serde::Deserialize;

#[derive(Clone, Copy, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CapabilityPolicyConfig {
    pub format_version: u32,
    #[serde(default)]
    pub store: PolicyStoreLimits,
    #[serde(default = "default_jobs")]
    pub maximum_control_jobs: usize,
}
const fn default_jobs() -> usize {
    4
}
pub(super) fn present<'de, D: serde::Deserializer<'de>>(
    decoder: D,
) -> Result<Option<CapabilityPolicyConfig>, D::Error> {
    CapabilityPolicyConfig::deserialize(decoder).map(Some)
}
pub(super) fn derive(
    value: Option<CapabilityPolicyConfig>,
) -> Result<Option<CapabilityPolicyConfig>, PlatformError> {
    if let Some(value) = value {
        if value.format_version != 1 || !(1..=16).contains(&value.maximum_control_jobs) {
            return Err(super::invalid("capability-policies"));
        }
        value
            .store
            .validate()
            .map_err(|_| super::invalid("capability-policies"))?;
    }
    Ok(value)
}
pub(super) fn check_existing(settings: &super::NodeSettings) -> Result<(), PlatformError> {
    if settings.capability_policies.is_none() {
        match std::fs::symlink_metadata(settings.data_directory.join("capability-policies")) {
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
            _ => {
                return Err(PlatformError {
                    code: latent_core::PlatformErrorCode::PermissionDenied,
                    message: "capability-policy-owner-required".into(),
                    retryable: false,
                    details: Vec::new(),
                })
            }
        }
    }
    Ok(())
}
