//! Component identity verification without retaining component bytes.

use latent_core::{PlatformError, PlatformErrorCode, ReleaseDigest};
use latent_manifest::CapsuleManifest;

use crate::{content_digest, ArtifactDescriptor, CapsuleArtifact, ContractDescriptor};

/// Owned metadata whose component digest and size have been verified.
///
/// Construction from an artifact checks actual bytes; it does not replace a
/// consumer's manifest or contract-policy validation. Directory repositories
/// additionally validate persisted metadata, COMPLETE and directory association.
/// No component buffer is retained, and no public mutable access is exposed.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct VerifiedArtifactMetadata {
    descriptor: ArtifactDescriptor,
    manifest: CapsuleManifest,
    contracts: Vec<ContractDescriptor>,
    verified_digest: ReleaseDigest,
    web_execution_projection: bool,
    transaction_execution_profile: bool,
}

impl VerifiedArtifactMetadata {
    /// Checks component identity and length, then releases its owned byte buffer.
    /// Metadata digest spelling may differ in ASCII case, matching the generic
    /// compiler contract; `verified_digest()` is always canonical lowercase.
    pub fn from_artifact(artifact: CapsuleArtifact) -> Result<Self, PlatformError> {
        let actual = content_digest(&artifact.component_bytes);
        if !artifact
            .descriptor
            .release_digest
            .0
            .eq_ignore_ascii_case(&actual.0)
            || !artifact
                .manifest
                .component_digest
                .0
                .eq_ignore_ascii_case(&actual.0)
        {
            return Err(invalid("release-digest-mismatch"));
        }
        if artifact.descriptor.size_bytes != artifact.component_bytes.len() as u64 {
            return Err(invalid(
                "artifact descriptor size does not match component bytes",
            ));
        }
        let CapsuleArtifact {
            descriptor,
            manifest,
            contracts,
            component_bytes,
        } = artifact;
        drop(component_bytes);
        Ok(Self::from_verified_parts(
            descriptor, manifest, contracts, actual,
        ))
    }

    /// Only repository code that has already checked the streamed digest and
    /// length can construct without a component buffer.
    pub(crate) fn from_verified_parts(
        descriptor: ArtifactDescriptor,
        manifest: CapsuleManifest,
        contracts: Vec<ContractDescriptor>,
        verified_digest: ReleaseDigest,
    ) -> Self {
        Self {
            descriptor,
            manifest,
            contracts,
            verified_digest,
            web_execution_projection: false,
            transaction_execution_profile: false,
        }
    }

    pub(crate) fn with_web_execution_projection(mut self) -> Self {
        self.web_execution_projection = true;
        self
    }

    /// Set only after the repository verifies the original admitted package's
    /// exact, digest-bound transaction companion and capsule association.
    pub(crate) fn with_transaction_execution_profile(mut self, selected: bool) -> Self {
        self.transaction_execution_profile = selected;
        self
    }

    /// Immutable structural profile provenance. Runtime ABI, current admission,
    /// namespace authority and an attached transaction are checked separately.
    #[must_use]
    pub const fn is_transaction_execution_profile(&self) -> bool {
        self.transaction_execution_profile
    }

    pub fn validate_deployment(
        &self,
        deployment: &latent_manifest::DeploymentManifest,
    ) -> Result<(), Vec<latent_manifest::ManifestViolation>> {
        use latent_manifest::{
            ManifestValidator, Phase1ManifestValidator, Phase4TransactionManifestValidator,
        };
        if self.transaction_execution_profile {
            Phase4TransactionManifestValidator
                .validate_deployment_against_capsule(deployment, &self.manifest)
        } else if self.web_execution_projection {
            Phase1ManifestValidator.validate_web_execution_projection(deployment, &self.manifest)
        } else {
            Phase1ManifestValidator.validate_deployment_against_capsule(deployment, &self.manifest)
        }
    }

    #[must_use]
    pub const fn is_web_execution_projection(&self) -> bool {
        self.web_execution_projection
    }

    #[must_use]
    pub fn descriptor(&self) -> &ArtifactDescriptor {
        &self.descriptor
    }

    #[must_use]
    pub fn manifest(&self) -> &CapsuleManifest {
        &self.manifest
    }

    #[must_use]
    pub fn contracts(&self) -> &[ContractDescriptor] {
        &self.contracts
    }

    #[must_use]
    pub fn verified_digest(&self) -> &ReleaseDigest {
        &self.verified_digest
    }

    pub(crate) fn verify_requested(&self, requested: &ReleaseDigest) -> Result<(), PlatformError> {
        if self.verified_digest != *requested {
            return Err(invalid("release-digest-mismatch"));
        }
        Ok(())
    }

    pub(crate) fn into_parts(
        self,
    ) -> (ArtifactDescriptor, CapsuleManifest, Vec<ContractDescriptor>) {
        (self.descriptor, self.manifest, self.contracts)
    }
}

fn invalid(message: &str) -> PlatformError {
    PlatformError {
        code: PlatformErrorCode::CorruptArtifact,
        message: message.to_owned(),
        retryable: false,
        details: Vec::new(),
    }
}
