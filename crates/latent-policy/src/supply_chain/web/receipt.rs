use super::super::{
    config::PolicyIdentity,
    receipt::{check_referrer, check_sbom_history, corrupt, retained_error},
    verification::CheckedEvidence,
    State,
};
use latent_artifacts::{
    package::{EvidenceKind, PackageLimits},
    web::{CheckedWebLayout, WebAdmissionBinding, MAX_WEB_RENDERER_BYTES},
    AdmissionStorageLimits, PackageAdmissionUpload,
};
use latent_core::{PlatformError, TenantId};
use latent_packaging::{inspect_bundle, inspect_web_bundle, BundleInput, PackagingLimits};
use latent_signing::{
    inspect_signature, inspect_web_provenance, PackageSigningSubject, ProvenanceLimits,
    SignatureLimits, VerifiedWebBuildProvenance,
};
use serde::{Deserialize, Serialize};

/// Exact historical association, separately versioned from capsule receipts.
/// Recovery reauthenticates all signatures against current policy before grants.
#[derive(Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(super) struct Receipt {
    format_version: u32,
    profile: String,
    tenant: String,
    package: String,
    manifest: String,
    assets: String,
    publisher: String,
    publisher_key: String,
    signature_manifest: String,
    signature_payload: String,
    builder: String,
    builder_key: String,
    provenance_manifest: String,
    provenance_payload: String,
    sbom_inventory: Option<String>,
    sbom_referrer: Option<String>,
    pub policy: PolicyIdentity,
    pub policy_digest: String,
    epoch: u64,
    verified_at: u64,
    valid_until: u64,
}
impl Receipt {
    pub fn new(
        tenant: &TenantId,
        layout: &CheckedWebLayout,
        checked: &CheckedEvidence<VerifiedWebBuildProvenance>,
        state: &State,
        now: u64,
    ) -> Result<Self, PlatformError> {
        let publisher = &checked.publisher;
        let builder = &checked.builder;
        Ok(Self {
            format_version: 1,
            profile: "lsf.web-admission.v1".into(),
            tenant: tenant.0.clone(),
            package: layout.package().to_string(),
            manifest: layout.manifest_digest().to_string(),
            assets: layout.assets_digest().to_string(),
            publisher: publisher.publisher().0.clone(),
            publisher_key: publisher.key_fingerprint().to_string(),
            signature_manifest: publisher.evidence_digest().to_string(),
            signature_payload: publisher.payload_digest().to_string(),
            builder: builder.builder_id().into(),
            builder_key: builder.key_fingerprint().to_string(),
            provenance_manifest: builder.evidence_digest().to_string(),
            provenance_payload: builder.payload_digest().to_string(),
            sbom_inventory: checked.sbom.inventory_digest().map(ToString::to_string),
            sbom_referrer: checked.sbom.referrer_digest().map(ToString::to_string),
            policy: state.policy.identity.clone(),
            policy_digest: state.policy.identity.digest()?,
            epoch: state.floor.epoch,
            verified_at: now,
            valid_until: publisher
                .valid_until()
                .min(builder.valid_until())
                .min(state.policy.identity.valid_until),
        })
    }
    pub fn encode(&self) -> Result<Vec<u8>, PlatformError> {
        let bytes = serde_json::to_vec(self).map_err(|_| corrupt())?;
        if bytes.len() > 16 * 1024 {
            return Err(corrupt());
        }
        Ok(bytes.into_boxed_slice().into_vec())
    }
    pub fn validate_history(binding: &WebAdmissionBinding) -> Result<Self, PlatformError> {
        if binding.tenant.0.capacity() > 128 || binding.receipt.capacity() > 16 * 1024 {
            return Err(corrupt());
        }
        super::super::json::preflight(&binding.receipt, 16 * 1024).map_err(|_| corrupt())?;
        let old: Self = serde_json::from_slice(&binding.receipt).map_err(|_| corrupt())?;
        old.policy.validate().map_err(|_| corrupt())?;
        for id in [&old.tenant, &old.publisher, &old.builder] {
            if !super::super::config::identifier(id) {
                return Err(corrupt());
            }
        }
        for digest in [
            &old.package,
            &old.manifest,
            &old.assets,
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
            || old.profile != "lsf.web-admission.v1"
            || old.epoch == 0
            || old.verified_at >= old.valid_until
            || old.verified_at < old.policy.valid_from
            || old.valid_until > old.policy.valid_until
            || old.encode()? != binding.receipt
            || old.policy.digest()? != old.policy_digest
            || old.tenant != binding.tenant.0
            || old.package != binding.package.as_str()
            || old.manifest != binding.manifest.as_str()
            || old.assets != binding.assets.as_str()
        {
            return Err(corrupt());
        }
        Ok(old)
    }
    pub fn recover(binding: &WebAdmissionBinding, fresh: &Self) -> Result<(), PlatformError> {
        let old = Self::validate_history(binding)?;
        if old.tenant != fresh.tenant
            || old.package != fresh.package
            || old.manifest != fresh.manifest
            || old.assets != fresh.assets
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

pub(in crate::supply_chain) fn validate_retained(
    binding: &WebAdmissionBinding,
    upload: PackageAdmissionUpload,
) -> Result<PackageAdmissionUpload, PlatformError> {
    let old = Receipt::validate_history(binding)?;
    let renderer_maximum = usize::try_from(MAX_WEB_RENDERER_BYTES).map_err(|_| corrupt())?;
    AdmissionStorageLimits::default().check_upload(&upload, renderer_maximum)?;
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
    let limits = PackagingLimits::default();
    let bundle = inspect_bundle(
        BundleInput {
            manifest,
            configuration,
            layers,
        },
        limits,
    )
    .map_err(retained_error)?;
    let layout = inspect_web_bundle(&bundle, limits.semantics).map_err(retained_error)?;
    if layout.package() != &binding.package
        || layout.manifest_digest() != &binding.manifest
        || layout.assets_digest() != &binding.assets
    {
        return Err(corrupt());
    }
    let expected = PackageSigningSubject::from_package(
        bundle.manifest_bytes(),
        bundle.config_bytes(),
        PackageLimits::default(),
    )
    .map_err(|_| corrupt())?;
    let signature = &signatures[0];
    let provenance_entry = &provenance[0];
    check_referrer(
        expected.subject(),
        signature,
        EvidenceKind::Signature,
        &old.signature_manifest,
        &old.signature_payload,
        SignatureLimits::default().max_envelope_bytes,
    )?;
    check_referrer(
        expected.subject(),
        provenance_entry,
        EvidenceKind::Provenance,
        &old.provenance_manifest,
        &old.provenance_payload,
        ProvenanceLimits::default().max_envelope_bytes,
    )?;
    let publisher =
        inspect_signature(&signature.payload, SignatureLimits::default()).map_err(|_| corrupt())?;
    let builder = inspect_web_provenance(&provenance_entry.payload, ProvenanceLimits::default())
        .map_err(|_| corrupt())?;
    let outputs = expected.web_outputs().ok_or_else(corrupt)?;
    if publisher.subject() != expected.subject()
        || builder.subject() != expected.subject()
        || publisher.publisher_id().0 != old.publisher
        || publisher.key_hint().as_str() != old.publisher_key
        || builder.builder_id() != old.builder
        || builder.key_hint().as_str() != old.builder_key
        || builder.observation().outputs_digest != outputs.digest().as_str()
        || builder.observation().outputs_count != outputs.count()
        || builder.observation().outputs_bytes != outputs.bytes()
        || bundle
            .sbom()
            .and_then(latent_packaging::CheckedPackageSbom::source_snapshot_digest)
            .is_some_and(|digest| digest.as_str() != builder.observation().source.snapshot_digest)
        || old.verified_at < publisher.validity().issued_at
        || old.valid_until > publisher.validity().expires_at
        || old.verified_at < builder.validity().issued_at
        || old.valid_until > builder.validity().expires_at
    {
        return Err(corrupt());
    }
    check_sbom_history(
        old.sbom_inventory.as_deref(),
        old.sbom_referrer.as_deref(),
        &bundle,
        &sboms,
    )?;
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
