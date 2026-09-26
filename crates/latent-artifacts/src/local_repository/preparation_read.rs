use latent_core::{PlatformError, ReleaseDigest};

use super::DirectoryArtifactRepository;
use crate::{ArtifactPreparationReadBounds, ArtifactPreparationReadLimits, CapsuleArtifact};

impl DirectoryArtifactRepository {
    pub(crate) fn preparation_read_bounds(
        &self,
        release: &ReleaseDigest,
    ) -> Result<ArtifactPreparationReadBounds, PlatformError> {
        self.selected_read_bounds(release, None)
    }

    pub(crate) fn repository_read_limits(&self) -> ArtifactPreparationReadLimits {
        ArtifactPreparationReadLimits {
            maximum_component_bytes: self.config.max_component_bytes,
            maximum_metadata_document_bytes: self.config.max_metadata_bytes,
            maximum_manifest_document_bytes: self.codec.limits().max_document_bytes,
        }
    }

    pub(crate) fn fetch_with_limits(
        &self,
        release: &ReleaseDigest,
        requested: ArtifactPreparationReadLimits,
    ) -> Result<CapsuleArtifact, PlatformError> {
        self.selected_fetch(release, None, requested)
    }
}
