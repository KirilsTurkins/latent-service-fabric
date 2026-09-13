use super::config::PolicyIdentity;
use latent_artifacts::package::{
    artifact_blob_digest, decode_referrer, package_digest, EvidenceKind, PackageKind,
    PackageLimits, PackageSubject,
};
use latent_artifacts::{
    AdmissionBinding, AdmissionEvidence, AdmissionStorageLimits, PackageAdmissionUpload,
};
use latent_core::{ArtifactBlobDigest, PackageDigest, PlatformError, PlatformErrorCode};
use latent_packaging::{
    evaluate_sboms, inspect_bundle, BundleInput, PackageBundle, PackagingLimits,
    SbomEvidenceLimits, SbomEvidenceRef, SbomPolicy, SbomPolicyConfig, SbomPresence,
};
use latent_signing::{
    inspect_provenance, inspect_signature, PackageSigningSubject, ProvenanceLimits, SignatureLimits,
};
use serde::{Deserialize, Serialize};

/// Historical disposition data. Recovery always obtains new cryptographic
/// proofs; decoding this receipt never yields an admission grant.
#[derive(Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(super) struct Receipt {
    pub format_version: u32,
    pub disposition: String,
    pub tenant: String,
    pub package: String,
    pub release: String,
    pub publisher: String,
    pub publisher_key: String,
    pub signature_manifest: String,
    pub signature_payload: String,
    pub builder: String,
    pub builder_key: String,
    pub provenance_manifest: String,
    pub provenance_payload: String,
    pub sbom_inventory: Option<String>,
    pub sbom_referrer: Option<String>,
    pub policy: PolicyIdentity,
    pub policy_digest: String,
    pub epoch: u64,
    pub verified_at: u64,
    pub valid_until: u64,
}
impl Receipt {
    /// Binds historical display fields to the original checked bytes before a
    /// current policy denial may retain non-authorizing history. Parsed identity
    /// hints confer no trust; successful recovery still verifies both signatures.
    pub fn validate_retained(
        binding: &AdmissionBinding,
        upload: PackageAdmissionUpload,
    ) -> Result<PackageAdmissionUpload, PlatformError> {
        let old = Self::validate_history(binding)?;
        AdmissionStorageLimits::default().check_upload(&upload, 64 * 1024 * 1024)?;
        if upload.signatures.len() != 1 || upload.provenance.len() != 1 {
            return Err(corrupt());
        }
        let PackageAdmissionUpload {
            manifest,
            configuration,
            layers,
            signatures,
            provenance,
            sboms,
        } = upload;
        let bundle = inspect_bundle(
            BundleInput {
                manifest,
                configuration,
                layers,
            },
            PackagingLimits::default(),
        )
        .map_err(retained_error)?;
        let subject = PackageSigningSubject::from_package(
            bundle.manifest_bytes(),
            bundle.config_bytes(),
            PackageLimits::default(),
        )
        .map_err(|_| corrupt())?;
        if subject.kind() != PackageKind::Capsule
            || subject.subject().digest != binding.package
            || subject.component_digest().map(ArtifactBlobDigest::as_str)
                != Some(binding.release.0.as_str())
        {
            return Err(corrupt());
        }
        old.check_signatures(&subject, &signatures[0], &provenance[0], &bundle)?;
        old.check_sboms(&bundle, &sboms)?;
        let BundleInput {
            manifest,
            configuration,
            layers,
        } = bundle.into_input();
        Ok(PackageAdmissionUpload {
            manifest,
            configuration,
            layers,
            signatures,
            provenance,
            sboms,
        })
    }

    fn check_signatures(
        &self,
        expected: &PackageSigningSubject,
        signature: &AdmissionEvidence,
        provenance: &AdmissionEvidence,
        bundle: &PackageBundle,
    ) -> Result<(), PlatformError> {
        check_referrer(
            expected.subject(),
            signature,
            EvidenceKind::Signature,
            &self.signature_manifest,
            &self.signature_payload,
            SignatureLimits::default().max_envelope_bytes,
        )?;
        check_referrer(
            expected.subject(),
            provenance,
            EvidenceKind::Provenance,
            &self.provenance_manifest,
            &self.provenance_payload,
            ProvenanceLimits::default().max_envelope_bytes,
        )?;
        let publisher = inspect_signature(&signature.payload, SignatureLimits::default())
            .map_err(|_| corrupt())?;
        let builder = inspect_provenance(&provenance.payload, ProvenanceLimits::default())
            .map_err(|_| corrupt())?;
        if publisher.subject() != expected.subject()
            || builder.subject() != expected.subject()
            || publisher.publisher_id().0 != self.publisher
            || publisher.key_hint().as_str() != self.publisher_key
            || builder.builder_id() != self.builder
            || builder.key_hint().as_str() != self.builder_key
            || builder.observation().component_digest != self.release
            || expected.component_size() != Some(builder.observation().component_size)
            || bundle
                .sbom()
                .and_then(latent_packaging::CheckedPackageSbom::source_snapshot_digest)
                .is_some_and(|digest| {
                    digest.as_str() != builder.observation().source.snapshot_digest
                })
            || self.verified_at < publisher.validity().issued_at
            || self.valid_until > publisher.validity().expires_at
            || self.verified_at < builder.validity().issued_at
            || self.valid_until > builder.validity().expires_at
        {
            return Err(corrupt());
        }
        Ok(())
    }

    fn check_sboms(
        &self,
        bundle: &PackageBundle,
        sboms: &[AdmissionEvidence],
    ) -> Result<(), PlatformError> {
        // Both presence modes are optional here: compare the historical exact
        // inventory/association set, without substituting today's content policy.
        let policy = SbomPolicy::new(SbomPolicyConfig {
            format_version: 1,
            embedded: SbomPresence::Optional,
            detached: SbomPresence::Optional,
            require_source: Vec::new(),
            require_license: Vec::new(),
        })?;
        let references = sboms
            .iter()
            .map(|entry| SbomEvidenceRef {
                manifest: &entry.manifest,
                config: &entry.configuration,
                payload: &entry.payload,
            })
            .collect::<Vec<_>>();
        let checked = evaluate_sboms(bundle, &references, &policy, SbomEvidenceLimits::default())
            .map_err(retained_error)?;
        if checked.inventory_digest().map(ArtifactBlobDigest::as_str)
            != self.sbom_inventory.as_deref()
            || checked.referrer_digest().map(PackageDigest::as_str) != self.sbom_referrer.as_deref()
        {
            return Err(corrupt());
        }
        Ok(())
    }

    pub fn encode(&self) -> Result<Vec<u8>, PlatformError> {
        let mut bytes = serde_json::to_vec(self).map_err(|_| corrupt())?;
        if bytes.len() > 16 * 1024 {
            return Err(corrupt());
        }
        bytes.shrink_to_fit();
        Ok(bytes)
    }
    pub fn validate_history(binding: &AdmissionBinding) -> Result<Self, PlatformError> {
        if binding.receipt.capacity() > 16 * 1024 {
            return Err(corrupt());
        }
        let bytes = &binding.receipt;
        super::json::preflight(bytes, 16 * 1024).map_err(|_| corrupt())?;
        let old: Self = serde_json::from_slice(bytes).map_err(|_| corrupt())?;
        old.policy.validate().map_err(|_| corrupt())?;
        for id in [&old.tenant, &old.publisher, &old.builder] {
            if !super::config::identifier(id) {
                return Err(corrupt());
            }
        }
        for digest in [
            &old.package,
            &old.release,
            &old.publisher_key,
            &old.signature_manifest,
            &old.signature_payload,
            &old.builder_key,
            &old.provenance_manifest,
            &old.provenance_payload,
            &old.policy_digest,
        ]
        .into_iter()
        .chain(old.sbom_inventory.iter())
        .chain(old.sbom_referrer.iter())
        {
            if digest.parse::<latent_core::ArtifactBlobDigest>().is_err() {
                return Err(corrupt());
            }
        }
        if old.format_version != 1
            || old.disposition != "admitted"
            || old.epoch == 0
            || old.verified_at >= old.valid_until
            || old.verified_at < old.policy.valid_from
            || old.valid_until > old.policy.valid_until
            || old.encode()? != *bytes
            || old.policy.digest()? != old.policy_digest
            || old.tenant != binding.tenant.0
            || old.package != binding.package.as_str()
            || old.release != binding.release.0
        {
            return Err(corrupt());
        }
        Ok(old)
    }
    pub fn recover(binding: &AdmissionBinding, fresh: &Self) -> Result<(), PlatformError> {
        let old = Self::validate_history(binding)?;
        if old.tenant != fresh.tenant
            || old.package != fresh.package
            || old.release != fresh.release
            || old.publisher != fresh.publisher
            || old.publisher_key != fresh.publisher_key
            || old.signature_manifest != fresh.signature_manifest
            || old.signature_payload != fresh.signature_payload
            || old.builder != fresh.builder
            || old.builder_key != fresh.builder_key
            || old.provenance_manifest != fresh.provenance_manifest
            || old.provenance_payload != fresh.provenance_payload
            || old.sbom_inventory != fresh.sbom_inventory
            || old.sbom_referrer != fresh.sbom_referrer
        {
            return Err(corrupt());
        }
        Ok(())
    }
}
fn check_referrer(
    expected: &PackageSubject,
    evidence: &AdmissionEvidence,
    kind: EvidenceKind,
    manifest_digest: &str,
    payload_digest: &str,
    payload_limit: usize,
) -> Result<(), PlatformError> {
    if evidence.manifest.len() > 4096
        || evidence.payload.len() > payload_limit
        || evidence.configuration != b"{}"
        || package_digest(&evidence.manifest).as_str() != manifest_digest
        || artifact_blob_digest(&evidence.payload).as_str() != payload_digest
    {
        return Err(corrupt());
    }
    let manifest =
        decode_referrer(&evidence.manifest, PackageLimits::default()).map_err(retained_error)?;
    if manifest.subject != *expected
        || manifest.artifact_type != kind.artifact_type()
        || manifest.layers[0].digest.as_str() != payload_digest
        || manifest.layers[0].size != evidence.payload.len() as u64
    {
        return Err(corrupt());
    }
    Ok(())
}
fn retained_error(error: PlatformError) -> PlatformError {
    if error.code == PlatformErrorCode::ResourceExhausted {
        error
    } else {
        corrupt()
    }
}
fn corrupt() -> PlatformError {
    super::error(
        PlatformErrorCode::CorruptArtifact,
        "admission-receipt-corrupt",
    )
}
