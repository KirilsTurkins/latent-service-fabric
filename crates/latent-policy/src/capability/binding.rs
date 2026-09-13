use super::{identifier, invalid, GrantRestriction};
use latent_core::{ArtifactBlobDigest, PlatformError};
use serde::{Deserialize, Serialize};

/// Tenant-owned provider selection metadata. A digest and epoch identify an
/// independently installed provider configuration; this document contains no
/// credentials and cannot create a provider or authorize an arbitrary endpoint.
#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Document {
    format_version: u32,
    tenant: String,
    capability: String,
    provider_profile: String,
    configuration_digest: String,
    configuration_epoch: u64,
    restriction: GrantRestriction,
}

#[derive(Debug)]
pub struct ProviderBinding {
    document: Document,
    canonical: Box<[u8]>,
    digest: String,
}
impl ProviderBinding {
    pub fn parse(bytes: &[u8]) -> Result<Self, PlatformError> {
        super::preflight(bytes)?;
        let document: Document = serde_json::from_slice(bytes).map_err(|_| invalid())?;
        if document.format_version != 1
            || !identifier(&document.tenant)
            || !identifier(&document.provider_profile)
            || document.configuration_epoch == 0
            || document.configuration_digest.len() != 71
            || document
                .configuration_digest
                .parse::<ArtifactBlobDigest>()
                .is_err()
        {
            return Err(invalid());
        }
        document.restriction.validate(&document.capability)?;
        let canonical = serde_json::to_vec(&document).map_err(|_| invalid())?;
        if canonical.len() > super::MAX_DOCUMENT_BYTES {
            return Err(invalid());
        }
        let digest = latent_artifacts::package::artifact_blob_digest(&canonical).to_string();
        Ok(Self {
            document,
            canonical: canonical.into_boxed_slice(),
            digest,
        })
    }
    #[must_use]
    pub fn tenant(&self) -> &str {
        &self.document.tenant
    }
    #[must_use]
    pub fn capability(&self) -> &str {
        &self.document.capability
    }
    #[must_use]
    pub fn provider_profile(&self) -> &str {
        &self.document.provider_profile
    }
    #[must_use]
    pub fn configuration_digest(&self) -> &str {
        &self.document.configuration_digest
    }
    #[must_use]
    pub fn configuration_epoch(&self) -> u64 {
        self.document.configuration_epoch
    }
    #[must_use]
    pub fn canonical(&self) -> &[u8] {
        &self.canonical
    }
    #[must_use]
    pub fn digest(&self) -> &str {
        &self.digest
    }
    pub(super) fn restriction(&self) -> &GrantRestriction {
        &self.document.restriction
    }
}
