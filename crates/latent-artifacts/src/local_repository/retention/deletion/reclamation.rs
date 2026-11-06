//! Observe the physical content of an already committed logical deletion.
use super::{
    busy, check_time, checked, deadline, model, storage, uncertain, DirectoryArtifactRepository,
    Duration, PlatformError, PublicationDeletionRequest, ReleaseLifecycleState,
};
use crate::{PublicationReclamationAssessment, PublicationReclamationLimits, PublicationRef};

impl DirectoryArtifactRepository {
    /// Trusted-host read-only assessment of the exact retained original deletion.
    /// The adapter must authorize scope and actor before calling. This creates no
    /// receipt, audit record, cleanup reservation, storage refund or unlink permit.
    /// It refuses UNKNOWN, changed requests, unavailable owners and held readers.
    /// All selected publication files and distinct canonical blobs are hashed
    /// under explicit file/byte/deadline bounds. There is no unrelated catalog walk.
    pub fn inspect_publication_reclamation(
        &self,
        deletion: &PublicationDeletionRequest,
        limits: PublicationReclamationLimits,
        timeout: Duration,
    ) -> Result<PublicationReclamationAssessment, PlatformError> {
        let deadline = deadline(timeout)?;
        deletion.validate()?;
        limits.validate()?;
        model::encode(deletion, model::MAX_REQUEST)?;
        let mut assessment = None;
        self.with_selected_publications(deletion, deadline, true, &mut |state, revision| {
            let mut selected = Vec::with_capacity(deletion.targets.len());
            for target in &deletion.targets {
                check_time(deadline)?;
                let reference = &target.publication;
                let path = if self
                    .life_store()
                    .record_publication(&reference.id)?
                    .is_some()
                {
                    self.publication_path(&reference.id)
                } else {
                    self.web_publication_path(&reference.id)
                };
                selected.push((reference.id.clone(), path));
            }
            let fence = storage::fence(&self.root, checked(state)?)?;
            let content = self
                .content
                .try_lock()
                .map_err(|_| busy())?
                .inspect_reclamation(&selected, limits, deadline)?;
            check_time(deadline)?;
            assessment = Some(PublicationReclamationAssessment {
                deletion: deletion.clone(),
                catalog_fence: fence,
                reference_revision: revision,
                content,
            });
            Ok(())
        })?;
        assessment.ok_or_else(uncertain)
    }

    pub(in crate::local_repository::retention) fn tombstoned_generation(
        &self,
        reference: &PublicationRef,
    ) -> Result<u64, PlatformError> {
        if let Some(record) = self.life_store().record_publication(&reference.id)? {
            if record.scope != reference.scope
                || !matches!(
                    record.state,
                    ReleaseLifecycleState::Retired | ReleaseLifecycleState::Revoked
                )
            {
                return Err(super::super::unavailable_target());
            }
            Ok(record.generation)
        } else {
            self.web.tombstoned_generation(reference)
        }
    }
}
