use serde::{Deserialize, Serialize};

#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PublisherKeyConfig {
    pub publisher_id: String,
    /// Canonical standard padded base64 encoding of a raw 32-byte public key.
    pub public_key: String,
    pub valid_from: u64,
    pub valid_until: u64,
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PublisherPolicyConfig {
    pub format_version: u32,
    pub scope: String,
    pub generation: u64,
    pub valid_from: u64,
    pub valid_until: u64,
    pub max_signature_lifetime_seconds: u64,
    pub max_proof_age_seconds: u64,
    /// An empty list explicitly denies every publisher.
    pub keys: Vec<PublisherKeyConfig>,
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RevocationSnapshotConfig {
    pub format_version: u32,
    pub scope: String,
    /// Exact canonical policy digest; changing policy requires a new snapshot.
    pub policy_digest: String,
    pub generation: u64,
    pub valid_from: u64,
    pub valid_until: u64,
    pub revoked_keys: Vec<String>,
    pub revoked_publishers: Vec<String>,
}
