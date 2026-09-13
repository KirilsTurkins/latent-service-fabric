mod evaluate;
pub use evaluate::{evaluate_sboms, SbomPolicyEvaluation};

use latent_artifacts::package::{artifact_blob_digest, validate_package_json, PackageLimits};
use latent_core::{ArtifactBlobDigest, PlatformError};
use serde::{Deserialize, Serialize};

use super::SbomEntryKind;

const MAX_POLICY_BYTES: usize = 4096;
const MAX_ROLES: usize = 9;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum SbomPresence {
    Optional,
    Required,
}

/// Source/license requirements apply to existing rows of the selected roles.
/// Optional presence permits an absent inventory; it does not prove absence from
/// a registry or imply that an available inventory has complete attribution.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SbomPolicyConfig {
    pub format_version: u32,
    pub embedded: SbomPresence,
    pub detached: SbomPresence,
    pub require_source: Vec<SbomEntryKind>,
    pub require_license: Vec<SbomEntryKind>,
}

/// Canonical bounded content policy. No mutable trust epoch, publisher approval,
/// freshness assertion, or catalog admission is established by this policy.
#[derive(Debug)]
pub struct SbomPolicy {
    config: SbomPolicyConfig,
    canonical: Box<[u8]>,
    digest: ArtifactBlobDigest,
}

impl SbomPolicy {
    pub fn new(mut config: SbomPolicyConfig) -> Result<Self, PlatformError> {
        if config.format_version != 1 {
            return Err(crate::invalid("unsupported-sbom-policy-version"));
        }
        if config.require_source.len() > MAX_ROLES || config.require_license.len() > MAX_ROLES {
            return Err(crate::exceeded("sbom-policy-role-limit"));
        }
        for roles in [&mut config.require_source, &mut config.require_license] {
            roles.sort_unstable();
            if roles.windows(2).any(|pair| pair[0] == pair[1]) {
                return Err(crate::invalid("duplicate-sbom-policy-role"));
            }
        }
        let canonical = super::json::encode(&config, MAX_POLICY_BYTES)?;
        // Discard potentially oversized caller spare capacity before retaining
        // the checked config. The canonical JSON also obeys the same shape caps.
        drop(config);
        let config = decode(&canonical)?;
        Ok(Self {
            config,
            digest: artifact_blob_digest(&canonical),
            canonical: canonical.into_boxed_slice(),
        })
    }

    pub fn from_json(bytes: &[u8]) -> Result<Self, PlatformError> {
        Self::new(decode(bytes)?)
    }

    #[must_use]
    pub fn config(&self) -> &SbomPolicyConfig {
        &self.config
    }
    #[must_use]
    pub fn digest(&self) -> &ArtifactBlobDigest {
        &self.digest
    }
    #[must_use]
    pub fn canonical_bytes(&self) -> &[u8] {
        &self.canonical
    }
}

fn decode(bytes: &[u8]) -> Result<SbomPolicyConfig, PlatformError> {
    validate_package_json(
        bytes,
        PackageLimits {
            max_document_bytes: MAX_POLICY_BYTES,
            max_depth: 4,
            max_nodes: 64,
            max_string_bytes: 32,
            max_layers: MAX_ROLES,
            max_annotations: 6,
            ..PackageLimits::default()
        },
    )?;
    serde_json::from_slice(bytes).map_err(|_| crate::invalid("invalid-sbom-policy-json"))
}
