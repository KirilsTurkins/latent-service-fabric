use std::sync::Arc;

use latent_core::{PlatformError, ReleaseDigest};

use crate::ArtifactRepository;
use crate::{ArtifactPreparationIdentity, CapsuleArtifact, DirectoryArtifactRepository};

/// Fixed-size read admission facts from an immutable, admitted catalog entry.
/// Document ceilings bound encoded input, not decoder or compiler heap usage.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ArtifactPreparationReadBounds {
    pub component_bytes: u64,
    pub maximum_metadata_document_bytes: usize,
    pub maximum_manifest_document_bytes: usize,
}

/// Caller-reserved read ceilings, intersected with the source's own limits.
/// These values confer no preparation identity or repository authority.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ArtifactPreparationReadLimits {
    pub maximum_component_bytes: usize,
    pub maximum_metadata_document_bytes: usize,
    pub maximum_manifest_document_bytes: usize,
}

/// Preparation authority retaining exactly one concrete directory owner.
///
/// A compiler job retains this source until its actual reads and compilation
/// finish, even if its last caller disappears. Cache entries and ready results
/// should retain the fixed epoch identity instead, so they do not keep the
/// repository's ownership lock alive. Cloning only clones the owner's `Arc`.
#[derive(Clone)]
pub struct OwnedArtifactPreparationSource {
    repository: Arc<DirectoryArtifactRepository>,
}

impl OwnedArtifactPreparationSource {
    pub(crate) fn new(repository: Arc<DirectoryArtifactRepository>) -> Self {
        Self { repository }
    }

    pub fn eligibility(
        &self,
        release: &ReleaseDigest,
    ) -> Result<Option<crate::ReleaseEligibility>, PlatformError> {
        self.repository.release_eligibility(release)
    }

    pub fn execution_eligibility(
        &self,
        release: &ReleaseDigest,
    ) -> Result<Option<crate::ReleaseUseEligibility>, PlatformError> {
        self.repository.execution_eligibility(release)
    }

    /// Returns an admitted immutable identity without disk I/O or metadata
    /// traversal. `None` requires this same source's fully checked fetch.
    pub fn identity(
        &self,
        release: &ReleaseDigest,
    ) -> Result<Option<ArtifactPreparationIdentity>, PlatformError> {
        self.repository.preparation_identity(release)
    }

    /// Copies bounded admission facts without cloning a descriptor or reading
    /// files. Missing and not-yet-admitted releases return `NotFound`.
    pub fn read_bounds(
        &self,
        release: &ReleaseDigest,
    ) -> Result<ArtifactPreparationReadBounds, PlatformError> {
        self.repository.preparation_read_bounds(release)
    }

    /// Performs fresh synchronous disk verification through the issuing owner.
    /// Run this on a bounded blocking worker, never an asynchronous executor.
    /// Reserve the indexed component size and document allowances first; the
    /// component ceiling should be the exact indexed size that was reserved.
    /// File growth is checked before bytes extend their retained buffer.
    pub fn fetch_blocking(
        &self,
        release: &ReleaseDigest,
        limits: ArtifactPreparationReadLimits,
    ) -> Result<CapsuleArtifact, PlatformError> {
        self.repository.fetch_with_limits(release, limits)
    }
}
