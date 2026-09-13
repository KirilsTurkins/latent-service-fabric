//! Sealed reads and execution selection keep publication and byte identity distinct.

use super::*;
use crate::{
    ArtifactPreparationReadBounds, ArtifactPreparationReadLimits, HistoricalExecutionSnapshot,
    LifecycleScope, PublicationRef, ReleaseUseEligibility,
};
use latent_core::{PublicationId, TenantId};

impl DirectoryArtifactRepository {
    pub(crate) fn selected_publication(
        &self,
        component: &ReleaseDigest,
        publication: Option<&PublicationId>,
    ) -> Result<PublicationRef, PlatformError> {
        crate::publication::validate_component(component)?;
        let Some(id) = publication else {
            return self.require_legacy_publication(None, component);
        };
        let index = self.index.read().map_err(lock_error)?;
        let entry = index
            .by_publication
            .get(id)
            .ok_or_else(|| error(PlatformErrorCode::NotFound, "publication not found"))?;
        if entry.value.descriptor.release_digest != *component {
            return Err(corrupt("publication-component-mismatch"));
        }
        Ok(entry.publication.clone())
    }

    /// Called by a trusted execution/deployment adapter, before metadata is cloned.
    /// Local-unscoped compatibility is available only in a trusted-local catalog.
    pub(crate) fn select_execution_publication(
        &self,
        tenant: &TenantId,
        component: &ReleaseDigest,
        publication: Option<&PublicationId>,
    ) -> Result<PublicationRef, PlatformError> {
        let scope = LifecycleScope::Tenant(tenant.clone());
        scope.validate()?;
        crate::publication::validate_component(component)?;
        let reference = if let Some(id) = publication {
            let index = self.index.read().map_err(lock_error)?;
            let entry = index
                .by_publication
                .get(id)
                .filter(|entry| {
                    entry.publication.scope == scope
                        || (entry.publication.scope == LifecycleScope::LocalUnscoped
                            && self.admission.is_none())
                })
                .ok_or_else(|| error(PlatformErrorCode::NotFound, "publication not found"))?;
            if entry.value.descriptor.release_digest != *component {
                return Err(corrupt("publication-component-mismatch"));
            }
            entry.publication.clone()
        } else {
            let index = self.index.read().map_err(lock_error)?;
            let scoped = index.legacy_component(Some(&scope), component)?;
            let local = if self.admission.is_none() {
                index.legacy_component(Some(&LifecycleScope::LocalUnscoped), component)?
            } else {
                None
            };
            if scoped.is_some() && local.is_some() {
                return Err(crate::publication::ambiguous());
            }
            scoped
                .or(local)
                .map(|entry| entry.publication.clone())
                .ok_or_else(|| error(PlatformErrorCode::NotFound, "publication not found"))?
        };
        if reference.scope != scope
            && !(reference.scope == LifecycleScope::LocalUnscoped && self.admission.is_none())
        {
            return Err(error(PlatformErrorCode::NotFound, "publication not found"));
        }
        Ok(reference)
    }

    pub(crate) fn selected_execution_eligibility(
        &self,
        component: &ReleaseDigest,
        publication: Option<&PublicationId>,
    ) -> Result<ReleaseUseEligibility, PlatformError> {
        let reference = self.selected_publication(component, publication)?;
        self.publication_execution_eligibility(&reference)
    }

    pub(crate) fn selected_preparation_identity(
        &self,
        component: &ReleaseDigest,
        publication: Option<&PublicationId>,
    ) -> Result<Option<ArtifactPreparationIdentity>, PlatformError> {
        let reference = self.selected_publication(component, publication)?;
        self.publication_execution_eligibility(&reference)?;
        let index = self.index.read().map_err(lock_error)?;
        let entry = index
            .exact(&reference)?
            .ok_or_else(|| error(PlatformErrorCode::NotFound, "publication not found"))?;
        entry
            .preparation_stamp
            .map(|stamp| {
                ArtifactPreparationIdentity::new(
                    Arc::clone(&self.preparation_epoch),
                    component,
                    entry.value.descriptor.size_bytes,
                    stamp,
                    reference.id.clone(),
                )
            })
            .transpose()
    }

    pub(crate) fn selected_read_bounds(
        &self,
        component: &ReleaseDigest,
        publication: Option<&PublicationId>,
    ) -> Result<ArtifactPreparationReadBounds, PlatformError> {
        let reference = self.selected_publication(component, publication)?;
        self.publication_execution_eligibility(&reference)?;
        let index = self.index.read().map_err(lock_error)?;
        let entry = index
            .exact(&reference)?
            .ok_or_else(|| error(PlatformErrorCode::NotFound, "publication not found"))?;
        Ok(ArtifactPreparationReadBounds {
            component_bytes: entry.value.descriptor.size_bytes,
            maximum_metadata_document_bytes: self.config.max_metadata_bytes,
            maximum_manifest_document_bytes: self.codec.limits().max_document_bytes,
        })
    }

    pub(crate) fn selected_fetch(
        &self,
        component: &ReleaseDigest,
        publication: Option<&PublicationId>,
        requested: ArtifactPreparationReadLimits,
    ) -> Result<CapsuleArtifact, PlatformError> {
        add(&self.verification_statistics.full_fetch_attempts, 1);
        let reference = self.selected_publication(component, publication)?;
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
        let bounds = self.selected_read_bounds(component, Some(&reference.id))?;
        if bounds.component_bytes > limits.maximum_component_bytes as u64 {
            return Err(resource_exhausted(
                "stored component exceeds configured component byte limit",
            ));
        }
        let verified = self.load_complete_entry_with_limits(
            &self.publication_path(&reference.id),
            Retention::Component,
            limits,
        )?;
        self.verify_publication_index(&reference, &verified)?;
        verified.metadata.verify_requested(component)?;
        self.publication_execution_eligibility(&reference)?;
        let (descriptor, manifest, contracts) = verified.metadata.into_parts();
        Ok(CapsuleArtifact {
            descriptor,
            manifest,
            contracts,
            component_bytes: verified.component_bytes,
        })
    }

    pub(crate) fn selected_metadata(
        &self,
        component: &ReleaseDigest,
        publication: Option<&PublicationId>,
    ) -> Result<VerifiedArtifactMetadata, PlatformError> {
        let reference = self.selected_publication(component, publication)?;
        self.publication_execution_eligibility(&reference)?;
        let snapshot = self.selected_historical_snapshot(component, Some(&reference.id))?;
        self.publication_execution_eligibility(&reference)?;
        Ok(snapshot.into_parts().0)
    }

    pub(crate) fn selected_historical_snapshot(
        &self,
        component: &ReleaseDigest,
        publication: Option<&PublicationId>,
    ) -> Result<HistoricalExecutionSnapshot, PlatformError> {
        let reference = self.selected_publication(component, publication)?;
        add(&self.verification_statistics.metadata_fetch_attempts, 1);
        let verified =
            self.load_complete_entry(&self.publication_path(&reference.id), Retention::Metadata)?;
        self.verify_publication_index(&reference, &verified)?;
        verified.metadata.verify_requested(component)?;
        HistoricalExecutionSnapshot::directory(
            verified.metadata,
            reference.clone(),
            self.lifecycle_authority(),
            self.publication_execution_eligibility(&reference),
        )
    }
}
