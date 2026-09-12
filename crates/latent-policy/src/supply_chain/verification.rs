//! Shared evidence evaluation. Diagnostic reports never construct admission grants.
use super::{denied, SupplyChainPolicy};
use latent_artifacts::package::PackageKind;
use latent_artifacts::{AdmissionEvidence, ReleaseEvidenceUpload};
use latent_core::{PlatformError, TenantId};
use latent_packaging::{
    evaluate_sboms, PackageBundle, PackagingLimits, SbomEvidenceLimits, SbomEvidenceRef,
    SbomPolicyEvaluation,
};
use latent_signing::{
    BuilderVerifier, PackageSigningSubject, ProvenanceEvidenceRef, PublisherVerifier,
    SignatureEvidenceRef, VerifiedBuildProvenance, VerifiedPackageSignature,
};
use serde::Serialize;

pub(super) struct EvidenceInput<'a> {
    pub signatures: &'a Vec<AdmissionEvidence>,
    pub provenance: &'a Vec<AdmissionEvidence>,
    pub sboms: &'a Vec<AdmissionEvidence>,
}

pub(super) struct CheckedEvidence {
    pub subject: PackageSigningSubject,
    pub publisher: VerifiedPackageSignature,
    pub builder: VerifiedBuildProvenance,
    pub sbom: SbomPolicyEvaluation,
}

// The durable authority invokes this under its existing policy/currentness fence.
pub(super) fn check_evidence(
    policy: &SupplyChainPolicy,
    verifiers: &(PublisherVerifier, BuilderVerifier),
    tenant: &TenantId,
    bundle: &PackageBundle,
    input: EvidenceInput<'_>,
    now: u64,
) -> Result<CheckedEvidence, PlatformError> {
    if !super::config::identifier(&tenant.0) || !policy.tenants.contains_key(&tenant.0) {
        return Err(denied("admission-tenant-denied"));
    }
    let EvidenceInput {
        signatures,
        provenance,
        sboms,
    } = input;
    let maximum = latent_artifacts::AdmissionStorageLimits::default();
    let mut bytes = 0usize;
    for entries in [signatures, provenance, sboms] {
        if entries.len() > maximum.max_evidence_per_kind
            || entries.capacity() > maximum.max_evidence_per_kind
        {
            return Err(super::invalid("admission-evidence-limit"));
        }
        for entry in entries {
            if entry.manifest.len() > maximum.max_document_bytes
                || entry.configuration.len() > maximum.max_document_bytes
            {
                return Err(super::invalid("admission-evidence-limit"));
            }
            for value in [&entry.manifest, &entry.configuration, &entry.payload] {
                bytes = bytes
                    .checked_add(value.capacity())
                    .ok_or_else(|| super::invalid("admission-evidence-limit"))?;
            }
        }
    }
    if bytes > maximum.max_auxiliary_bytes {
        return Err(super::invalid("admission-evidence-limit"));
    }
    if signatures.len() != 1 || provenance.len() != 1 {
        return Err(denied("admission-required-evidence-cardinality"));
    }
    let limits = PackagingLimits::default();
    if bundle.layout().config().kind != PackageKind::Capsule {
        return Err(denied("admission-executable-package-required"));
    }
    let subject = PackageSigningSubject::from_package(
        bundle.manifest_bytes(),
        bundle.config_bytes(),
        limits.package,
    )?;
    let signature = &signatures[0];
    let publisher = verifiers.0.verify_package(
        &subject,
        SignatureEvidenceRef {
            manifest: &signature.manifest,
            config: &signature.configuration,
            payload: &signature.payload,
        },
        now,
    )?;
    if !policy
        .tenants
        .get(&tenant.0)
        .is_some_and(|publishers| publishers.contains(&publisher.publisher().0))
    {
        return Err(denied("admission-tenant-publisher-denied"));
    }
    let provenance_entry = &provenance[0];
    let builder = verifiers.1.verify_package(
        &subject,
        ProvenanceEvidenceRef {
            manifest: &provenance_entry.manifest,
            config: &provenance_entry.configuration,
            payload: &provenance_entry.payload,
        },
        now,
    )?;
    let evidence = sboms
        .iter()
        .map(|entry| SbomEvidenceRef {
            manifest: &entry.manifest,
            config: &entry.configuration,
            payload: &entry.payload,
        })
        .collect::<Vec<_>>();
    let sbom = evaluate_sboms(
        bundle,
        &evidence,
        &policy.sbom,
        SbomEvidenceLimits::default(),
    )
    .map_err(|error| match error.message.as_str() {
        "required-embedded-sbom-missing" => denied("required-embedded-sbom-missing"),
        "required-detached-sbom-missing" => denied("required-detached-sbom-missing"),
        "required-sbom-source-unavailable" => denied("required-sbom-source-unavailable"),
        "required-sbom-license-unavailable" => denied("required-sbom-license-unavailable"),
        _ => error,
    })?;
    if bundle
        .sbom()
        .and_then(latent_packaging::CheckedPackageSbom::source_snapshot_digest)
        .is_some_and(|snapshot| snapshot != builder.source_snapshot_digest())
    {
        return Err(denied("admission-build-sbom-source-mismatch"));
    }
    Ok(CheckedEvidence {
        subject,
        publisher,
        builder,
        sbom,
    })
}

/// Borrowed package and evidence for one explicit local diagnostic check.
/// The caller owns input bytes and supplies its sampled wall time. No durable
/// clock/policy floor or target-node runtime suitability is established.
pub struct PackageVerificationRequest<'a> {
    pub tenant: &'a TenantId,
    pub package: &'a PackageBundle,
    pub evidence: &'a ReleaseEvidenceUpload,
    pub unix_seconds: u64,
}

/// Closed diagnostic output with no grant, receipt or permit conversion.
#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PackageVerificationReport {
    format_version: u32,
    tenant: String,
    package_digest: String,
    component_digest: String,
    publisher: String,
    publisher_key: String,
    signature_digest: String,
    builder: String,
    builder_key: String,
    provenance_digest: String,
    sbom_inventory_digest: Option<String>,
    sbom_referrer_digest: Option<String>,
    policy: super::config::PolicyIdentity,
    policy_digest: String,
    checked_at_unix_seconds: u64,
    valid_until_unix_seconds: u64,
    runtime_compatibility: &'static str,
    durable_policy_clock_floors: bool,
}

impl PackageVerificationReport {
    #[must_use]
    pub fn package_digest(&self) -> &str {
        &self.package_digest
    }
    #[must_use]
    pub fn component_digest(&self) -> &str {
        &self.component_digest
    }
    #[must_use]
    pub const fn checked_at_unix_seconds(&self) -> u64 {
        self.checked_at_unix_seconds
    }
}

/// Verify the same publisher, builder, SBOM, tenant and capsule metadata rules
/// as node admission. This has no catalog, filesystem, runtime grant or history.
pub fn verify_package_once(
    policy: &SupplyChainPolicy,
    request: PackageVerificationRequest<'_>,
) -> Result<PackageVerificationReport, PlatformError> {
    let verifiers = policy.verifiers(request.unix_seconds)?;
    let checked = check_evidence(
        policy,
        &verifiers,
        request.tenant,
        request.package,
        EvidenceInput {
            signatures: &request.evidence.signatures,
            provenance: &request.evidence.provenance,
            sboms: &request.evidence.sboms,
        },
        request.unix_seconds,
    )?;
    let metadata = super::verify::metadata(
        request.package,
        request.tenant,
        checked.publisher.publisher().clone(),
    )?;
    Ok(PackageVerificationReport {
        format_version: 1,
        tenant: request.tenant.0.clone(),
        package_digest: checked.subject.subject().digest.to_string(),
        component_digest: metadata.descriptor.release_digest.0,
        publisher: checked.publisher.publisher().0.clone(),
        publisher_key: checked.publisher.key_fingerprint().to_string(),
        signature_digest: checked.publisher.evidence_digest().to_string(),
        builder: checked.builder.builder_id().to_owned(),
        builder_key: checked.builder.key_fingerprint().to_string(),
        provenance_digest: checked.builder.evidence_digest().to_string(),
        sbom_inventory_digest: checked.sbom.inventory_digest().map(ToString::to_string),
        sbom_referrer_digest: checked.sbom.referrer_digest().map(ToString::to_string),
        policy: policy.identity.clone(),
        policy_digest: policy.identity.digest()?,
        checked_at_unix_seconds: request.unix_seconds,
        valid_until_unix_seconds: checked
            .publisher
            .valid_until()
            .min(checked.builder.valid_until())
            .min(policy.identity.valid_until),
        runtime_compatibility: "not-evaluated",
        durable_policy_clock_floors: false,
    })
}
