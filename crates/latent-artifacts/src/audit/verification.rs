use std::sync::Arc;

use latent_audit::{
    AuditActorIdentity, AuditActorKind, AuditHandle, AuditIdentities, AuditObservation,
    AuditOutcome, AuditPolicyIdentity, AuditPolicyRole, AuditReason, AuditScope,
    Phase2AuditEventKind,
};
use latent_core::{ArtifactBlobDigest, PlatformError, PlatformErrorCode, TenantId};
use sha2::{Digest, Sha256};

use crate::{
    AdmissionAuthority, AdmissionBinding, AdmissionStorageLimits, PackageAdmissionUpload,
    VerifiedAdmission,
};

/// Diagnostic capture around explicit verification/recovery operations. The
/// original authority owns every trust decision and returned grant. Capture is
/// lossy and runs after its call/fences complete; it is never a new trust check.
pub struct AuditedAdmissionAuthority {
    inner: Arc<dyn AdmissionAuthority>,
    audit: AuditHandle,
}

impl AuditedAdmissionAuthority {
    #[must_use]
    pub fn new(inner: Arc<dyn AdmissionAuthority>, audit: AuditHandle) -> Self {
        Self { inner, audit }
    }

    fn observed(
        &self,
        tenant: &TenantId,
        received: Option<ArtifactBlobDigest>,
        result: &Result<VerifiedAdmission, PlatformError>,
    ) {
        // Preserve bounded trusted scope; malformed input is node diagnostic
        // data, never an invented tenant or a copied unbounded identifier.
        let scope = if tenant.0.capacity() <= 512
            && !tenant.0.is_empty()
            && !tenant
                .0
                .chars()
                .any(|ch| ch.is_control() || ch.is_whitespace())
        {
            AuditScope::Tenant(tenant.clone())
        } else {
            AuditScope::Node
        };
        let mut identities = AuditIdentities {
            received_manifest_digest: received,
            ..Default::default()
        };
        let (kind, outcome, reason) = match result {
            Ok(verified) => {
                let binding = verified.grant.binding();
                // The concrete repository independently validates the same
                // association. Never publish a success under another tenant.
                if binding.tenant != *tenant || binding.release.0.len() != 71 {
                    self.audit.note_unavailable();
                    return;
                }
                identities.package = Some(binding.package.clone());
                identities.component = Some(binding.release.clone());
                if let Some(policy) = verified.grant.policy_identity() {
                    identities.policies.push(AuditPolicyIdentity {
                        role: AuditPolicyRole::Admission,
                        scope: policy.scope,
                        generation: policy.generation,
                        digest: policy.digest,
                    });
                }
                (
                    Phase2AuditEventKind::VerificationAccepted,
                    AuditOutcome::Succeeded,
                    AuditReason::Verified,
                )
            }
            Err(failure) => {
                let reason = match failure.code {
                    PlatformErrorCode::PermissionDenied => AuditReason::PolicyDenied,
                    PlatformErrorCode::ResourceExhausted => AuditReason::Capacity,
                    PlatformErrorCode::Unavailable => AuditReason::Unavailable,
                    PlatformErrorCode::CorruptArtifact => AuditReason::IntegrityMismatch,
                    PlatformErrorCode::IncompatibleContract => AuditReason::Unsupported,
                    _ => AuditReason::Rejected,
                };
                let outcome = if failure.code == PlatformErrorCode::PermissionDenied {
                    AuditOutcome::Denied
                } else {
                    AuditOutcome::Failed
                };
                (Phase2AuditEventKind::VerificationRejected, outcome, reason)
            }
        };
        let _ = self.audit.try_capture(&AuditObservation {
            scope,
            actor: AuditActorIdentity {
                kind: AuditActorKind::Host,
                subject: "supply-chain-authority".to_owned(),
            },
            kind,
            outcome,
            identities,
            reason,
            cache_kind: None,
            occurred_at_unix_millis: super::mapping::now(),
        });
    }
}

impl AdmissionAuthority for AuditedAdmissionAuthority {
    fn verify(
        &self,
        tenant: &TenantId,
        upload: PackageAdmissionUpload,
    ) -> Result<VerifiedAdmission, PlatformError> {
        let received = received(&upload);
        let result = self.inner.verify(tenant, upload);
        self.observed(tenant, received, &result);
        result
    }

    fn recover(
        &self,
        binding: &AdmissionBinding,
        upload: PackageAdmissionUpload,
    ) -> Result<VerifiedAdmission, PlatformError> {
        let received = received(&upload);
        let result = self.inner.recover(binding, upload);
        self.observed(&binding.tenant, received, &result);
        result
    }
}

fn received(upload: &PackageAdmissionUpload) -> Option<ArtifactBlobDigest> {
    // Omit the digest for oversized rejected input instead of hashing an
    // unbounded upload merely to enrich a diagnostic event.
    (upload.manifest.len() <= AdmissionStorageLimits::default().max_document_bytes).then(|| {
        crate::content_hash::format_digest(Sha256::digest(&upload.manifest).into())
            .0
            .parse()
            .expect("canonical manifest digest")
    })
}
