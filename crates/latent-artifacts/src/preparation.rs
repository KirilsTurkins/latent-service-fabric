//! Sealed preparation provenance bound to one concrete repository owner.

use std::hash::{Hash, Hasher};
use std::mem::size_of_val;
use std::sync::Arc;

use latent_core::{BoxFuture, PlatformError, PlatformErrorCode, ReleaseDigest};
use sha2::{Digest, Sha256};

use crate::{
    preparation_metadata_fingerprint, ArtifactRepository, CapsuleArtifact,
    DirectoryArtifactRepository, PreparationMetadataFingerprint, VerifiedArtifactMetadata,
};

/// Conservative one-allocation charge for the epoch's `Arc` control block.
pub(crate) const EPOCH_RETAINED_BYTES: usize = 64;
/// Eligibility limit for this optional optimization, not a publication limit.
pub(crate) const MAXIMUM_STAMP_BYTES: usize = 16 * 1024 * 1024;

#[derive(Debug)]
pub(crate) struct RepositoryEpoch;

/// A borrowed preparation capability. Both operations use the same directory
/// owner, even when an outer repository adapter delegates to this capability.
/// Never combine its identity with that adapter's separate `fetch` operation.
#[derive(Clone, Copy)]
pub struct ArtifactPreparationSource<'repo> {
    repository: &'repo DirectoryArtifactRepository,
}

impl<'repo> ArtifactPreparationSource<'repo> {
    pub(crate) fn new(repository: &'repo DirectoryArtifactRepository) -> Self {
        Self { repository }
    }

    /// Looks up an immutable admitted snapshot without file I/O or metadata
    /// traversal. Missing entries are `NotFound`; `None` means use this source's
    /// fully checked fetch because its metadata is not eligible for a stamp.
    pub fn identity(
        &self,
        release: &ReleaseDigest,
    ) -> Result<Option<ArtifactPreparationIdentity>, PlatformError> {
        self.repository.preparation_identity(release)
    }

    /// Fresh disk verification through exactly the owner that issues identities.
    pub fn fetch<'a>(
        &'a self,
        release: &'a ReleaseDigest,
    ) -> BoxFuture<'a, Result<CapsuleArtifact, PlatformError>> {
        self.repository.fetch(release)
    }
}

/// A fixed-size identity of a verified repository snapshot. It authorizes reuse
/// only when acquired through the matching sealed preparation source. It is not
/// a principal, a live disk audit, or an unchecked caller preparation request.
#[derive(Debug, Clone)]
pub struct ArtifactPreparationIdentity {
    epoch: Arc<RepositoryEpoch>,
    component_digest: [u8; 32],
    component_bytes: u64,
    metadata: PreparationMetadataFingerprint,
}

impl PartialEq for ArtifactPreparationIdentity {
    fn eq(&self, other: &Self) -> bool {
        Arc::ptr_eq(&self.epoch, &other.epoch)
            && self.component_digest == other.component_digest
            && self.component_bytes == other.component_bytes
            && self.metadata == other.metadata
    }
}
impl Eq for ArtifactPreparationIdentity {}

impl Hash for ArtifactPreparationIdentity {
    fn hash<H: Hasher>(&self, state: &mut H) {
        std::ptr::hash(Arc::as_ptr(&self.epoch), state);
        self.component_digest.hash(state);
        self.component_bytes.hash(state);
        self.metadata.hash(state);
    }
}

impl ArtifactPreparationIdentity {
    pub(crate) fn new(
        epoch: Arc<RepositoryEpoch>,
        release: &ReleaseDigest,
        component_bytes: u64,
        metadata: PreparationMetadataFingerprint,
    ) -> Result<Self, PlatformError> {
        Ok(Self {
            epoch,
            component_digest: digest_bytes(release).ok_or_else(mismatch)?,
            component_bytes,
            metadata,
        })
    }

    #[must_use]
    pub fn metadata(&self) -> &PreparationMetadataFingerprint {
        &self.metadata
    }
    #[must_use]
    pub fn component_digest(&self) -> &[u8; 32] {
        &self.component_digest
    }
    #[must_use]
    pub fn component_bytes(&self) -> u64 {
        self.component_bytes
    }

    /// Canonical lowercase release association, without allocating a string.
    #[must_use]
    pub fn matches_release(&self, release: &ReleaseDigest) -> bool {
        digest_bytes(release).as_ref() == Some(&self.component_digest)
    }

    /// Compares fresh metadata with this snapshot. This checks declared/owned
    /// length but deliberately does not rehash component bytes; source fetch and
    /// the execution backend retain responsibility for component verification.
    pub fn verify_metadata(
        &self,
        artifact: &CapsuleArtifact,
        maximum_bytes: usize,
        maximum_depth: usize,
    ) -> Result<(), PlatformError> {
        if !self.matches_release(&artifact.descriptor.release_digest)
            || !self.matches_release(&artifact.manifest.component_digest)
            || self.component_bytes != artifact.descriptor.size_bytes
            || self.component_bytes != artifact.component_bytes.len() as u64
        {
            return Err(mismatch());
        }
        let actual = preparation_metadata_fingerprint(
            &artifact.descriptor,
            &artifact.manifest,
            &artifact.contracts,
            maximum_bytes,
            maximum_depth,
        )?;
        if actual != self.metadata {
            return Err(mismatch());
        }
        Ok(())
    }

    /// Fixed-input, process-local lookup digest. Callers must still compare the
    /// exact token on a hit. Keeping the epoch alive prevents pointer recycling.
    #[must_use]
    pub fn cache_digest(&self) -> [u8; 32] {
        let mut hash = Sha256::new();
        hash.update(b"lsf-artifact-preparation-source-v1\0");
        hash.update((Arc::as_ptr(&self.epoch) as usize).to_le_bytes());
        hash.update(self.component_digest);
        hash.update(self.component_bytes.to_le_bytes());
        hash.update(self.metadata.digest());
        hash.update(self.metadata.charged_bytes().to_le_bytes());
        hash.update(self.metadata.required_type_depth().to_le_bytes());
        hash.finalize().into()
    }

    /// Conservative per-retained-token charge, including shared epoch storage.
    #[must_use]
    pub fn retained_bytes(&self) -> usize {
        size_of_val(self) + EPOCH_RETAINED_BYTES
    }
}

pub(crate) fn repository_stamp(
    metadata: &VerifiedArtifactMetadata,
    maximum_bytes: usize,
) -> Option<PreparationMetadataFingerprint> {
    // The storage decoder already bounds type depth to 32 and total nodes.
    // Exceeding the independent optimization allowance only disables the stamp.
    preparation_metadata_fingerprint(
        metadata.descriptor(),
        metadata.manifest(),
        metadata.contracts(),
        maximum_bytes,
        32,
    )
    .ok()
}

fn digest_bytes(value: &ReleaseDigest) -> Option<[u8; 32]> {
    let hex = value.0.strip_prefix("sha256:")?;
    if hex.len() != 64 {
        return None;
    }
    fn nibble(value: u8) -> Option<u8> {
        match value {
            b'0'..=b'9' => Some(value - b'0'),
            b'a'..=b'f' => Some(value - b'a' + 10),
            _ => None,
        }
    }
    let mut digest = [0; 32];
    for (output, pair) in digest.iter_mut().zip(hex.as_bytes().chunks_exact(2)) {
        *output = nibble(pair[0])? * 16 + nibble(pair[1])?;
    }
    Some(digest)
}

fn mismatch() -> PlatformError {
    PlatformError {
        code: PlatformErrorCode::CorruptArtifact,
        message: "artifact preparation identity does not match verified metadata".to_owned(),
        retryable: false,
        details: Vec::new(),
    }
}
