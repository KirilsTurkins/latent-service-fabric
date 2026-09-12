use crate::aot::AotCompatibilityKey;
use latent_artifacts::LifecycleScope;
use serde::Deserialize;

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(super) struct Receipt {
    pub(super) format_version: u32,
    pub(super) compatibility: WireKey,
    pub(super) output_digest: String,
    pub(super) output_size: u64,
    pub(super) compiler_identity: String,
    pub(super) seal: [u8; 32],
}

/// A closed private wire view. It never constructs the public provenance key.
#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(super) struct WireKey {
    scope: LifecycleScope,
    #[serde(default, deserialize_with = "present")]
    package: Option<String>,
    component: String,
    component_bytes: u64,
    metadata_digest: [u8; 32],
    engine_profile_digest: String,
    engine_compatibility: [u8; 32],
    capability_contract_digest: String,
    security_policy_digest: String,
    compiler_digest: [u8; 32],
    sandbox_digest: [u8; 32],
}
impl WireKey {
    pub(super) fn matches(&self, expected: &AotCompatibilityKey) -> bool {
        self.scope == *expected.scope()
            && self.package.as_deref() == expected.package().map(latent_core::PackageDigest::as_str)
            && self.component == expected.component().as_str()
            && self.component_bytes == expected.component_bytes()
            && self.metadata_digest == *expected.metadata_digest()
            && self.engine_profile_digest == expected.engine_profile_digest().as_str()
            && self.engine_compatibility == *expected.engine_compatibility()
            && self.capability_contract_digest == expected.capability_contract_digest().as_str()
            && self.security_policy_digest == expected.security_policy_digest().as_str()
            && self.compiler_digest == *expected.compiler_digest()
            && self.sandbox_digest == *expected.sandbox_digest()
    }
}
fn present<'de, D: serde::Deserializer<'de>>(deserializer: D) -> Result<Option<String>, D::Error> {
    String::deserialize(deserializer).map(Some)
}
