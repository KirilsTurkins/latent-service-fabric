use super::*;
use crate::{
    ManagedPublicationUpload, ReleaseEvidenceUpload, ReleaseLifecycleAction,
    ReleaseLifecycleReason, ReleaseLifecycleRecord, ReleaseMutationContext,
    ReleaseOperationDisposition, ReleaseOperationPreview, ReleaseOperationReceipt,
};
use latent_core::{ArtifactBlobDigest, ErrorDetail, PackageDigest};
use sha2::{Digest, Sha256};
use std::sync::atomic::{AtomicU64, Ordering};

pub(super) type Preflight<'a> =
    dyn for<'p> FnMut(ReleaseOperationPreview<'p>) -> Result<(), PlatformError> + Send + 'a;

pub(super) struct Request {
    pub context: ReleaseMutationContext,
    pub operation_id: String,
    pub action: ReleaseLifecycleAction,
    pub digest: ArtifactBlobDigest,
    pub component: Option<ReleaseDigest>,
    pub package: Option<ArtifactBlobDigest>,
}
impl Request {
    pub fn new(
        context: ReleaseMutationContext,
        action: ReleaseLifecycleAction,
        component: Option<ReleaseDigest>,
        package: Option<ArtifactBlobDigest>,
        payload: ArtifactBlobDigest,
    ) -> Result<Self, PlatformError> {
        context.validate()?;
        if context.operation.is_none() && action != ReleaseLifecycleAction::Publish {
            return Err(error(
                PlatformErrorCode::InvalidArgument,
                "release-operation-required",
            ));
        }
        let operation_id = context
            .operation
            .as_ref()
            .map(|value| value.operation_id.clone())
            .unwrap_or_else(host_operation_id);
        let mut hash = Sha256::new();
        part(&mut hash, b"lsf-release-operation-v1");
        part(
            &mut hash,
            &serde_json::to_vec(&(&context.scope, &context.actor, action))
                .map_err(|_| corrupt("release-operation-encoding"))?,
        );
        part(&mut hash, operation_id.as_bytes());
        part(
            &mut hash,
            &context
                .operation
                .as_ref()
                .map(|value| value.expected_generation)
                .map(u64::to_le_bytes)
                .map(Vec::from)
                .unwrap_or_default(),
        );
        part(
            &mut hash,
            component.as_ref().map_or(b"", |value| value.0.as_bytes()),
        );
        part(
            &mut hash,
            package
                .as_ref()
                .map_or(b"", |value| value.as_str().as_bytes()),
        );
        part(&mut hash, payload.as_str().as_bytes());
        Ok(Self {
            context,
            operation_id,
            action,
            digest: finish(hash),
            component,
            package,
        })
    }
    pub fn receipt(
        &self,
        record: Option<ReleaseLifecycleRecord>,
        disposition: ReleaseOperationDisposition,
        reason: ReleaseLifecycleReason,
    ) -> ReleaseOperationReceipt {
        ReleaseOperationReceipt {
            operation_id: self.operation_id.clone(),
            request_digest: self.digest.clone(),
            scope: self.context.scope.clone(),
            actor: self.context.actor.clone(),
            action: self.action,
            disposition,
            reason,
            component_digest: self.component.clone(),
            package_manifest_digest: self.package.clone(),
            expected_generation: self
                .context
                .operation
                .as_ref()
                .map(|value| value.expected_generation),
            policy: record.as_ref().and_then(|value| value.policy.clone()),
            observed_at_unix_millis: record
                .as_ref()
                .and_then(|value| value.observed_at_unix_millis),
            record,
        }
    }
    pub fn check_generation(
        &self,
        old: Option<&ReleaseLifecycleRecord>,
    ) -> Result<(), PlatformError> {
        if self.context.operation.as_ref().is_some_and(|operation| {
            operation.expected_generation != old.map_or(0, |value| value.generation)
        }) {
            return Err(error(
                PlatformErrorCode::StateConflict,
                "release-generation-conflict",
            ));
        }
        Ok(())
    }
}

impl DirectoryArtifactRepository {
    pub(super) fn publication_request(
        &self,
        context: ReleaseMutationContext,
        upload: &ManagedPublicationUpload,
    ) -> Result<Request, PlatformError> {
        context.validate()?;
        let mut hash = Sha256::new();
        let (component, package) = match upload {
            ManagedPublicationUpload::Local(artifact) => {
                super::input::check(artifact, self.config)?;
                if artifact.component_bytes.capacity() > self.config.max_component_bytes {
                    return Err(resource_exhausted("publication-component-capacity"));
                }
                part(&mut hash, b"local");
                part(
                    &mut hash,
                    &encode_metadata(artifact, self.config.max_metadata_bytes)?,
                );
                part(
                    &mut hash,
                    &self.codec.encode_capsule(&artifact.manifest).map_err(|_| {
                        error(
                            PlatformErrorCode::InvalidArgument,
                            "capsule-manifest-encoding",
                        )
                    })?,
                );
                part(&mut hash, &artifact.component_bytes);
                (Some(crate::content_digest(&artifact.component_bytes)), None)
            }
            ManagedPublicationUpload::Package(upload) => {
                let limits = self
                    .admission
                    .as_ref()
                    .map_or_else(crate::AdmissionStorageLimits::default, |value| value.limits);
                limits.check_upload(upload, self.config.max_component_bytes)?;
                part(&mut hash, b"package");
                part(&mut hash, &upload.manifest);
                part(&mut hash, &upload.configuration);
                part(&mut hash, &(upload.layers.len() as u64).to_le_bytes());
                for (path, bytes) in &upload.layers {
                    part(&mut hash, path.as_bytes());
                    part(&mut hash, bytes);
                }
                hash_evidence(&mut hash, &upload.signatures);
                hash_evidence(&mut hash, &upload.provenance);
                hash_evidence(&mut hash, &upload.sboms);
                // Unverified manifest identity is diagnostic only. The component
                // identity is filled only after authority verification succeeds.
                (
                    None,
                    Some(crate::package::artifact_blob_digest(&upload.manifest)),
                )
            }
        };
        Request::new(
            context,
            ReleaseLifecycleAction::Publish,
            component,
            package,
            finish(hash),
        )
    }

    pub(super) fn replay(
        &self,
        request: &Request,
        preflight: &mut Preflight<'_>,
    ) -> Result<Option<ReleaseOperationReceipt>, PlatformError> {
        match self
            .life_store()
            .operation(&request.context.scope, &request.operation_id)?
        {
            crate::ReleaseOperationLookup::Found(receipt) => {
                if receipt.request_digest != request.digest {
                    return Err(error(
                        PlatformErrorCode::StateConflict,
                        "release-operation-id-conflict",
                    ));
                }
                let summary = if receipt.disposition == ReleaseOperationDisposition::Committed
                    && receipt.action == ReleaseLifecycleAction::Publish
                {
                    receipt.component_digest.as_ref().and_then(|release| {
                        self.index
                            .read()
                            .ok()?
                            .by_digest
                            .get(release)
                            .map(|entry| entry.value.clone())
                    })
                } else {
                    None
                };
                let failure = (receipt.disposition == ReleaseOperationDisposition::Rejected)
                    .then(|| rejected_error(&receipt));
                preflight(ReleaseOperationPreview {
                    receipt: &receipt,
                    release: summary.as_ref(),
                    failure: failure.as_ref(),
                })?;
                if let Some(failure) = failure {
                    return Err(failure);
                }
                Ok(Some(receipt))
            }
            crate::ReleaseOperationLookup::Unknown => Ok(None),
            crate::ReleaseOperationLookup::Uncertain => Err(operation_error(
                request,
                "uncertain",
                "mutation-uncertain",
                PlatformErrorCode::Unavailable,
                None,
            )),
        }
    }

    pub(super) fn reject_request(
        &self,
        request: &Request,
        failure: PlatformError,
        preflight: &mut Preflight<'_>,
    ) -> Result<PlatformError, PlatformError> {
        let reason = match failure.code {
            PlatformErrorCode::StateConflict => ReleaseLifecycleReason::GenerationConflict,
            PlatformErrorCode::PermissionDenied => ReleaseLifecycleReason::PolicyDenied,
            PlatformErrorCode::IncompatibleContract => ReleaseLifecycleReason::IncompatibleContract,
            PlatformErrorCode::AlreadyExists => ReleaseLifecycleReason::ContentConflict,
            PlatformErrorCode::CorruptArtifact => ReleaseLifecycleReason::IntegrityMismatch,
            // Capacity/transient I/O rejection is not a durable package judgement.
            PlatformErrorCode::Unavailable | PlatformErrorCode::Internal => {
                return Ok(operation_error(
                    request,
                    "uncertain",
                    "mutation-uncertain",
                    failure.code,
                    None,
                ))
            }
            PlatformErrorCode::ResourceExhausted => return Ok(failure),
            _ => ReleaseLifecycleReason::InvalidPackage,
        };
        let old = request
            .component
            .as_ref()
            .map(|release| self.life_store().record(release))
            .transpose()?
            .flatten();
        if old
            .as_ref()
            .is_some_and(|value| value.scope != request.context.scope)
        {
            return Ok(error(
                PlatformErrorCode::NotFound,
                "release digest not found",
            ));
        }
        let receipt = request.receipt(old, ReleaseOperationDisposition::Rejected, reason);
        let prepared = self.life_store().prepare(receipt, None)?;
        let failure = rejected_error(prepared.receipt());
        preflight(ReleaseOperationPreview {
            receipt: prepared.receipt(),
            release: None,
            failure: Some(&failure),
        })?;
        self.life_store().with_prepared(&prepared, &mut |fence| {
            fence.commit(&prepared)?;
            Ok(())
        })?;
        Ok(failure)
    }
}

pub(super) fn mutation_digest(
    release: &ReleaseDigest,
    package: Option<&PackageDigest>,
    reason: Option<crate::ReleaseLifecycleReason>,
    evidence: Option<&ReleaseEvidenceUpload>,
) -> ArtifactBlobDigest {
    let mut hash = Sha256::new();
    part(&mut hash, release.0.as_bytes());
    part(
        &mut hash,
        package.map_or(b"", |value| value.as_str().as_bytes()),
    );
    if let Some(reason) = reason {
        part(
            &mut hash,
            &serde_json::to_vec(&reason).expect("closed reason enum"),
        );
    }
    if let Some(evidence) = evidence {
        hash_evidence(&mut hash, &evidence.signatures);
        hash_evidence(&mut hash, &evidence.provenance);
        hash_evidence(&mut hash, &evidence.sboms);
    }
    finish(hash)
}
fn hash_evidence(hash: &mut Sha256, entries: &[crate::AdmissionEvidence]) {
    part(hash, &(entries.len() as u64).to_le_bytes());
    for value in entries {
        part(hash, &value.manifest);
        part(hash, &value.configuration);
        part(hash, &value.payload);
    }
}
fn part(hash: &mut Sha256, bytes: &[u8]) {
    hash.update((bytes.len() as u64).to_le_bytes());
    hash.update(bytes);
}
fn finish(hash: Sha256) -> ArtifactBlobDigest {
    crate::content_hash::format_digest(hash.finalize().into())
        .0
        .parse()
        .expect("canonical SHA-256")
}
fn host_operation_id() -> String {
    static SEQUENCE: AtomicU64 = AtomicU64::new(0);
    let sequence = SEQUENCE.fetch_add(1, Ordering::Relaxed);
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |value| value.as_nanos());
    format!("host-{}-{nanos}-{sequence}", std::process::id())
}
pub(super) fn observed_time() -> Option<u64> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .ok()
        .and_then(|value| value.as_millis().try_into().ok())
}
pub(super) fn rejected_error(receipt: &ReleaseOperationReceipt) -> PlatformError {
    let code = match receipt.reason {
        ReleaseLifecycleReason::GenerationConflict => PlatformErrorCode::StateConflict,
        ReleaseLifecycleReason::PolicyDenied
        | ReleaseLifecycleReason::EvidenceRejected
        | ReleaseLifecycleReason::ReleaseRevoked
        | ReleaseLifecycleReason::ReleaseRetired => PlatformErrorCode::PermissionDenied,
        ReleaseLifecycleReason::IncompatibleContract => PlatformErrorCode::IncompatibleContract,
        ReleaseLifecycleReason::IntegrityMismatch => PlatformErrorCode::CorruptArtifact,
        ReleaseLifecycleReason::ContentConflict => PlatformErrorCode::AlreadyExists,
        _ => PlatformErrorCode::InvalidArgument,
    };
    let reason = serde_json::to_value(receipt.reason).expect("closed reason enum");
    detailed_error(
        &receipt.operation_id,
        "rejected",
        reason.as_str().expect("reason string"),
        code,
        receipt.record.as_ref().map(|value| value.generation),
    )
}
pub(super) fn operation_error(
    request: &Request,
    disposition: &str,
    reason: &str,
    code: PlatformErrorCode,
    generation: Option<u64>,
) -> PlatformError {
    detailed_error(&request.operation_id, disposition, reason, code, generation)
}
fn detailed_error(
    id: &str,
    disposition: &str,
    reason: &str,
    code: PlatformErrorCode,
    generation: Option<u64>,
) -> PlatformError {
    let mut fields = latent_core::Metadata::new();
    fields.insert("operation_id".to_owned(), id.to_owned());
    fields.insert("disposition".to_owned(), disposition.to_owned());
    fields.insert("reason".to_owned(), reason.to_owned());
    if let Some(generation) = generation {
        fields.insert("generation".to_owned(), generation.to_string());
    }
    PlatformError {
        code,
        message: "release-operation-failed".to_owned(),
        retryable: disposition == "uncertain",
        details: vec![ErrorDetail {
            kind: "release-operation".to_owned(),
            fields,
        }],
    }
}
