use crate::BuilderTrustStateId;
use latent_artifacts::package::PackageSubject;
use latent_core::{ArtifactBlobDigest, PackageDigest};

/// Authenticated, finite-lived builder assertion about exact web package outputs.
/// There is no component identity for browser-only packages. This proof alone
/// grants neither tenant admission nor renderer/asset access.
#[derive(Debug)]
pub struct VerifiedWebBuildProvenance {
    pub(super) subject: PackageSubject,
    pub(super) outputs_digest: ArtifactBlobDigest,
    pub(super) outputs_count: usize,
    pub(super) outputs_bytes: u64,
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

impl VerifiedWebBuildProvenance {
    #[must_use]
    pub fn subject(&self) -> &PackageSubject {
        &self.subject
    }
    #[must_use]
    pub fn outputs_digest(&self) -> &ArtifactBlobDigest {
        &self.outputs_digest
    }
    #[must_use]
    pub const fn outputs_count(&self) -> usize {
        self.outputs_count
    }
    #[must_use]
    pub const fn outputs_bytes(&self) -> u64 {
        self.outputs_bytes
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
