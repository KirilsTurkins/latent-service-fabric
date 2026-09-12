use crate::BuilderTrustStateId;
use latent_artifacts::package::PackageSubject;
use latent_core::{ArtifactBlobDigest, PackageDigest};

/// Current, authenticated builder assertion about an exact package/component.
/// This is neither publisher approval nor tenant/catalog/native-code authority.
/// Persisted fields must be reverified, never deserialized into a trusted proof.
#[derive(Debug)]
pub struct VerifiedBuildProvenance {
    pub(super) subject: PackageSubject,
    pub(super) component_digest: ArtifactBlobDigest,
    pub(super) builder_id: String,
    pub(super) key_fingerprint: ArtifactBlobDigest,
    pub(super) evidence_digest: PackageDigest,
    pub(super) payload_digest: ArtifactBlobDigest,
    pub(super) source_repository: String,
    pub(super) source_revision: String,
    pub(super) source_snapshot_digest: ArtifactBlobDigest,
    pub(super) state: BuilderTrustStateId,
    pub(super) verified_at: u64,
    pub(super) valid_until: u64,
}

impl VerifiedBuildProvenance {
    #[must_use]
    pub fn subject(&self) -> &PackageSubject {
        &self.subject
    }
    #[must_use]
    pub fn component_digest(&self) -> &ArtifactBlobDigest {
        &self.component_digest
    }
    #[must_use]
    pub fn builder_id(&self) -> &str {
        &self.builder_id
    }
    #[must_use]
    pub fn key_fingerprint(&self) -> &ArtifactBlobDigest {
        &self.key_fingerprint
    }
    #[must_use]
    pub fn evidence_digest(&self) -> &PackageDigest {
        &self.evidence_digest
    }
    #[must_use]
    pub fn payload_digest(&self) -> &ArtifactBlobDigest {
        &self.payload_digest
    }
    #[must_use]
    pub fn source_repository(&self) -> &str {
        &self.source_repository
    }
    #[must_use]
    pub fn source_revision(&self) -> &str {
        &self.source_revision
    }
    #[must_use]
    pub fn source_snapshot_digest(&self) -> &ArtifactBlobDigest {
        &self.source_snapshot_digest
    }
    #[must_use]
    pub fn state_id(&self) -> &BuilderTrustStateId {
        &self.state
    }
    #[must_use]
    pub const fn verified_at(&self) -> u64 {
        self.verified_at
    }
    #[must_use]
    pub const fn valid_until(&self) -> u64 {
        self.valid_until
    }
}
