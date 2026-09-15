mod commit;
mod request;
use super::{
    busy, capacity, corrupt, denied, error, evidence, fs, io_error, lock_error, persistence,
    recovery, shared_content, storage, sync_dir, Arc, ArtifactBlobDigest,
    DirectoryArtifactRepository, Entry, LifecycleScope, PlatformError, PlatformErrorCode,
    PublicationRef, PublicationState, ReleaseLifecycleState, State, WebGeneration,
    WebLifecycleRecord, WebMutationResult, WebOperationReceipt, HEAD, TEMP_DIR,
};
use crate::{
    PackageAdmissionUpload, ReleaseEvidenceUpload, ReleaseLifecycleAction, ReleaseLifecycleReason,
    ReleaseMutationContext, ReleaseOperationDisposition,
};
use commit::Payload;

type Preflight<'a> = dyn FnMut(&WebMutationResult) -> Result<(), PlatformError> + 'a;

impl DirectoryArtifactRepository {
    /// Trusted host entry point. Authenticate/authorize the scope and actor before
    /// calling; preflight reserves the exact management response before any write.
    pub fn publish_web_package(
        &self,
        context: ReleaseMutationContext,
        upload: PackageAdmissionUpload,
        preflight: &mut Preflight<'_>,
    ) -> Result<WebMutationResult, PlatformError> {
        let _work = self.admission_work.try_lock().map_err(|_| busy())?;
        let config = self.web_authority()?;
        context.validate()?;
        config.limits.check_upload(
            &upload,
            storage::renderer_limit(self.config.max_component_bytes)?,
        )?;
        let package = crate::package::package_digest(&upload.manifest);
        let reference = PublicationRef::package(context.scope.clone(), &package)?;
        let receipt = request::receipt(
            &context,
            &reference,
            ReleaseLifecycleAction::Publish,
            ReleaseLifecycleReason::Admitted,
            &request::upload_digest(&upload),
        )?;
        let _epoch = self.web.epoch.write()?;
        let mut state = self.web.state.try_write().map_err(|_| busy())?;
        if let Some(replay) = state.check_receipt(&receipt)? {
            preflight(&replay)?;
            return Ok(replay);
        }
        request::check_generation(&state, &receipt)?;
        if receipt.expected_generation != 0 {
            return Err(error(
                PlatformErrorCode::AlreadyExists,
                "web-publication-already-exists",
            ));
        }
        let tenant = context.scope.tenant().ok_or_else(denied)?;
        let value = config.authority.verify_web(tenant, upload)?;
        self.check_web_grant(tenant, &value)?;
        let prepared = storage::Prepared::new(
            reference.clone(),
            value.grant.binding(),
            value.upload,
            &value.layout,
            config.limits,
            self.config.max_component_bytes,
        )?;
        let completion = if self
            .web_publication_path(&reference.id)
            .try_exists()
            .map_err(io_error)?
        {
            let original = self.web_storage(&reference)?;
            if !prepared.same_upload(&original) {
                return Err(corrupt("web-immutable-publication-conflict"));
            }
            original.digest()?
        } else {
            prepared.record.digest()?
        };
        let record = WebLifecycleRecord {
            publication: reference,
            package,
            manifest: value.layout.manifest_digest().clone(),
            assets: value.layout.assets_digest().clone(),
            state: ReleaseLifecycleState::Admitted,
            generation: 1,
            actor: context.actor,
            reason: ReleaseLifecycleReason::Admitted,
            operation_id: receipt.operation_id.clone(),
            evidence_revision: None,
        };
        let entry = Entry {
            record,
            completion,
            layout: Arc::new(value.layout),
            grant: Some(value.grant),
            generation: Arc::new(WebGeneration::new(1)),
        };
        let next = request::updated(
            &state,
            &receipt,
            entry,
            self.lifecycle_limits.max_recent_operations,
        );
        self.commit_web(
            &mut state,
            next,
            &receipt,
            Payload::Publication(&prepared),
            preflight,
        )
    }
    /// Revocation and retirement are terminal for this scoped immutable package.
    /// Rollback selects another exact still-eligible publication; it cannot undo
    /// either transition or borrow a grant from a package sharing its renderer.
    pub fn transition_web_publication(
        &self,
        context: ReleaseMutationContext,
        reference: &PublicationRef,
        action: ReleaseLifecycleAction,
        reason: ReleaseLifecycleReason,
        preflight: &mut Preflight<'_>,
    ) -> Result<WebMutationResult, PlatformError> {
        let _work = self.admission_work.try_lock().map_err(|_| busy())?;
        let target = match (action, reason) {
            (
                ReleaseLifecycleAction::Revoke,
                ReleaseLifecycleReason::OperatorRevocation
                | ReleaseLifecycleReason::SecurityIncident
                | ReleaseLifecycleReason::CorruptContent,
            ) => ReleaseLifecycleState::Revoked,
            (
                ReleaseLifecycleAction::Retire,
                ReleaseLifecycleReason::Superseded
                | ReleaseLifecycleReason::EndOfSupport
                | ReleaseLifecycleReason::OperatorRetirement,
            ) => ReleaseLifecycleState::Retired,
            _ => {
                return Err(error(
                    PlatformErrorCode::InvalidArgument,
                    "web-lifecycle-transition",
                ))
            }
        };
        let receipt = request::receipt(
            &context,
            reference,
            action,
            reason,
            &crate::package::artifact_blob_digest(b"web-terminal-transition-v1"),
        )?;
        let _epoch = self.web.epoch.write()?;
        let mut state = self.web.state.try_write().map_err(|_| busy())?;
        if let Some(replay) = state.check_receipt(&receipt)? {
            preflight(&replay)?;
            return Ok(replay);
        }
        request::check_generation(&state, &receipt)?;
        let mut entry = state.entry(reference)?.clone();
        if entry.record.state != ReleaseLifecycleState::Admitted {
            return Err(denied());
        }
        entry.record.state = target;
        entry.record.generation = receipt.resulting_generation;
        entry.record.actor = context.actor;
        entry.record.reason = reason;
        entry.record.operation_id.clone_from(&receipt.operation_id);
        entry.grant = None;
        let next = request::updated(
            &state,
            &receipt,
            entry,
            self.lifecycle_limits.max_recent_operations,
        );
        self.commit_web(&mut state, next, &receipt, Payload::None, preflight)
    }
    pub fn renew_web_evidence(
        &self,
        context: ReleaseMutationContext,
        reference: &PublicationRef,
        evidence: ReleaseEvidenceUpload,
        preflight: &mut Preflight<'_>,
    ) -> Result<WebMutationResult, PlatformError> {
        let _work = self.admission_work.try_lock().map_err(|_| busy())?;
        context.validate()?;
        if context.scope != reference.scope {
            return Err(denied());
        }
        let _epoch = self.web.epoch.write()?;
        let mut state = self.web.state.try_write().map_err(|_| busy())?;
        let mut entry = state.entry(reference)?.clone();
        let config = self.web_authority()?;
        // Validate supplied evidence bounds before allocating the retained package.
        config.limits.check_evidence(&evidence)?;
        let stored = self.web_storage(reference)?;
        if stored.digest()? != entry.completion {
            return Err(corrupt("web-retained-content-changed"));
        }
        let mut upload = stored.upload(
            &self.web_publication_path(&reference.id),
            config.limits,
            self.config.max_component_bytes,
        )?;
        upload.signatures = evidence.signatures;
        upload.provenance = evidence.provenance;
        upload.sboms = evidence.sboms;
        let receipt = request::receipt(
            &context,
            reference,
            ReleaseLifecycleAction::RenewEvidence,
            ReleaseLifecycleReason::EvidenceRenewed,
            &request::upload_digest(&upload),
        )?;
        if let Some(replay) = state.check_receipt(&receipt)? {
            preflight(&replay)?;
            return Ok(replay);
        }
        request::check_generation(&state, &receipt)?;
        if entry.record.state != ReleaseLifecycleState::Admitted {
            return Err(denied());
        }
        let tenant = context.scope.tenant().ok_or_else(denied)?;
        let value = config.authority.verify_web(tenant, upload)?;
        self.check_web_grant(tenant, &value)?;
        if value.layout != *entry.layout {
            return Err(corrupt("web-renewal-package-changed"));
        }
        entry.grant = Some(Arc::clone(&value.grant));
        let prepared = evidence::PreparedEvidence::new(
            reference,
            &entry.completion,
            value,
            config.limits,
            self.lifecycle_limits.max_evidence_revision_bytes,
        )?;
        entry.record.evidence_revision = Some(prepared.digest.clone());
        entry.record.generation = receipt.resulting_generation;
        entry.record.reason = receipt.reason;
        entry.record.actor = context.actor;
        entry.record.operation_id.clone_from(&receipt.operation_id);
        let next = request::updated(
            &state,
            &receipt,
            entry,
            self.lifecycle_limits.max_recent_operations,
        );
        self.commit_web(
            &mut state,
            next,
            &receipt,
            Payload::Evidence(&prepared),
            preflight,
        )
    }
    /// Bounded proof refresh over the selected original/renewed raw evidence.
    /// This changes no durable history and cannot revive a terminal publication.
    pub fn reverify_web_publication(
        &self,
        reference: &PublicationRef,
    ) -> Result<(), PlatformError> {
        let _work = self.admission_work.try_lock().map_err(|_| busy())?;
        let _epoch = self.web.epoch.write()?;
        let mut state = self.web.state.try_write().map_err(|_| busy())?;
        let mut next = state.clone();
        let entry = next
            .entries
            .get_mut(&reference.id)
            .filter(|entry| entry.record.publication == *reference)
            .ok_or_else(denied)?;
        if entry.record.state != ReleaseLifecycleState::Admitted {
            return Err(denied());
        }
        let config = self.web_authority()?;
        let upload = if let Some(revision) = &entry.record.evidence_revision {
            self.read_web_revision(reference, revision, &entry.completion)?
                .1
        } else {
            let stored = self.web_storage(reference)?;
            if stored.digest()? != entry.completion {
                return Err(corrupt("web-retained-content-changed"));
            }
            stored.upload(
                &self.web_publication_path(&reference.id),
                config.limits,
                self.config.max_component_bytes,
            )?
        };
        let value = config
            .authority
            .verify_web(reference.scope.tenant().ok_or_else(denied)?, upload)?;
        self.check_web_grant(reference.scope.tenant().ok_or_else(denied)?, &value)?;
        if value.layout != *entry.layout {
            return Err(corrupt("web-reverification-association"));
        }
        let grant = Arc::clone(&value.grant);
        entry.grant = Some(value.grant);
        let writer = self.publish_lock.try_lock().map_err(|_| busy())?;
        if writer.pending.is_some() {
            return Err(busy());
        }
        let retained = next.retained_bytes()?;
        grant.with_current(&mut |check| {
            check.check()?;
            self.index.write().map_err(lock_error)?.replace_web(
                next.entries.len(),
                retained,
                self.config,
            )?;
            *state = next.clone();
            Ok(())
        })
    }
    pub fn web_operation_status(
        &self,
        scope: &LifecycleScope,
        operation: &str,
    ) -> Result<Option<WebOperationReceipt>, PlatformError> {
        scope.validate()?;
        crate::ReleaseOperationPrecondition {
            operation_id: operation.into(),
            expected_generation: 0,
        }
        .validate()?;
        self.web.epoch.check()?;
        let state = self.web.state.try_read().map_err(|_| busy())?;
        Ok(state
            .receipts
            .iter()
            .find(|receipt| {
                &receipt.publication.scope == scope && receipt.operation_id == operation
            })
            .cloned())
    }
}
