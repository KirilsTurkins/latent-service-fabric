//! Capsule immutable-history reclamation, including recognized-intent recovery.
//! Web payloads and independent lifecycle/evidence/audit histories remain retained.
use super::*;
use crate::lifecycle::LifecycleIdentity;
use crate::{
    PublicationReclamationLimits, PublicationReclamationLookup, PublicationReclamationRequest,
    PublicationReclamationResult,
};
use latent_core::PublicationId;
use model::cleanup::Plan;

impl DirectoryArtifactRepository {
    /// Trusted-host continuation of one exact retained deletion. Authenticate the
    /// scope/actor and reserve finite audit outcome/response capacity in preflight.
    /// A successful receipt reports synchronized immutable namespace removal only.
    /// No new cleanup may be inferred from UNKNOWN, or from an assessment alone.
    /// Componentless-web targets are rejected before preflight or any mutation.
    pub fn reclaim_tombstoned_capsules(
        &self,
        request: &PublicationReclamationRequest,
        timeout: Duration,
        preflight: &mut dyn FnMut(&PublicationReclamationResult) -> Result<(), PlatformError>,
    ) -> Result<PublicationReclamationResult, PlatformError> {
        let deadline = deadline(timeout)?;
        request.validate()?;
        model::encode(request, model::MAX_REQUEST)?;
        match self.publication_reclamation_operation(
            &request.deletion.scope,
            &request.deletion.operation_id,
        )? {
            PublicationReclamationLookup::Found(receipt) => {
                if receipt.request != *request {
                    return Err(conflict());
                }
                let result = PublicationReclamationResult {
                    receipt,
                    replay: true,
                };
                preflight(&result)?;
                check_time(deadline)?;
                return Ok(result);
            }
            PublicationReclamationLookup::Uncertain => return Err(uncertain()),
            PublicationReclamationLookup::Unknown => {}
        }
        let mut prepared = None;
        self.with_selected_publications(
            &request.deletion,
            deadline,
            true,
            &mut |state, revision| {
                if storage::fence(&self.root, checked(state)?)? != request.expected_catalog_fence {
                    return Err(conflict());
                }
                let plan = self.prepare_cleanup(request, revision, deadline)?;
                let next = checked(state)?.begin_cleanup(&plan)?;
                self.check_cleanup_capacity(checked(state)?, &next)?;
                prepared = Some((plan, next));
                Ok(())
            },
        )?;
        let (plan, next) = prepared.ok_or_else(uncertain)?;
        let result = PublicationReclamationResult {
            receipt: plan.receipt(),
            replay: false,
        };
        preflight(&result)?;
        check_time(deadline)?;
        self.with_reclamation_selection(
            &request.deletion,
            deadline,
            true,
            &mut |state, revision, writer| {
                if revision != plan.reference_revision
                    || storage::fence(&self.root, checked(state)?)?
                        != request.expected_catalog_fence
                    || checked(state)?.begin_cleanup(&plan)? != next
                    || self.prepare_cleanup(request, revision, deadline)? != plan
                {
                    return Err(conflict());
                }
                self.commit_cleanup(state, writer, &plan, &next, deadline)
            },
        )?;
        Ok(result)
    }

    pub fn publication_reclamation_operation(
        &self,
        scope: &LifecycleScope,
        operation_id: &str,
    ) -> Result<PublicationReclamationLookup, PlatformError> {
        scope.validate()?;
        crate::publication_retention::token(operation_id)?;
        let state = self.retention.try_lock().map_err(|_| busy())?;
        if !state.healthy || self.life_store().check_health().is_err() {
            return Ok(PublicationReclamationLookup::Uncertain);
        }
        Ok(checked(&state)?
            .cleanup
            .as_ref()
            .and_then(|c| c.receipt(scope, operation_id))
            .cloned()
            .map_or(
                PublicationReclamationLookup::Unknown,
                PublicationReclamationLookup::Found,
            ))
    }

    fn prepare_cleanup(
        &self,
        request: &PublicationReclamationRequest,
        revision: u64,
        deadline: Instant,
    ) -> Result<Plan, PlatformError> {
        let mut identities = Vec::with_capacity(request.deletion.targets.len());
        let mut selected = Vec::with_capacity(request.deletion.targets.len());
        for target in &request.deletion.targets {
            check_time(deadline)?;
            let identity = self
                .life_store()
                .identity_publication(&target.publication.id)?
                .filter(|i| i.publication().ok().as_ref() == Some(&target.publication))
                .ok_or_else(|| {
                    failure(
                        PlatformErrorCode::InvalidArgument,
                        "publication-reclamation-capsule-target-required",
                    )
                })?;
            identities.push(identity);
            selected.push((
                target.publication.id.clone(),
                self.publication_path(&target.publication.id),
            ));
        }
        // Both the preflight preview and post-callback recheck count towards one
        // public work limit. Neither pass can consume more than half the budget.
        let limits = PublicationReclamationLimits {
            maximum_files: request.limits.maximum_files / 2,
            maximum_bytes_hashed: request.limits.maximum_bytes_hashed / 2,
        };
        let files = self
            .content
            .try_lock()
            .map_err(|_| busy())?
            .plan_reclamation(&selected, limits, deadline)?;
        Ok(Plan {
            request: request.clone(),
            reference_revision: revision,
            identities,
            files,
        })
    }
    fn check_cleanup_capacity(
        &self,
        old: &model::Head,
        next: &model::Head,
    ) -> Result<(), PlatformError> {
        storage::validate_transition(old, next)?;
        // Bound the completion envelope BEFORE accepting the irreversible intent.
        let finished = next.finish_cleanup(next.cleanup.as_ref().ok_or_else(corrupt)?.fence)?;
        storage::validate_transition(next, &finished)?;
        let (metadata, physical) = cleanup_exposure(old, next, &finished)?;
        self.index
            .try_read()
            .map_err(|_| busy())?
            .check_retention(metadata, self.config)?;
        self.content
            .try_lock()
            .map_err(|_| busy())?
            .check_retention_control(physical)?;
        Ok(())
    }
    fn commit_cleanup(
        &self,
        state: &mut RetentionState,
        writer: &mut crate::local_repository::PublicationState,
        plan: &Plan,
        next: &model::Head,
        deadline: Instant,
    ) -> Result<(), PlatformError> {
        self.check_cleanup_capacity(checked(state)?, next)?;
        let old = checked(state)?.clone();
        let finished = next.finish_cleanup(plan.request.expected_catalog_fence)?;
        let (metadata, physical) = cleanup_exposure(&old, next, &finished)?;
        let mut index = self.index.try_write().map_err(|_| busy())?;
        let mut content = self.content.try_lock().map_err(|_| busy())?;
        check_time(deadline)?;
        index.replace_retention(metadata, self.config)?;
        content.replace_retention_control(physical)?;
        state.healthy = false;
        let outcome: Result<(), PlatformError> = (|| {
            storage::persist(&self.root, &old, next, deadline)?;
            state.head = Some(next.clone());
            storage::fault(8)?;
            content.execute_cleanup(&plan.files, plan.request.limits, deadline, false)?;
            let final_head = next.finish_cleanup(storage::fence(&self.root, next)?)?;
            storage::fault(13)?;
            storage::persist(&self.root, next, &final_head, deadline)?;
            storage::fault(14)?;
            // Refunded metadata and directory slots are published only after
            // file unlink + parent fsync and the durable completion receipt.
            for target in &plan.request.deletion.targets {
                index.refund_reclaimed(&target.publication.id)?;
            }
            writer.release_directories = writer
                .release_directories
                .checked_sub(plan.identities.len())
                .ok_or_else(corrupt)?;
            let (metadata, physical) = exposure(&final_head)?;
            index.replace_retention(metadata, self.config)?;
            content.replace_retention_control(physical)?;
            state.head = Some(final_head);
            Ok(())
        })();
        if outcome.is_err() {
            self.life_store().retire();
            self.web.epoch.retire();
            return Err(uncertain());
        }
        state.healthy = true;
        Ok(())
    }

    pub(in crate::local_repository) fn preload_cleanup(&self) -> Result<(), PlatformError> {
        let marker = self.root.join("LIFECYCLE_MODE");
        let promoted = if storage::exists(&marker)? {
            is_marker(&read_bounded_file(&marker, 64, "lifecycle mode")?)
        } else {
            false
        };
        self.retention.lock().map_err(lock_error)?.head =
            storage::load(&self.root, promoted, false)?;
        Ok(())
    }
    pub(in crate::local_repository) fn cleanup_identities(
        &self,
    ) -> Result<Vec<LifecycleIdentity>, PlatformError> {
        Ok(self
            .retention
            .lock()
            .map_err(lock_error)?
            .head
            .as_ref()
            .and_then(|h| h.cleanup.as_ref())
            .map_or_else(Vec::new, |c| c.identities.clone()))
    }
    pub(in crate::local_repository) fn is_reclaimed_publication(
        &self,
        id: &PublicationId,
    ) -> Result<bool, PlatformError> {
        Ok(self
            .retention
            .lock()
            .map_err(lock_error)?
            .head
            .as_ref()
            .and_then(|h| h.cleanup.as_ref())
            .is_some_and(|c| {
                c.identities
                    .binary_search_by(|i| i.publication().expect("validated identity").id.cmp(id))
                    .is_ok()
            }))
    }
    pub(in crate::local_repository) fn cleanup_identity_path(
        &self,
        path: &Path,
    ) -> Result<Option<LifecycleIdentity>, PlatformError> {
        let Some(name) = path.file_name().and_then(|n| n.to_str()) else {
            return Ok(None);
        };
        let Ok(id) = format!("publication:sha256:{name}").parse::<PublicationId>() else {
            return Ok(None);
        };
        let state = self.retention.lock().map_err(lock_error)?;
        let Some(cleanup) = state.head.as_ref().and_then(|h| h.cleanup.as_ref()) else {
            return Ok(None);
        };
        Ok(cleanup
            .identities
            .binary_search_by(|i| i.publication().expect("validated identity").id.cmp(&id))
            .ok()
            .map(|n| cleanup.identities[n].clone()))
    }
    pub(in crate::local_repository) fn check_cleanup_path(
        &self,
        identity: &LifecycleIdentity,
        path: &Path,
    ) -> Result<(), PlatformError> {
        let id = identity.publication()?.id;
        let state = self.retention.lock().map_err(lock_error)?;
        let active = state
            .head
            .as_ref()
            .and_then(|h| h.cleanup.as_ref())
            .and_then(|c| c.active.as_ref());
        if !active.is_some_and(|p| p.files.directories.iter().any(|d| d.id == id)) {
            return Err(corrupt()); // A completed cleanup cannot resurrect older payload directories.
        }
        shared_content::directory(path)
    }
    pub(super) fn recover_cleanup(&self, head: model::Head) -> Result<model::Head, PlatformError> {
        let Some(plan) = head.cleanup.as_ref().and_then(|c| c.active.as_ref()) else {
            return Ok(head);
        };
        // This is continuation of a durable committed original operation under
        // exclusive installation ownership, never a new deletion decision.
        plan.validate(&head)?;
        let deadline = deadline(Duration::from_secs(30))?;
        let (metadata, physical) = exposure(&head)?;
        self.index
            .write()
            .map_err(lock_error)?
            .replace_retention(metadata, self.config)?;
        let mut content = self.content.lock().map_err(lock_error)?;
        content.replace_retention_control(physical)?;
        content.execute_cleanup(&plan.files, plan.request.limits, deadline, true)?;
        let final_head = head.finish_cleanup(storage::fence(&self.root, &head)?)?;
        storage::persist(&self.root, &head, &final_head, deadline)?;
        Ok(final_head)
    }
}

fn cleanup_exposure(
    old: &model::Head,
    next: &model::Head,
    finished: &model::Head,
) -> Result<(usize, u64), PlatformError> {
    let a = exposure(old)?;
    let b = exposure(next)?;
    let c = exposure(finished)?;
    Ok((a.0.max(b.0).max(c.0), a.1.max(b.1).max(c.1)))
}
