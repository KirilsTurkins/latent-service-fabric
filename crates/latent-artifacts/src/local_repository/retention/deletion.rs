//! Coherent negative checks held through the durable tombstone commit.
mod commit;
mod reclamation;
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
    /// tombstone or refund. The tombstone commit repeats all checks.
    pub fn inspect_publication_deletion(
        &self,
        request: &PublicationDeletionRequest,
        timeout: Duration,
    ) -> Result<PublicationDeletionAssessment, PlatformError> {
        request.validate()?;
        model::encode(request, model::MAX_REQUEST)?;
        let deadline = deadline(timeout)?;
        let mut assessment = None;
        self.with_deletion_selection(request, deadline, &mut |_, reference_revision| {
            assessment = Some(PublicationDeletionAssessment {
                request: request.clone(),
                reference_revision,
            });
            Ok(())
        })?;
        assessment.ok_or_else(uncertain)
    }

    fn with_deletion_selection(
        &self,
        request: &PublicationDeletionRequest,
        deadline: std::time::Instant,
        action: &mut dyn FnMut(&mut super::RetentionState, u64) -> Result<(), PlatformError>,
    ) -> Result<(), PlatformError> {
        self.with_selected_publications(request, deadline, false, action)
    }

    pub(super) fn with_selected_publications(
        &self,
        request: &PublicationDeletionRequest,
        deadline: std::time::Instant,
        tombstoned: bool,
        action: &mut dyn FnMut(&mut super::RetentionState, u64) -> Result<(), PlatformError>,
    ) -> Result<(), PlatformError> {
        self.with_reclamation_selection(request, deadline, tombstoned, &mut |state, revision, _| {
            action(state, revision)
        })
    }

    pub(super) fn with_reclamation_selection(
        &self,
        request: &PublicationDeletionRequest,
        deadline: std::time::Instant,
        tombstoned: bool,
        action: &mut dyn FnMut(
            &mut super::RetentionState,
            u64,
            &mut crate::local_repository::PublicationState,
        ) -> Result<(), PlatformError>,
    ) -> Result<(), PlatformError> {
        check_time(deadline)?;
        let _work = self.admission_work.try_lock().map_err(|_| busy())?;
        self.life_store().with_exclusive(&mut |_| {
            let _epoch = self.web.epoch.write()?;
            let mut writer = self.publish_lock.try_lock().map_err(|_| busy())?;
            if writer.pending.is_some() {
                return Err(uncertain());
            }
            let mut state = self.retention.try_lock().map_err(|_| busy())?;
            let head = checked(&state)?;
            // A cleanup observation can only name the exact retained original
            // deletion. UNKNOWN/eviction is not permission to reconstruct it.
            if tombstoned {
                match head.deletion_receipt(&request.scope, &request.operation_id) {
                    Some(receipt) if receipt.request == *request => {}
                    Some(_) => return Err(conflict()),
                    None => {
                        return Err(failure(
                            PlatformErrorCode::NotFound,
                            "publication-reclamation-original-operation-unavailable",
                        ))
                    }
                }
            }
            if tombstoned
                && head.cleanup.as_ref().is_some_and(|c| {
                    request.targets.iter().any(|t| {
                        c.web_identities
                            .binary_search_by(|i| i.record.publication.id.cmp(&t.publication.id))
                            .is_ok()
                            || c.identities
                                .binary_search_by(|i| {
                                    i.publication()
                                        .expect("validated identity")
                                        .id
                                        .cmp(&t.publication.id)
                                })
                                .is_ok()
                    })
                })
            {
                return Err(failure(
                    PlatformErrorCode::StateConflict,
                    "publication-reclamation-already-committed-query-original-operation",
                ));
            }
            // Validate every scoped identity before disclosing pins or references.
            for target in &request.targets {
                check_time(deadline)?;
                let generation = if tombstoned {
                    if !head
                        .deletion
                        .as_ref()
                        .is_some_and(|d| d.contains(&target.publication.id))
                    {
                        return Err(corrupt());
                    }
                    self.tombstoned_generation(&target.publication)?
                } else {
                    self.retention_generation(&target.publication)?
                };
                if generation != target.expected_generation {
                    return Err(conflict());
                }
            }
            // A retained deletion request contains the pre-deletion fence. The
            // read-only cleanup assessment returns today's fence separately.
            if !tombstoned && storage::fence(&self.root, head)? != request.expected_catalog_fence {
                return Err(conflict());
            }
            let publications: Vec<_> = request
                .targets
                .iter()
                .map(|t| t.publication.clone())
                .collect();
            for publication in &publications {
                check_time(deadline)?;
                if head.pin(publication)?.is_some() {
                    return Err(failure(
                        PlatformErrorCode::StateConflict,
                        "publication-deletion-retention-pin",
                    ));
                }
                if !tombstoned && !self.terminal_publication(publication)? {
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
            let mut called = false;
            references.with_unreferenced_publications(
                &self.lifecycle_authority(),
                &publications,
                &mut |revision| {
                    if called {
                        return Err(corrupt());
                    }
                    called = true;
                    check_time(deadline)?;
                    action(&mut state, revision, &mut writer)
                },
            )?;
            // A successful commit cannot be retroactively reported as a definite
            // deadline rejection. The action owns its precommit/time checks.
            if called {
                Ok(())
            } else {
                Err(uncertain())
            }
        })
    }

    fn terminal_publication(
        &self,
        publication: &crate::PublicationRef,
    ) -> Result<bool, PlatformError> {
        if let Some(record) = self.life_store().record_publication(&publication.id)? {
            if record.scope != publication.scope {
                return Err(super::unavailable_target());
            }
            Ok(matches!(
                record.state,
                ReleaseLifecycleState::Retired | ReleaseLifecycleState::Revoked
            ))
        } else {
            self.web.terminal_for_deletion(publication)
        }
    }
}

fn reference_unavailable() -> PlatformError {
    failure(
        PlatformErrorCode::Unavailable,
        "publication-deletion-reference-authority-unavailable",
    )
}
