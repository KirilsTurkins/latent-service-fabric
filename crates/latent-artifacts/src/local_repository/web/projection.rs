mod metadata;

use super::{
    busy, capacity, corrupt, denied, error, storage, Arc, DirectoryArtifactRepository,
    PlatformError, PlatformErrorCode, PublicationId, PublicationRef, TenantId,
};
use crate::{
    ArtifactPreparationIdentity, ArtifactPreparationReadBounds, ArtifactPreparationReadLimits,
    CapsuleArtifact, HistoricalExecutionSnapshot, ReleaseUseEligibility, VerifiedArtifactMetadata,
};
use latent_core::ReleaseDigest;
pub(super) use metadata::Projection;

impl DirectoryArtifactRepository {
    pub(in crate::local_repository) fn web_execution_publication(
        &self,
        component: &ReleaseDigest,
        id: &PublicationId,
        tenant: Option<&TenantId>,
    ) -> Result<PublicationRef, PlatformError> {
        self.web.epoch.check()?;
        let state = self.web.state.try_read().map_err(|_| busy())?;
        let entry = state
            .entries
            .get(id)
            .filter(|entry| {
                tenant.is_none_or(|tenant| entry.record.publication.scope.tenant() == Some(tenant))
            })
            .ok_or_else(|| error(PlatformErrorCode::NotFound, "publication not found"))?;
        let projection = entry
            .projection
            .as_ref()
            .ok_or_else(crate::web::incompatible)?;
        if projection.descriptor.release_digest != *component {
            return Err(corrupt("publication-component-mismatch"));
        }
        Ok(entry.record.publication.clone())
    }

    pub(in crate::local_repository) fn is_web_publication(
        &self,
        reference: &PublicationRef,
    ) -> Result<bool, PlatformError> {
        let state = self.web.state.try_read().map_err(|_| busy())?;
        Ok(state
            .entries
            .get(&reference.id)
            .is_some_and(|entry| entry.record.publication == *reference))
    }

    pub(in crate::local_repository) fn web_execution_eligibility(
        &self,
        reference: &PublicationRef,
    ) -> Result<ReleaseUseEligibility, PlatformError> {
        let selection = self.select_web_publication(reference)?;
        ReleaseUseEligibility::from_web(&self.lifecycle_authority(), selection.eligibility)
    }

    pub(in crate::local_repository) fn web_preparation_identity(
        &self,
        reference: &PublicationRef,
    ) -> Result<Option<ArtifactPreparationIdentity>, PlatformError> {
        self.web_execution_eligibility(reference)?;
        let state = self.web.state.try_read().map_err(|_| busy())?;
        let projection = state
            .entry(reference)?
            .projection
            .as_ref()
            .ok_or_else(crate::web::incompatible)?;
        ArtifactPreparationIdentity::new(
            Arc::clone(&self.preparation_epoch),
            &projection.descriptor.release_digest,
            projection.descriptor.size_bytes,
            projection.fingerprint,
            reference.id.clone(),
        )
        .map(Some)
    }

    pub(in crate::local_repository) fn web_execution_read_bounds(
        &self,
        reference: &PublicationRef,
    ) -> Result<ArtifactPreparationReadBounds, PlatformError> {
        self.web_execution_eligibility(reference)?;
        let state = self.web.state.try_read().map_err(|_| busy())?;
        let projection = state
            .entry(reference)?
            .projection
            .as_ref()
            .ok_or_else(crate::web::incompatible)?;
        Ok(ArtifactPreparationReadBounds {
            component_bytes: projection.descriptor.size_bytes,
            maximum_metadata_document_bytes: self
                .web_authority()?
                .limits
                .max_document_bytes
                .max(metadata::METADATA_BYTES),
            maximum_manifest_document_bytes: metadata::METADATA_BYTES,
        })
    }

    pub(in crate::local_repository) fn web_execution_fetch(
        &self,
        reference: &PublicationRef,
        limits: ArtifactPreparationReadLimits,
    ) -> Result<CapsuleArtifact, PlatformError> {
        let bounds = self.web_execution_read_bounds(reference)?;
        if bounds.component_bytes > limits.maximum_component_bytes as u64
            || bounds.maximum_metadata_document_bytes > limits.maximum_metadata_document_bytes
            || bounds.maximum_manifest_document_bytes > limits.maximum_manifest_document_bytes
        {
            return Err(capacity());
        }
        let read = self.read_web_renderer(reference)?;
        let state = self.web.state.try_read().map_err(|_| busy())?;
        let projection = state
            .entry(reference)?
            .projection
            .as_ref()
            .ok_or_else(crate::web::incompatible)?;
        let value = CapsuleArtifact {
            descriptor: projection.descriptor.clone(),
            manifest: projection.manifest.clone(),
            contracts: projection.contracts.clone(),
            component_bytes: read.bytes.into_vec(),
        };
        drop(state);
        read.selection
            .eligibility
            .check_current(reference.scope.tenant().ok_or_else(denied)?)?;
        Ok(value)
    }

    pub(in crate::local_repository) fn web_historical_execution(
        &self,
        reference: &PublicationRef,
    ) -> Result<HistoricalExecutionSnapshot, PlatformError> {
        let state = self.web.state.try_read().map_err(|_| busy())?;
        let entry = state.entry(reference)?;
        let projection = Arc::clone(
            entry
                .projection
                .as_ref()
                .ok_or_else(crate::web::incompatible)?,
        );
        let renderer = entry
            .layout
            .manifest()
            .renderer
            .as_ref()
            .ok_or_else(crate::web::incompatible)?;
        let layer_path = renderer.layer.clone();
        let completion = entry.completion.clone();
        let charge = entry
            .retained_bytes()?
            .checked_add(self.web_authority()?.limits.max_document_bytes * 8)
            .and_then(|bytes| bytes.checked_add(16 * 1024))
            .ok_or_else(capacity)?;
        let _permit = self.web.reads.reserve(charge)?;
        drop(state);
        let directory = self.web_publication_path(&reference.id);
        let stored = storage::Stored::read_header(
            &directory,
            self.web_authority()?.limits,
            self.config.max_component_bytes,
        )?;
        if stored.digest()? != completion {
            return Err(corrupt("web-publication-changed"));
        }
        let layer = stored
            .layers
            .iter()
            .find(|layer| layer.path == layer_path)
            .ok_or_else(|| corrupt("web-layer-missing"))?;
        if layer.blob.digest != projection.descriptor.release_digest.0
            || layer.blob.size != projection.descriptor.size_bytes
        {
            return Err(corrupt("web-layer-association"));
        }
        super::super::admission_storage::read::verify(&directory, &layer.blob)?;
        let metadata = VerifiedArtifactMetadata::from_verified_parts(
            projection.descriptor.clone(),
            projection.manifest.clone(),
            projection.contracts.clone(),
            projection.descriptor.release_digest.clone(),
        )
        .with_web_execution_projection();
        HistoricalExecutionSnapshot::directory(
            metadata,
            reference.clone(),
            self.lifecycle_authority(),
            self.web_execution_eligibility(reference),
        )
    }
}
