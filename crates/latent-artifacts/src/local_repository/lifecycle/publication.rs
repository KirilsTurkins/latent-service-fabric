use super::request::{observed_time, Preflight, Request};
use super::*;
use crate::local_repository::admission_storage::PreparedAdmissionFiles;
use crate::{
    ArtifactCatalogEntry, ManagedPublicationReceipt, ManagedPublicationUpload, ReleaseActor,
    ReleaseActorKind, ReleaseEligibility, ReleaseLifecycleReason, ReleaseLifecycleRecord,
    ReleaseMutationContext, ReleaseOperationDisposition, ReleaseOperationPreview,
};

struct Candidate {
    publication: PreparedPublication,
    files: Option<PreparedAdmissionFiles>,
    proof: Option<ReleaseEligibility>,
    summary: ArtifactCatalogEntry,
    lifecycle: crate::lifecycle::LifecyclePrepared,
}
impl DirectoryArtifactRepository {
    pub(in crate::local_repository) fn managed_publish(
        &self,
        context: ReleaseMutationContext,
        upload: ManagedPublicationUpload,
        preflight: &mut Preflight<'_>,
    ) -> Result<ManagedPublicationReceipt, PlatformError> {
        self.managed_publish_inner(context, upload, preflight, false)
    }

    fn managed_publish_inner(
        &self,
        context: ReleaseMutationContext,
        upload: ManagedPublicationUpload,
        preflight: &mut Preflight<'_>,
        legacy_errors: bool,
    ) -> Result<ManagedPublicationReceipt, PlatformError> {
        let _work = self
            .admission_work
            .try_lock()
            .map_err(|_| resource_exhausted("admission-work-busy"))?;
        let mut request = self.publication_request(context, &upload)?;
        if let Some(operation) = self.replay(&request, preflight)? {
            let release = operation
                .component_digest
                .as_ref()
                .and_then(|release| {
                    self.index
                        .read()
                        .ok()?
                        .by_digest
                        .get(release)
                        .map(|value| value.value.clone())
                })
                .ok_or_else(|| corrupt("committed-publication-history-missing"))?;
            return Ok(ManagedPublicationReceipt { release, operation });
        }
        let candidate = match self.publication_candidate(&mut request, upload) {
            Ok(candidate) => candidate,
            Err(failure) => {
                let original = legacy_errors.then(|| failure.clone());
                let recorded = self.reject_request(&request, failure, preflight)?;
                return Err(original.unwrap_or(recorded));
            }
        };
        // The exact success DTO must fit before staging, receipts or payload I/O.
        preflight(ReleaseOperationPreview {
            replay: false,
            receipt: candidate.lifecycle.receipt(),
            release: Some(&candidate.summary),
            failure: None,
        })?;
        let destination =
            self.entry_path(&candidate.publication.artifact.descriptor.release_digest)?;
        let staged = if destination.exists() {
            None
        } else {
            Some(Staged(self.stage_publication_with_admission(
                &candidate.publication,
                candidate.files.as_ref(),
            )?))
        };
        let Candidate {
            publication,
            files,
            proof,
            summary,
            lifecycle,
        } = candidate;
        let expected = publication.completion;
        // All payload ownership is released before the second streamed read.
        drop(publication.artifact);
        drop(publication.metadata_bytes);
        drop(publication.manifest_bytes);
        drop(files);
        let result = self.life_store().with_prepared(&lifecycle, &mut |fence| {
            if let Some(proof) = &proof {
                proof.with_current(&mut |check| {
                    self.commit_publication(
                        &destination,
                        staged.as_ref().map(|value| value.0.as_path()),
                        &expected,
                        Some(proof),
                        &lifecycle,
                        fence,
                        &mut || check.check(),
                    )
                })
            } else {
                self.commit_publication(
                    &destination,
                    staged.as_ref().map(|value| value.0.as_path()),
                    &expected,
                    None,
                    &lifecycle,
                    fence,
                    &mut || Ok(()),
                )
            }
        });
        if let Err(failure) = result {
            if legacy_errors {
                return Err(failure);
            }
            return Err(request::operation_error(
                &request,
                "uncertain",
                "mutation-uncertain",
                failure.code,
                None,
            ));
        }
        Ok(ManagedPublicationReceipt {
            release: summary,
            operation: lifecycle.receipt().clone(),
        })
    }

    fn publication_candidate(
        &self,
        request: &mut Request,
        upload: ManagedPublicationUpload,
    ) -> Result<Candidate, PlatformError> {
        let (artifact, files, mut proof) = match upload {
            ManagedPublicationUpload::Local(artifact) => {
                if self.admission.is_some() {
                    return Err(error(
                        PlatformErrorCode::PermissionDenied,
                        "raw-publication-disabled-in-enforced-mode",
                    ));
                }
                let scope = artifact
                    .manifest
                    .metadata
                    .tenant
                    .clone()
                    .map_or(LifecycleScope::LocalUnscoped, LifecycleScope::Tenant);
                if scope != request.context.scope {
                    return Err(error(
                        PlatformErrorCode::PermissionDenied,
                        "publication-tenant-mismatch",
                    ));
                }
                (artifact, None, None)
            }
            ManagedPublicationUpload::Package(upload) => {
                let config = self.admission.as_ref().ok_or_else(|| {
                    error(
                        PlatformErrorCode::PermissionDenied,
                        "package-admission-not-configured",
                    )
                })?;
                let tenant = request.context.scope.tenant().ok_or_else(|| {
                    error(
                        PlatformErrorCode::PermissionDenied,
                        "package-tenant-required",
                    )
                })?;
                let verified = config.authority.verify(tenant, upload)?;
                self.validate_verified(tenant, &verified)?;
                request.component = Some(verified.grant.binding().release.clone());
                request.package = Some(
                    verified
                        .grant
                        .binding()
                        .package
                        .as_str()
                        .parse()
                        .map_err(|_| corrupt("verified-package-identity"))?,
                );
                let files = PreparedAdmissionFiles::prepare(
                    verified.grant.binding(),
                    verified.upload,
                    &verified.artifact,
                    config.limits,
                    self.config.max_component_bytes,
                )?;
                (
                    verified.artifact,
                    Some(files),
                    Some(ReleaseEligibility::new(
                        verified.grant,
                        Arc::clone(&config.owner),
                    )),
                )
            }
        };
        let mut publication = self.prepare_publication(artifact)?;
        let release = publication.artifact.descriptor.release_digest.clone();
        request.component = Some(release.clone());
        let old = self.life_store().record(&release)?;
        request.check_generation(old.as_ref())?;
        if old
            .as_ref()
            .is_some_and(|row| row.scope != request.context.scope)
        {
            return Err(error(
                PlatformErrorCode::NotFound,
                "release digest not found",
            ));
        }
        if old
            .as_ref()
            .is_some_and(|row| row.state != ReleaseLifecycleState::Admitted)
        {
            return Err(error(
                PlatformErrorCode::PermissionDenied,
                "release-lifecycle-ineligible",
            ));
        }
        let destination = self.entry_path(&release)?;
        if destination.exists() {
            let existing = self.load_complete_entry(&destination, Retention::Metadata)?;
            if !publication.completion.same_artifact(&existing.completion)
                || files.as_ref().is_some_and(|files| {
                    existing
                        .admission
                        .as_ref()
                        .is_none_or(|stored| !files.same_upload(stored))
                })
            {
                return Err(error(
                    PlatformErrorCode::AlreadyExists,
                    "release contains different package or evidence",
                ));
            }
            if proof.is_some() {
                proof = if old
                    .as_ref()
                    .is_some_and(|row| row.evidence_revision_digest.is_some())
                {
                    self.recover_selected_evidence(&destination, &existing)?
                } else {
                    self.recover_eligibility(&destination, &existing)?
                        .and_then(|value| value.eligibility)
                };
                if proof.is_none() {
                    return Err(error(
                        PlatformErrorCode::PermissionDenied,
                        "retained-admission-is-not-current",
                    ));
                }
            }
            publication.completion = existing.completion;
        } else if let Some(files) = &files {
            publication.completion.bind_admission(&files.record_bytes);
        }
        let identity = LifecycleIdentity {
            scope: request.context.scope.clone(),
            release: release.clone(),
            package: proof.as_ref().map(|value| value.package().clone()),
            completion: publication.completion.identity()?,
        };
        // Reserve every bounded resource logically before the response callback
        // or staging filesystem access. The one admission-work slot serializes
        // publication, renewal and lifecycle mutations through final adoption.
        {
            let publication_state = self.publish_lock.lock().map_err(lock_error)?;
            if publication_state
                .pending
                .as_ref()
                .is_some_and(|pending| pending != &release)
            {
                return Err(error(PlatformErrorCode::Unavailable, "catalog needs publication recovery: retry the pending release or reopen the root"));
            }
            if !destination.exists()
                && publication_state.release_directories >= self.config.max_recovery_directories
            {
                return Err(resource_exhausted(
                    "catalog recovery directory capacity reached",
                ));
            }
        }
        if let Some(proof) = &proof {
            let original = if destination.exists() {
                self.load_complete_entry(&destination, Retention::Metadata)?
                    .admission
                    .ok_or_else(|| corrupt("admission-record-missing"))?
                    .binding(
                        &destination,
                        self.admission.as_ref().expect("enforced mode").limits,
                    )?
            } else {
                proof.binding().clone()
            };
            self.index.read().map_err(lock_error)?.preflight_admission(
                &publication.artifact.descriptor,
                &publication.artifact.manifest,
                &original,
                identity.completion,
                proof.retained_bytes(),
                self.config,
            )?;
        }
        let record = old.unwrap_or_else(|| ReleaseLifecycleRecord {
            scope: request.context.scope.clone(),
            release,
            package: identity.package.clone(),
            state: ReleaseLifecycleState::Admitted,
            generation: 1,
            actor: request.context.actor.clone(),
            reason: ReleaseLifecycleReason::Admitted,
            operation_id: request.operation_id.clone(),
            policy: proof
                .as_ref()
                .and_then(|value| value.grant.policy_identity()),
            observed_at_unix_millis: observed_time(),
            evidence_revision_digest: None,
        });
        let receipt = request.receipt(
            Some(record),
            ReleaseOperationDisposition::Committed,
            ReleaseLifecycleReason::Admitted,
        );
        let lifecycle = self.life_store().prepare(receipt, Some(identity))?;
        let artifact = &publication.artifact;
        let summary = ArtifactCatalogEntry {
            descriptor: artifact.descriptor.clone(),
            tenant: artifact.manifest.metadata.tenant.clone(),
            service: latent_core::ServiceId(artifact.manifest.metadata.name.clone()),
            semantic_version: artifact.manifest.semantic_version.clone(),
            world: artifact.manifest.world.clone(),
        };
        Ok(Candidate {
            publication,
            files,
            proof,
            summary,
            lifecycle,
        })
    }

    #[allow(clippy::too_many_arguments)]
    fn commit_publication(
        &self,
        destination: &Path,
        staged: Option<&Path>,
        expected: &CompletionRecord,
        proof: Option<&ReleaseEligibility>,
        prepared: &crate::lifecycle::LifecyclePrepared,
        fence: &crate::lifecycle::LifecycleFence<'_>,
        check: &mut dyn FnMut() -> Result<(), PlatformError>,
    ) -> Result<(), PlatformError> {
        let release = prepared
            .receipt()
            .component_digest
            .as_ref()
            .ok_or_else(|| corrupt("publication-release-missing"))?;
        let mut publication = self.publish_lock.lock().map_err(lock_error)?;
        if publication
            .pending
            .as_ref()
            .is_some_and(|pending| pending != release)
        {
            return Err(error(
                PlatformErrorCode::Unavailable,
                "catalog-needs-pending-publication-recovery",
            ));
        }
        check()?;
        if let Some(staged) = staged {
            if destination.exists() {
                return Err(error(
                    PlatformErrorCode::StateConflict,
                    "concurrent-publication-retry-required",
                ));
            }
            if publication.release_directories >= self.config.max_recovery_directories {
                return Err(resource_exhausted(
                    "catalog recovery directory capacity reached",
                ));
            }
            fs::rename(staged, destination).map_err(io_error)?;
            publication.release_directories += 1;
            publication.pending = Some(release.clone());
            #[cfg(test)]
            integrity::faults::after_rename(destination);
        }
        publication.pending = Some(release.clone());
        let verified = self.load_complete_entry(destination, Retention::Metadata)?;
        if &verified.completion != expected {
            return Err(corrupt("publication-completion-changed"));
        }
        #[cfg(test)]
        if self
            .fail_parent_sync_once
            .swap(false, std::sync::atomic::Ordering::SeqCst)
        {
            return Err(error(
                PlatformErrorCode::Internal,
                "injected parent-directory sync failure after rename",
            ));
        }
        sync_dir(&self.root.join(RELEASES_DIR))?;
        let stamp = self.preparation_stamp(&verified.metadata);
        let original_binding = verified
            .admission
            .as_ref()
            .map(|stored| {
                stored.binding(
                    destination,
                    self.admission.as_ref().expect("enforced storage").limits,
                )
            })
            .transpose()?;
        let index = self.index.read().map_err(lock_error)?;
        if let Some(binding) = &original_binding {
            index.preflight_admission(
                verified.metadata.descriptor(),
                verified.metadata.manifest(),
                binding,
                expected.identity()?,
                proof.map_or(0, ReleaseEligibility::retained_bytes),
                self.config,
            )?;
        } else {
            index.preflight(
                verified.metadata.descriptor(),
                verified.metadata.manifest(),
                self.config,
            )?;
        }
        drop(index);
        check()?;
        fence.commit(prepared)?;
        let mut index = self.index.write().map_err(lock_error)?;
        check()?;
        if let Some(binding) = original_binding {
            index.insert_admitted(
                verified.metadata,
                stamp,
                binding,
                None,
                expected.identity()?,
                self.config,
            )?;
            index.install_selected_eligibility(
                release,
                proof.cloned(),
                expected.identity()?,
                self.config,
            )?;
        } else {
            index.insert_verified(verified.metadata, stamp, self.config)?;
        }
        publication.pending = None;
        Ok(())
    }

    pub(in crate::local_repository) fn publish_legacy(
        &self,
        artifact: CapsuleArtifact,
    ) -> Result<ArtifactDescriptor, PlatformError> {
        let scope = artifact
            .manifest
            .metadata
            .tenant
            .clone()
            .map_or(LifecycleScope::LocalUnscoped, LifecycleScope::Tenant);
        let context = ReleaseMutationContext {
            scope,
            actor: ReleaseActor {
                subject: "trusted-local-host".to_owned(),
                kind: ReleaseActorKind::Host,
            },
            operation: None,
        };
        self.managed_publish_inner(
            context,
            ManagedPublicationUpload::Local(artifact),
            &mut |_| Ok(()),
            true,
        )
        .map(|value| value.release.descriptor)
    }
    pub(in crate::local_repository) fn admit_legacy(
        &self,
        tenant: &latent_core::TenantId,
        upload: crate::PackageAdmissionUpload,
        preflight: &mut (dyn FnMut(&ArtifactCatalogEntry) -> Result<(), PlatformError> + Send),
    ) -> Result<ArtifactCatalogEntry, PlatformError> {
        let context = ReleaseMutationContext {
            scope: LifecycleScope::Tenant(tenant.clone()),
            actor: ReleaseActor {
                subject: "authenticated-host-adapter".to_owned(),
                kind: ReleaseActorKind::Host,
            },
            operation: None,
        };
        self.managed_publish_inner(
            context,
            ManagedPublicationUpload::Package(upload),
            &mut |preview| {
                if let Some(summary) = preview.release {
                    preflight(summary)?;
                }
                Ok(())
            },
            true,
        )
        .map(|value| value.release)
    }
}
struct Staged(PathBuf);
impl Drop for Staged {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}
