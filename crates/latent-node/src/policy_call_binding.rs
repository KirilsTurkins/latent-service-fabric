//! Descriptive constraints shared by installed runtime and management bindings.

use latent_policy::capability::GrantRestriction;

/// Descriptive installed binding constraints. This data grants no authority:
/// the real policy owner must seal the exact profile, configuration, revision
/// and operation before execution or result publication.
pub struct PolicyCallBinding {
    pub policies: Vec<String>,
    pub binding: String,
    pub profile: String,
    pub configuration_digest: String,
    pub configuration_epoch: u64,
    pub operations: Vec<String>,
    pub deployment: GrantRestriction,
    pub provider_configuration: GrantRestriction,
}
