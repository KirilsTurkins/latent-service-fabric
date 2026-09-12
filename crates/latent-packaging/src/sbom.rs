//! One bounded, pre-package `CycloneDX` inventory. It describes content, not trust.
pub(crate) mod embedded;
mod evidence;
mod json;
mod model;
mod policy;
mod profile;
mod validation;

pub use embedded::{CheckedPackageSbom, SbomRoleCounts, SBOM_PATH};
pub use evidence::{
    attach_package_sbom, inspect_sbom_association, CheckedSbomAssociation, SbomEvidence,
    SbomEvidenceLimits, SbomEvidenceRef,
};
pub use model::{
    SbomDependencyCompleteness, SbomDigestScope, SbomEntryKind, SbomEntryOrigin, SbomInventory,
    SbomInventoryEntry,
};
pub use policy::{
    evaluate_sboms, SbomPolicy, SbomPolicyConfig, SbomPolicyEvaluation, SbomPresence,
};

use crate::{LayerInput, PackageBundle, PackageInput, PackagingLimits};
use latent_artifacts::package::{artifact_blob_digest, LayerRole};
use latent_core::{ArtifactBlobDigest, PlatformError};

pub const CYCLONEDX_JSON_MEDIA_TYPE: &str = "application/vnd.cyclonedx+json";
pub const CYCLONEDX_SPEC_VERSION: &str = "1.6";

#[derive(Debug, Clone, Copy)]
pub struct SbomLimits {
    pub max_document_bytes: usize,
    pub max_entries: usize,
    pub max_string_bytes: usize,
}
impl Default for SbomLimits {
    fn default() -> Self {
        Self {
            max_document_bytes: 1_048_576,
            max_entries: 4096,
            max_string_bytes: 4096,
        }
    }
}
impl SbomLimits {
    pub(crate) fn validate(self) -> Result<(), PlatformError> {
        if self.max_document_bytes == 0
            || self.max_document_bytes > 1_048_576
            || self.max_entries == 0
            || self.max_entries > 4096
            || self.max_string_bytes == 0
            || self.max_string_bytes > 4096
        {
            return Err(crate::invalid("invalid-sbom-limits"));
        }
        Ok(())
    }
}

pub struct SbomDocument {
    digest: ArtifactBlobDigest,
    bytes: Box<[u8]>,
}
impl std::fmt::Debug for SbomDocument {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("SbomDocument")
            .field("digest", &self.digest)
            .field("bytes", &self.bytes.len())
            .finish()
    }
}
impl SbomDocument {
    #[must_use]
    pub fn bytes(&self) -> &[u8] {
        &self.bytes
    }
    #[must_use]
    pub fn digest(&self) -> &ArtifactBlobDigest {
        &self.digest
    }
    #[must_use]
    pub const fn media_type(&self) -> &'static str {
        CYCLONEDX_JSON_MEDIA_TYPE
    }
}

/// A validated inventory, with the identity of the original received bytes.
pub struct SbomInspection {
    digest: ArtifactBlobDigest,
    inventory: SbomInventory,
}
impl std::fmt::Debug for SbomInspection {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("SbomInspection")
            .field("digest", &self.digest)
            .field("entries", &self.inventory.entries.len())
            .finish()
    }
}
impl SbomInspection {
    #[must_use]
    pub fn digest(&self) -> &ArtifactBlobDigest {
        &self.digest
    }
    #[must_use]
    pub fn inventory(&self) -> &SbomInventory {
        &self.inventory
    }
}

pub fn decode_sbom_inventory(
    bytes: &[u8],
    limits: SbomLimits,
) -> Result<SbomInventory, PlatformError> {
    let inventory = json::decode(bytes, limits)?;
    validation::inventory(&inventory, limits)?;
    Ok(inventory)
}

pub fn generate_cyclonedx_sbom(
    mut inventory: SbomInventory,
    limits: SbomLimits,
) -> Result<SbomDocument, PlatformError> {
    // Validate all lengths and aggregate serialization before comparison/sorting.
    validation::inventory(&inventory, limits)?;
    inventory.entries.sort();
    let document = profile::encode(&inventory)?;
    let bytes = json::encode(&document, limits.max_document_bytes)?;
    // The generated and received paths enforce the same complete profile.
    inspect_cyclonedx_sbom(CYCLONEDX_JSON_MEDIA_TYPE, &bytes, limits)?;
    Ok(SbomDocument {
        digest: artifact_blob_digest(&bytes),
        bytes: bytes.into_boxed_slice(),
    })
}

pub fn inspect_cyclonedx_sbom(
    media_type: &str,
    bytes: &[u8],
    limits: SbomLimits,
) -> Result<SbomInspection, PlatformError> {
    if media_type != CYCLONEDX_JSON_MEDIA_TYPE {
        return Err(crate::invalid("unsupported-sbom-media-type"));
    }
    let document = json::decode(bytes, limits)?;
    let inventory = profile::decode(document)?;
    validation::inventory(&inventory, limits)?;
    Ok(SbomInspection {
        digest: artifact_blob_digest(bytes),
        inventory,
    })
}

/// Generates the reserved layer before immutable package identity is computed.
pub fn build_package_with_sbom(
    mut input: PackageInput,
    inventory: SbomInventory,
    limits: PackagingLimits,
) -> Result<PackageBundle, PlatformError> {
    crate::assembly::validate_inputs(&input, limits)?;
    if input.layers.iter().any(|layer| layer.path == SBOM_PATH) {
        return Err(crate::invalid("reserved-sbom-path"));
    }
    let document = generate_cyclonedx_sbom(inventory, limits.sbom)?;
    input.layers.push(LayerInput {
        path: SBOM_PATH.to_owned(),
        role: LayerRole::Asset,
        media_type: CYCLONEDX_JSON_MEDIA_TYPE.to_owned(),
        bytes: document.bytes.into_vec(),
    });
    crate::build_package(input, limits)
}

#[cfg(test)]
mod tests;
