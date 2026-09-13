use crate::TrustStateId;
use latent_artifacts::package::PackageSubject;
use latent_core::{ArtifactBlobDigest, PackageDigest, PublisherId};

/// Point-in-time package publisher proof, never a tenant or execution capability.
/// Only cryptographic verification constructs it. Persisted/displayed fields must
/// be reverified on adoption, not deserialized into authoritative instances.
#[derive(Debug)]
pub struct VerifiedPackageSignature {
    pub(super) subject: PackageSubject,
    pub(super) publisher: PublisherId,
    pub(super) key_fingerprint: ArtifactBlobDigest,
    pub(super) evidence_digest: PackageDigest,
    pub(super) payload_digest: ArtifactBlobDigest,
    pub(super) state: TrustStateId,
    pub(super) verified_at: u64,
    pub(super) valid_until: u64,
}

impl VerifiedPackageSignature {
    #[must_use]
    pub fn subject(&self) -> &PackageSubject {
        &self.subject
    }
    #[must_use]
    pub fn publisher(&self) -> &PublisherId {
        &self.publisher
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
    pub fn state_id(&self) -> &TrustStateId {
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
