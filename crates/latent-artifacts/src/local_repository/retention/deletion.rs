//! Coherent negative checks. No tombstones, content unlink, or audit mutation.
use super::{
    busy, check_time, checked, conflict, corrupt, deadline, failure, model, storage, uncertain,
    DirectoryArtifactRepository, Duration, PlatformError, PlatformErrorCode,
};
use crate::{
    PublicationDeletionAssessment, PublicationDeletionRequest, PublicationReferenceAuthority,
    ReleaseLifecycleState,
};

impl DirectoryArtifactRepository {
    /// Bind exactly one native reference owner before exposing maintenance.
    /// A weak reference avoids a catalog ownership cycle. Its disappearance is
    /// unavailable, never evidence that the installation has no references.
    /// Changing the bound owner requires a quiesced reopen of the whole catalog.
    pub fn install_publication_reference_authority(
        &self,
        authority: &std::sync::Arc<dyn PublicationReferenceAuthority>,
    ) -> Result<(), PlatformError> {
        if !authority
            .catalog_authority()?
            .same_owner(&self.lifecycle_authority())
        {
            return Err(reference_unavailable());
        }
        let _work = self.admission_work.try_lock().map_err(|_| busy())?;
        self.life_store().check_health()?;
        if let Some(existing) = self.reference_authority.get() {
            return if std::sync::Weak::ptr_eq(existing, &std::sync::Arc::downgrade(authority)) {
                Ok(())
            } else {
                Err(reference_unavailable())
            };
        }
        self.reference_authority
            .set(std::sync::Arc::downgrade(authority))
            .map_err(|_| reference_unavailable())
    }

    /// Inspect a prospective deletion under the actual native commit/read owners.
    /// This is advisory only: it creates no durable receipt, reservation, permit,
    /// tombstone or refund. Committed-history deletion remains unavailable.
    pub fn inspect_publication_deletion(
        &self,
        request: &PublicationDeletionRequest,
        timeout: Duration,
    ) -> Result<PublicationDeletionAssessment, PlatformError> {
        request.validate()?;
        model::encode(request, model::MAX_REQUEST)?;
        let deadline = deadline(timeout)?;
        let _work = self.admission_work.try_lock().map_err(|_| busy())?;
        let mut assessment = None;
        self.life_store().with_exclusive(&mut |_| {
            let _epoch = self.web.epoch.write()?;
            let writer = self.publish_lock.try_lock().map_err(|_| busy())?;
            if writer.pending.is_some() {
                return Err(uncertain());
            }
            let state = self.retention.try_lock().map_err(|_| busy())?;
            let head = checked(&state)?;
            // Validate the entire exact selection before reporting anything about
            // pins/readers/routes, including when a foreign target follows a local one.
            for target in &request.targets {
                check_time(deadline)?;
                if self.retention_generation(&target.publication)? != target.expected_generation {
                    return Err(conflict());
                }
            }
            if storage::fence(&self.root, head)? != request.expected_catalog_fence {
                return Err(conflict());
            }
            let publications: Vec<_> = request
                .targets
                .iter()
                .map(|target| target.publication.clone())
                .collect();
            for publication in &publications {
                check_time(deadline)?;
                if head.pin(publication)?.is_some() {
                    return Err(failure(
                        PlatformErrorCode::StateConflict,
                        "publication-deletion-retention-pin",
                    ));
                }
                let terminal =
                    if let Some(record) = self.life_store().record_publication(&publication.id)? {
                        matches!(
                            record.state,
                            ReleaseLifecycleState::Retired | ReleaseLifecycleState::Revoked
                        )
                    } else {
                        self.web.terminal_for_deletion(publication)?
                    };
                if !terminal {
                    return Err(failure(
                        PlatformErrorCode::StateConflict,
                        "publication-deletion-requires-terminal-publication",
                    ));
                }
            }
            let _readers = self.read_owners.exclusive()?;
            if self.web.retained_readers(&publications)? {
                return Err(failure(
                    PlatformErrorCode::Unavailable,
                    "publication-deletion-readers-active",
                ));
            }
            let references = self
                .reference_authority
                .get()
                .and_then(std::sync::Weak::upgrade)
                .ok_or_else(reference_unavailable)?;
            if !references
                .catalog_authority()?
                .same_owner(&self.lifecycle_authority())
            {
                return Err(reference_unavailable());
            }
            references.with_unreferenced_publications(
                &self.lifecycle_authority(),
                &publications,
                &mut |reference_revision| {
                    if assessment.is_some() {
                        return Err(corrupt());
                    }
                    check_time(deadline)?;
                    assessment = Some(PublicationDeletionAssessment {
                        request: request.clone(),
                        reference_revision,
                    });
                    Ok(())
                },
            )?;
            check_time(deadline)
        })?;
        assessment.ok_or_else(uncertain)
    }
}

fn reference_unavailable() -> PlatformError {
    failure(
        PlatformErrorCode::Unavailable,
        "publication-deletion-reference-authority-unavailable",
    )
}
