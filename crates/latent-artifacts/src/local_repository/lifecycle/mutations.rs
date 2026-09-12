use super::request::{mutation_digest, observed_time, Preflight, Request};
use super::*;
use crate::{
    ReleaseEligibility, ReleaseEvidenceUpload, ReleaseLifecycleAction, ReleaseLifecycleReason,
    ReleaseMutationContext, ReleaseOperationDisposition, ReleaseOperationPreview,
    ReleaseOperationReceipt,
};
use latent_core::PackageDigest;

impl DirectoryArtifactRepository {
    pub(in crate::local_repository) fn change_lifecycle(
        &self,
        context: ReleaseMutationContext,
        release: &ReleaseDigest,
        action: ReleaseLifecycleAction,
        reason: ReleaseLifecycleReason,
        preflight: &mut Preflight<'_>,
    ) -> Result<ReleaseOperationReceipt, PlatformError> {
        validate_release(release)?;
        let _work = self
            .admission_work
            .try_lock()
            .map_err(|_| resource_exhausted("admission-work-busy"))?;
        let valid = match action {
            ReleaseLifecycleAction::Revoke => matches!(
                reason,
                ReleaseLifecycleReason::OperatorRevocation
                    | ReleaseLifecycleReason::SecurityIncident
                    | ReleaseLifecycleReason::CorruptContent
            ),
            ReleaseLifecycleAction::Retire => matches!(
                reason,
                ReleaseLifecycleReason::OperatorRetirement
                    | ReleaseLifecycleReason::Superseded
                    | ReleaseLifecycleReason::EndOfSupport
            ),
            _ => false,
        };
        if !valid {
            return Err(error(
                PlatformErrorCode::InvalidArgument,
                "release-lifecycle-action-reason",
            ));
        }
        let mut request = Request::new(
            context,
            action,
            Some(release.clone()),
            None,
            mutation_digest(release, None, Some(reason), None),
        )?;
        if let Some(receipt) = self.replay(&request, preflight)? {
            return Ok(receipt);
        }
        let prepared = match (|| {
            let mut old = self.scoped_record(&request)?;
            request.package = old
                .package
                .as_ref()
                .map(|value| value.as_str().parse().expect("canonical package digest"));
            request.check_generation(Some(&old))?;
            if old.state == ReleaseLifecycleState::Retired
                || (action == ReleaseLifecycleAction::Revoke
                    && old.state != ReleaseLifecycleState::Admitted)
            {
                return Err(error(
                    PlatformErrorCode::PermissionDenied,
                    "release-lifecycle-terminal-state",
                ));
            }
            old.generation = old
                .generation
                .checked_add(1)
                .ok_or_else(|| resource_exhausted("release-generation-exhausted"))?;
            old.state = if action == ReleaseLifecycleAction::Revoke {
                ReleaseLifecycleState::Revoked
            } else {
                ReleaseLifecycleState::Retired
            };
            old.actor = request.context.actor.clone();
            old.operation_id = request.operation_id.clone();
            old.reason = reason;
            // Negative decisions require neither a fresh signing proof nor a
            // healthy verification clock. Previous policy is historical only.
            old.observed_at_unix_millis = observed_time();
            self.life_store().prepare(
                request.receipt(Some(old), ReleaseOperationDisposition::Committed, reason),
                None,
            )
        })() {
            Ok(prepared) => prepared,
            Err(failure) if failure.code == PlatformErrorCode::NotFound => return Err(failure),
            Err(failure) => return Err(self.reject_request(&request, failure, preflight)?),
        };
        preflight(ReleaseOperationPreview {
            replay: false,
            receipt: prepared.receipt(),
            release: None,
            failure: None,
        })?;
        self.life_store()
            .with_prepared(&prepared, &mut |fence| {
                fence.commit(&prepared)?;
                Ok(())
            })
            .map_err(|failure| {
                request::operation_error(
                    &request,
                    "uncertain",
                    "mutation-uncertain",
                    failure.code,
                    None,
                )
            })?;
        Ok(prepared.receipt().clone())
    }

    pub(in crate::local_repository) fn renew_evidence(
        &self,
        context: ReleaseMutationContext,
        release: &ReleaseDigest,
        package: &PackageDigest,
        evidence: ReleaseEvidenceUpload,
        preflight: &mut Preflight<'_>,
    ) -> Result<ReleaseOperationReceipt, PlatformError> {
        validate_release(release)?;
        let _work = self
            .admission_work
            .try_lock()
            .map_err(|_| resource_exhausted("admission-work-busy"))?;
        // Validate typed capacity/counts before request hashing and package I/O.
        evidence::check_input(
            &evidence,
            self.admission
                .as_ref()
                .map_or_else(crate::AdmissionStorageLimits::default, |value| value.limits),
            self.life_store().limits().max_evidence_revision_bytes,
        )?;
        let request = Request::new(
            context,
            ReleaseLifecycleAction::RenewEvidence,
            Some(release.clone()),
            Some(package.as_str().parse().expect("canonical package digest")),
            mutation_digest(release, Some(package), None, Some(&evidence)),
        )?;
        if let Some(receipt) = self.replay(&request, preflight)? {
            return Ok(receipt);
        }
        let candidate = (|| {
            let mut record = self.scoped_record(&request)?;
            request.check_generation(Some(&record))?;
            if record.state != ReleaseLifecycleState::Admitted {
                return Err(error(
                    PlatformErrorCode::PermissionDenied,
                    "release-lifecycle-ineligible",
                ));
            }
            if record.package.as_ref() != Some(package) {
                return Err(error(
                    PlatformErrorCode::PermissionDenied,
                    "renewal-package-mismatch",
                ));
            }
            let verified = self.verify_new_evidence(release, package, evidence)?;
            let identity = self
                .life_store()
                .identity(release)?
                .ok_or_else(|| corrupt("lifecycle-identity-missing"))?;
            let upload = verified.upload;
            let raw = ReleaseEvidenceUpload {
                signatures: upload.signatures,
                provenance: upload.provenance,
                sboms: upload.sboms,
            };
            let revision = crate::lifecycle::LifecycleEvidence::prepare(
                &identity,
                verified.grant.binding(),
                raw,
                self.life_store().limits(),
            )?;
            record.generation = record
                .generation
                .checked_add(1)
                .ok_or_else(|| resource_exhausted("release-generation-exhausted"))?;
            record.actor = request.context.actor.clone();
            record.operation_id = request.operation_id.clone();
            record.reason = ReleaseLifecycleReason::EvidenceRenewed;
            record.evidence_revision_digest = Some(revision.digest().clone());
            record.policy = verified.grant.policy_identity();
            record.observed_at_unix_millis = observed_time();
            let proof = ReleaseEligibility::new(
                verified.grant,
                Arc::clone(
                    &self
                        .admission
                        .as_ref()
                        .expect("verified enforced mode")
                        .owner,
                ),
            );
            self.index
                .read()
                .map_err(lock_error)?
                .eligibility_capacity(release, proof.retained_bytes(), self.config)?;
            let prepared = self.life_store().prepare(
                request.receipt(
                    Some(record),
                    ReleaseOperationDisposition::Committed,
                    ReleaseLifecycleReason::EvidenceRenewed,
                ),
                None,
            )?;
            Ok((prepared, revision, proof, identity.completion))
        })();
        let (prepared, revision, proof, completion) = match candidate {
            Ok(candidate) => candidate,
            Err(failure) if failure.code == PlatformErrorCode::NotFound => return Err(failure),
            Err(failure) => return Err(self.reject_request(&request, failure, preflight)?),
        };
        preflight(ReleaseOperationPreview {
            replay: false,
            receipt: prepared.receipt(),
            release: None,
            failure: None,
        })?;
        self.life_store().reclaim_evidence()?;
        self.life_store().stage_evidence(&revision)?;
        self.life_store()
            .with_prepared(&prepared, &mut |fence| {
                proof.with_current(&mut |check| {
                    let _writer = self.publish_lock.lock().map_err(lock_error)?;
                    self.index
                        .read()
                        .map_err(lock_error)?
                        .eligibility_capacity(release, proof.retained_bytes(), self.config)?;
                    check.check()?;
                    fence.commit(&prepared)?;
                    check.check()?;
                    self.index
                        .write()
                        .map_err(lock_error)?
                        .install_selected_eligibility(
                            release,
                            Some(proof.clone()),
                            completion,
                            self.config,
                        )
                })
            })
            .map_err(|failure| {
                request::operation_error(
                    &request,
                    "uncertain",
                    "mutation-uncertain",
                    failure.code,
                    None,
                )
            })?;
        // A retained receipt still reports the committed decision if reclamation
        // later encounters an I/O failure; reclamation never undoes permission.
        self.life_store().reclaim_evidence().map_err(|failure| {
            request::operation_error(
                &request,
                "committed",
                "evidence-reclamation-pending",
                failure.code,
                prepared
                    .receipt()
                    .record
                    .as_ref()
                    .map(|value| value.generation),
            )
        })?;
        Ok(prepared.receipt().clone())
    }

    fn scoped_record(
        &self,
        request: &Request,
    ) -> Result<crate::ReleaseLifecycleRecord, PlatformError> {
        self.life_store()
            .record(
                request
                    .component
                    .as_ref()
                    .ok_or_else(|| corrupt("operation-release-missing"))?,
            )?
            .filter(|value| value.scope == request.context.scope)
            .ok_or_else(|| error(PlatformErrorCode::NotFound, "release digest not found"))
    }
}

fn validate_release(release: &ReleaseDigest) -> Result<(), PlatformError> {
    if release.0.len() != 71
        || release.0.capacity() > 71
        || release
            .0
            .parse::<latent_core::ArtifactBlobDigest>()
            .is_err()
    {
        return Err(error(
            PlatformErrorCode::InvalidArgument,
            "release-digest-required",
        ));
    }
    Ok(())
}
