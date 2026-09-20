use super::{
    busy, capacity, corrupt, denied, error, evidence, fs, io_error, lock_error, persistence,
    recovery, shared_content, storage, sync_dir, DirectoryArtifactRepository, PlatformError,
    PlatformErrorCode, Preflight, PublicationRef, PublicationState, ReleaseLifecycleAction, State,
    WebMutationResult, WebOperationReceipt, HEAD, TEMP_DIR,
};
use crate::AdmissionRecheck;
#[cfg(test)]
use std::sync::atomic::Ordering;

#[derive(Clone, Copy)]
pub(super) enum Payload<'a> {
    Publication(&'a storage::Prepared),
    Evidence(&'a evidence::PreparedEvidence),
    None,
}
impl DirectoryArtifactRepository {
    pub(super) fn commit_web(
        &self,
        current: &mut State,
        mut next: State,
        receipt: &WebOperationReceipt,
        payload: Payload<'_>,
        preflight: &mut Preflight<'_>,
    ) -> Result<WebMutationResult, PlatformError> {
        let mut writer = self.publish_lock.try_lock().map_err(|_| busy())?;
        if writer.pending.is_some() {
            return Err(busy());
        }
        let reference = &receipt.publication;
        let mut content = self.content.lock().map_err(lock_error)?;
        self.web_payload_preflight(&payload, reference, &mut next, &writer, &content)?;
        let retained = next.retained_bytes()?;
        self.index.read().map_err(lock_error)?.check_web(
            next.entries.len(),
            retained,
            self.config,
        )?;
        let head = persistence::encode(&next, self.lifecycle_limits, self.web_head_limit())?;
        let exposure = recovery::control_exposure(&next, head.len())?;
        content.check_web_control(exposure)?;
        let result = WebMutationResult {
            receipt: receipt.clone(),
            replay: false,
        };
        persistence::encode_line(&receipt, self.lifecycle_limits.max_receipt_bytes)?;
        preflight(&result)?;
        let positive = matches!(
            receipt.action,
            ReleaseLifecycleAction::Publish | ReleaseLifecycleAction::RenewEvidence
        );
        let grant = next.entry(reference)?.grant.clone();
        // Immutable payload I/O must not hold the policy clock fence. The
        // existing control owner can renew its finite lease while bytes are
        // staged. Nothing becomes a positive publication before the final
        // current-grant check and HEAD commit below.
        let staged = (|| {
            if positive {
                grant.as_ref().ok_or_else(denied)?.check_current()?;
            }
            // A failed write never restores in-memory authority. All future
            // web uses and catalog mutations wait for durable restart recovery.
            writer.pending = Some(reference.id.clone());
            self.activate_web(current)?;
            content.replace_web_control(exposure)?;
            self.stage_web_payload(&payload, reference, &mut writer, &mut content)?;
            #[cfg(test)]
            if let Some(observe) = self.web.after_payload_staged.lock().unwrap().take() {
                observe();
            }
            Ok(())
        })();
        let mut commit = |check: Option<&dyn AdmissionRecheck>| -> Result<(), PlatformError> {
            if let Some(check) = check {
                check.check()?;
            }
            #[cfg(test)]
            if self.fail_parent_sync_once.swap(false, Ordering::SeqCst) {
                return Err(busy());
            }
            persistence::atomic_write(&self.web_path().join(HEAD), &head)?;
            #[cfg(test)]
            if self.web.fail_after_head.swap(false, Ordering::SeqCst) {
                return Err(busy());
            }
            next.enabled = true;
            next.head_bytes = head.len();
            let entry = next.entry(reference)?;
            entry.generation.replace(entry.record.generation);
            self.index.write().map_err(lock_error)?.replace_web(
                next.entries.len(),
                retained,
                self.config,
            )?;
            *current = next.clone();
            writer.pending = None;
            Ok(())
        };
        let committed = staged.and_then(|()| {
            if positive {
                grant
                    .as_ref()
                    .ok_or_else(denied)?
                    .with_current(&mut |check| commit(Some(check)))
            } else {
                commit(None)
            }
        });
        if let Err(failure) = committed {
            if writer.pending.is_some() {
                self.web.epoch.retire();
                return Err(error(
                    PlatformErrorCode::Unavailable,
                    "web-mutation-uncertain-reopen-and-query-operation",
                ));
            }
            return Err(failure);
        }
        Ok(result)
    }
    fn web_payload_preflight(
        &self,
        payload: &Payload<'_>,
        reference: &PublicationRef,
        next: &mut State,
        writer: &PublicationState,
        content: &shared_content::SharedContent,
    ) -> Result<(), PlatformError> {
        match payload {
            Payload::Publication(prepared) => {
                let path = self.web_publication_path(&reference.id);
                if !path.try_exists().map_err(io_error)? {
                    if writer.release_directories >= self.config.max_recovery_directories {
                        return Err(capacity());
                    }
                    content.preflight(&reference.id, &prepared.content_files())?;
                } else if !prepared.same_upload(&self.web_storage(reference)?) {
                    return Err(corrupt("web-immutable-publication-conflict"));
                }
            }
            Payload::Evidence(prepared) => {
                let root = self.web_evidence_path(&prepared.digest);
                if root.try_exists().map_err(io_error)? {
                    // Exact digest and association validation, never replacement.
                    self.read_web_revision(
                        reference,
                        &prepared.digest,
                        &next.entry(reference)?.completion,
                    )?;
                } else {
                    next.evidence_directories = next
                        .evidence_directories
                        .checked_add(1)
                        .filter(|n| *n <= self.config.max_recovery_directories)
                        .ok_or_else(capacity)?;
                    next.evidence_bytes = next
                        .evidence_bytes
                        .checked_add(prepared.bytes)
                        .filter(|n| *n <= self.lifecycle_limits.max_total_evidence_bytes as u64)
                        .ok_or_else(capacity)?;
                }
            }
            Payload::None => {}
        }
        Ok(())
    }
    fn stage_web_payload(
        &self,
        payload: &Payload<'_>,
        reference: &PublicationRef,
        writer: &mut PublicationState,
        content: &mut shared_content::SharedContent,
    ) -> Result<(), PlatformError> {
        match payload {
            Payload::Publication(prepared) => {
                let destination = self.web_publication_path(&reference.id);
                if !destination.try_exists().map_err(io_error)? {
                    let staging = self
                        .root
                        .join(TEMP_DIR)
                        .join(format!("web-{}", reference.id.hex()));
                    fs::create_dir(&staging).map_err(io_error)?;
                    for (name, bytes) in prepared.content_files() {
                        content.link_bytes(&staging.join(name), bytes)?;
                    }
                    sync_dir(&staging)?;
                    let stored = storage::Stored::read(
                        &staging,
                        self.web_authority()?.limits,
                        self.config.max_component_bytes,
                    )?;
                    if !prepared.same_upload(&stored) {
                        return Err(corrupt("web-staging-changed"));
                    }
                    fs::rename(&staging, &destination).map_err(io_error)?;
                    writer.release_directories += 1;
                    sync_dir(
                        destination
                            .parent()
                            .ok_or_else(|| corrupt("web-publication-parent"))?,
                    )?;
                }
                content.register_directory(&reference.id, &destination)
            }
            Payload::Evidence(prepared) => {
                let destination = self.web_evidence_path(&prepared.digest);
                if !destination.try_exists().map_err(io_error)? {
                    prepared.stage(&destination)?;
                }
                Ok(())
            }
            Payload::None => Ok(()),
        }
    }
}
