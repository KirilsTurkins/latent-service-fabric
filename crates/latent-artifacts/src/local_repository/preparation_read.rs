use latent_core::{PlatformError, PlatformErrorCode, ReleaseDigest};

use super::{add, error, lock_error, resource_exhausted, DirectoryArtifactRepository, Retention};
use crate::{ArtifactPreparationReadBounds, ArtifactPreparationReadLimits, CapsuleArtifact};

impl DirectoryArtifactRepository {
    pub(crate) fn preparation_read_bounds(
        &self,
        release: &ReleaseDigest,
    ) -> Result<ArtifactPreparationReadBounds, PlatformError> {
        self.current_eligibility(release)?;
        let index = self.index.read().map_err(lock_error)?;
        let entry = index
            .by_digest
            .get(release)
            .ok_or_else(|| error(PlatformErrorCode::NotFound, "release digest not found"))?;
        Ok(ArtifactPreparationReadBounds {
            component_bytes: entry.value.descriptor.size_bytes,
            maximum_metadata_document_bytes: self.config.max_metadata_bytes,
            maximum_manifest_document_bytes: self.codec.limits().max_document_bytes,
        })
    }

    pub(super) fn repository_read_limits(&self) -> ArtifactPreparationReadLimits {
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
        add(&self.verification_statistics.full_fetch_attempts, 1);
        let limits = ArtifactPreparationReadLimits {
            maximum_component_bytes: requested
                .maximum_component_bytes
                .min(self.config.max_component_bytes),
            maximum_metadata_document_bytes: requested
                .maximum_metadata_document_bytes
                .min(self.config.max_metadata_bytes),
            maximum_manifest_document_bytes: requested
                .maximum_manifest_document_bytes
                .min(self.codec.limits().max_document_bytes),
        };
        // Copy only the immutable admitted size. Release the index lock before
        // any filesystem operation, allocation of input buffers, or decoding.
        let bounds = self.preparation_read_bounds(release)?;
        if bounds.component_bytes > limits.maximum_component_bytes as u64 {
            return Err(resource_exhausted(
                "stored component exceeds configured component byte limit",
            ));
        }
        let verified = self.load_complete_entry_with_limits(
            &self.entry_path(release)?,
            Retention::Component,
            limits,
        )?;
        self.verify_admission_index(release, &verified)?;
        self.current_eligibility(release)?;
        let (descriptor, manifest, contracts) = verified.metadata.into_parts();
        Ok(CapsuleArtifact {
            descriptor,
            manifest,
            contracts,
            component_bytes: verified.component_bytes,
        })
    }
}
