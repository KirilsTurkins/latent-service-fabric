//! Renewal reuses immutable package bytes and independently verifies new evidence.

use std::path::Path;
use std::sync::Arc;

use latent_core::{PackageDigest, PlatformError, PlatformErrorCode, ReleaseDigest};
use sha2::{Digest, Sha256};

use crate::local_repository::{
    admission::association, corrupt, error, resource_exhausted, DirectoryArtifactRepository,
    Retention, VerifiedEntry,
};
use crate::{
    AdmissionBinding, AdmissionEvidence, AdmissionStorageLimits, PackageAdmissionUpload,
    ReleaseEligibility, ReleaseEvidenceUpload, VerifiedAdmission, VerifiedArtifactMetadata,
};

impl DirectoryArtifactRepository {
    /// The caller owns the bounded admission-work permit and checks lifecycle
    /// state/scope before this read. No current original proof is required.
    pub(in crate::local_repository) fn verify_new_evidence(
        &self,
        release: &ReleaseDigest,
        package: &PackageDigest,
        evidence: ReleaseEvidenceUpload,
    ) -> Result<VerifiedAdmission, PlatformError> {
        let config = self.admission.as_ref().ok_or_else(mode)?;
        check_input(
            &evidence,
            config.limits,
            self.life_store().limits().max_evidence_revision_bytes,
        )?;
        let expected_evidence =
            evidence_digest([&evidence.signatures, &evidence.provenance, &evidence.sboms]);
        let path = self.entry_path(release)?;
        let original = self.load_complete_entry(&path, Retention::Metadata)?;
        self.verify_admission_index(release, &original)?;
        let (binding, mut upload) = self.original_evidence_upload(&path, &original)?;
        if &binding.package != package || &binding.release != release {
            return Err(error(
                PlatformErrorCode::PermissionDenied,
                "renewal-package-mismatch",
            ));
        }
        replace(&mut upload, evidence);
        config
            .limits
            .check_upload(&upload, self.config.max_component_bytes)?;
        // Association is checked before crypto, including evidence on a package
        // whose original proof is expired/revoked under the current policy.
        association::verify(&binding, &upload, &original.metadata, &self.codec)?;
        let verified = config.authority.verify(&binding.tenant, upload)?;
        self.check_renewed_result(
            &binding,
            &original.metadata,
            verified,
            expected_evidence,
            false,
        )
    }

    /// Called only when the durable lifecycle record selects an evidence
    /// revision. Missing or malformed selected data is corruption, never an
    /// instruction to fall back to the original admission proof.
    pub(in crate::local_repository) fn recover_selected_evidence(
        &self,
        path: &Path,
        original: &VerifiedEntry,
    ) -> Result<Option<ReleaseEligibility>, PlatformError> {
        let config = self.admission.as_ref().ok_or_else(mode)?;
        let release = original.metadata.verified_digest();
        let (binding, evidence) = self
            .life_store()
            .read_evidence(release)?
            .ok_or_else(|| corrupt("selected-evidence-revision-missing"))?;
        config.limits.check_binding(&binding)?;
        check_input(
            &evidence,
            config.limits,
            self.life_store().limits().max_evidence_revision_bytes,
        )?;
        let expected_evidence =
            evidence_digest([&evidence.signatures, &evidence.provenance, &evidence.sboms]);
        let (historical, mut upload) = self.original_evidence_upload(path, original)?;
        same_identity(&historical, &binding)?;
        replace(&mut upload, evidence);
        config
            .limits
            .check_upload(&upload, self.config.max_component_bytes)?;
        association::verify(&binding, &upload, &original.metadata, &self.codec)?;
        match config.authority.recover(&binding, upload) {
            Ok(verified) => {
                let verified = self.check_renewed_result(
                    &binding,
                    &original.metadata,
                    verified,
                    expected_evidence,
                    true,
                )?;
                Ok(Some(ReleaseEligibility::new(
                    verified.grant,
                    Arc::clone(&config.owner),
                )))
            }
            Err(failure)
                if matches!(
                    failure.code,
                    PlatformErrorCode::PermissionDenied
                        | PlatformErrorCode::IncompatibleContract
                        | PlatformErrorCode::StateConflict
                        | PlatformErrorCode::Unavailable
                ) =>
            {
                Ok(None)
            }
            Err(failure) => Err(failure),
        }
    }

    fn original_evidence_upload(
        &self,
        path: &Path,
        original: &VerifiedEntry,
    ) -> Result<(AdmissionBinding, PackageAdmissionUpload), PlatformError> {
        let config = self.admission.as_ref().ok_or_else(mode)?;
        let stored = original
            .admission
            .as_ref()
            .ok_or_else(|| corrupt("admission-record-missing"))?;
        let binding = stored.binding(path, config.limits)?;
        config.limits.check_binding(&binding)?;
        let upload = stored.upload(path, config.limits, self.config.max_component_bytes)?;
        config
            .limits
            .check_upload(&upload, self.config.max_component_bytes)?;
        association::verify(&binding, &upload, &original.metadata, &self.codec)?;
        Ok((binding, upload))
    }

    fn check_renewed_result(
        &self,
        expected: &AdmissionBinding,
        metadata: &VerifiedArtifactMetadata,
        verified: VerifiedAdmission,
        expected_evidence: [u8; 32],
        recovery: bool,
    ) -> Result<VerifiedAdmission, PlatformError> {
        self.validate_verified(&expected.tenant, &verified)?;
        same_identity(expected, verified.grant.binding())?;
        if recovery && expected != verified.grant.binding() {
            return Err(corrupt("renewal-recovered-receipt-mismatch"));
        }
        // The configured verifier must return the exact evidence it checked,
        // not silently substitute a different otherwise-valid receipt input.
        if evidence_digest([
            &verified.upload.signatures,
            &verified.upload.provenance,
            &verified.upload.sboms,
        ]) != expected_evidence
        {
            return Err(corrupt("renewal-verified-evidence-mismatch"));
        }
        association::verify(
            verified.grant.binding(),
            &verified.upload,
            metadata,
            &self.codec,
        )?;
        let VerifiedAdmission {
            artifact,
            upload,
            grant,
        } = verified;
        // Reuse the ordinary bounded manifest/descriptor/capacity validator;
        // the temporary prepared bytes are discarded without staging anything.
        let artifact = self.prepare_publication(artifact)?.artifact;
        if artifact.descriptor != *metadata.descriptor()
            || artifact.manifest != *metadata.manifest()
            || artifact.contracts != metadata.contracts()
        {
            return Err(corrupt("renewal-immutable-artifact-mismatch"));
        }
        Ok(VerifiedAdmission {
            artifact,
            upload,
            grant,
        })
    }
}

fn same_identity(
    expected: &AdmissionBinding,
    actual: &AdmissionBinding,
) -> Result<(), PlatformError> {
    if expected.tenant != actual.tenant
        || expected.package != actual.package
        || expected.release != actual.release
    {
        return Err(corrupt("renewal-immutable-binding-mismatch"));
    }
    Ok(())
}

fn replace(upload: &mut PackageAdmissionUpload, evidence: ReleaseEvidenceUpload) {
    upload.signatures = evidence.signatures;
    upload.provenance = evidence.provenance;
    upload.sboms = evidence.sboms;
}

pub(super) fn check_input(
    evidence: &ReleaseEvidenceUpload,
    limits: AdmissionStorageLimits,
    maximum: usize,
) -> Result<(), PlatformError> {
    let mut total = 0_usize;
    for entries in [&evidence.signatures, &evidence.provenance, &evidence.sboms] {
        if entries.len() > limits.max_evidence_per_kind
            || entries.capacity() > limits.max_evidence_per_kind
        {
            return Err(resource_exhausted("renewal-evidence-count-limit"));
        }
        for item in entries {
            if item.manifest.len() > limits.max_document_bytes
                || item.configuration.len() > limits.max_document_bytes
            {
                return Err(resource_exhausted("renewal-evidence-document-limit"));
            }
            for bytes in [&item.manifest, &item.configuration, &item.payload] {
                total = total
                    .checked_add(bytes.capacity())
                    .ok_or_else(|| resource_exhausted("renewal-evidence-byte-limit"))?;
            }
        }
    }
    if total > maximum.min(limits.max_auxiliary_bytes) {
        return Err(resource_exhausted("renewal-evidence-byte-limit"));
    }
    Ok(())
}

fn evidence_digest(kinds: [&[AdmissionEvidence]; 3]) -> [u8; 32] {
    let mut digest = Sha256::new();
    digest.update(b"lsf-renewal-exact-evidence-v1\0");
    for entries in kinds {
        digest.update((entries.len() as u64).to_le_bytes());
        for item in entries {
            for bytes in [&item.manifest, &item.configuration, &item.payload] {
                digest.update((bytes.len() as u64).to_le_bytes());
                digest.update(bytes);
            }
        }
    }
    digest.finalize().into()
}

fn mode() -> PlatformError {
    error(
        PlatformErrorCode::PermissionDenied,
        "evidence-renewal-requires-enforced-mode",
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    fn input() -> ReleaseEvidenceUpload {
        ReleaseEvidenceUpload {
            signatures: vec![AdmissionEvidence {
                manifest: b"m".to_vec(),
                configuration: b"{}".to_vec(),
                payload: b"p".to_vec(),
            }],
            provenance: Vec::new(),
            sboms: Vec::new(),
        }
    }

    #[test]
    fn renewal_owned_input_bounds_are_checked_before_materializing_the_original() {
        let mut evidence = input();
        check_input(&evidence, AdmissionStorageLimits::default(), 4).unwrap();
        assert!(check_input(&evidence, AdmissionStorageLimits::default(), 3).is_err());
        evidence.signatures[0].payload = Vec::with_capacity(16);
        assert!(check_input(&evidence, AdmissionStorageLimits::default(), 4).is_err());
        let mut evidence = input();
        evidence.provenance = Vec::with_capacity(9);
        assert!(check_input(&evidence, AdmissionStorageLimits::default(), 1024).is_err());
    }

    #[test]
    fn renewal_exact_bytes_include_role_order_and_field_boundaries() {
        let mut evidence = input();
        let original =
            evidence_digest([&evidence.signatures, &evidence.provenance, &evidence.sboms]);
        assert_ne!(
            original,
            evidence_digest([&evidence.provenance, &evidence.signatures, &evidence.sboms])
        );
        evidence.signatures[0].payload.push(b'x');
        assert_ne!(
            original,
            evidence_digest([&evidence.signatures, &evidence.provenance, &evidence.sboms])
        );
        evidence.signatures[0].payload.pop();
        evidence.signatures[0].manifest.push(b'{');
        evidence.signatures[0].configuration.remove(0);
        assert_ne!(
            original,
            evidence_digest([&evidence.signatures, &evidence.provenance, &evidence.sboms])
        );
    }
}
