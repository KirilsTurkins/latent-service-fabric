use serde::{Deserialize, Serialize};

#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct BuilderKeyConfig {
    pub builder_id: String,
    /// Canonical standard padded base64 of a raw Ed25519 public key.
    pub public_key: String,
    pub valid_from: u64,
    pub valid_until: u64,
}

/// One explicit allowed build/source combination. Any matching requirement allows the build.
#[derive(Debug, Serialize, Deserialize, PartialEq, Eq, PartialOrd, Ord)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct BuilderRequirement {
    pub builder_id: String,
    pub build_type: String,
    pub source_repository: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub source_revision: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub source_snapshot_digest: Option<String>,
    pub require_reproducible: bool,
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct BuilderPolicyConfig {
    pub format_version: u32,
    pub scope: String,
    pub generation: u64,
    pub valid_from: u64,
    pub valid_until: u64,
    pub max_signature_lifetime_seconds: u64,
    pub max_proof_age_seconds: u64,
    /// Empty keys or requirements explicitly deny every build.
    pub keys: Vec<BuilderKeyConfig>,
    pub requirements: Vec<BuilderRequirement>,
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct BuilderRevocationSnapshotConfig {
    pub format_version: u32,
    pub scope: String,
    /// Binds all builder anchors and source requirements.
    pub policy_digest: String,
    pub generation: u64,
    pub valid_from: u64,
    pub valid_until: u64,
    pub revoked_keys: Vec<String>,
    pub revoked_builders: Vec<String>,
}
