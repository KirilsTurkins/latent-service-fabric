use latent_artifacts::package::{LayerRole, PackageKind};
use latent_artifacts::{
    decode_contract_metadata, AdmissionBinding, AdmissionStorageLimits, ArtifactDescriptor,
    CapsuleArtifact, ContractMetadataLimits, PackageAdmissionUpload, VerifiedAdmission,
};
use latent_core::{ArtifactReference, PlatformError, ReleaseDigest, TenantId};
use latent_manifest::{JsonManifestCodec, ManifestCodec, ManifestLimits};
use latent_packaging::{
    evaluate_sboms, inspect_bundle, BundleInput, PackageBundle, PackagingLimits,
    SbomEvidenceLimits, SbomEvidenceRef,
};
use latent_signing::{PackageSigningSubject, ProvenanceEvidenceRef, SignatureEvidenceRef};
use std::collections::BTreeMap;
use std::sync::Arc;

use super::{denied, grant::Grant, invalid, receipt::Receipt, Inner};

pub(super) fn verify(
    owner: &Arc<Inner>,
    tenant: &TenantId,
    upload: PackageAdmissionUpload,
    previous: Option<&AdmissionBinding>,
) -> Result<VerifiedAdmission, PlatformError> {
    // Reservation precedes all decode/copy work. One bounded owner slot, no
    // waiting queue; reject spare-capacity abuse before holding received data.
    let mut state = owner.lock()?;
    with_state(owner, tenant, upload, previous, &mut state)
}

// Keep the ordered verification-to-grant transaction visible under one fence.
#[allow(clippy::too_many_lines)]
pub(super) fn with_state(
    owner: &Arc<Inner>,
    tenant: &TenantId,
    upload: PackageAdmissionUpload,
    previous: Option<&AdmissionBinding>,
    state: &mut super::State,
) -> Result<VerifiedAdmission, PlatformError> {
    let now = owner.sample(state)?;
    if !super::config::identifier(&tenant.0) || !state.policy.tenants.contains_key(&tenant.0) {
        return Err(denied("admission-tenant-denied"));
    }
    let limits = PackagingLimits::default();
    let component_limit = usize::try_from(limits.package.max_layer_bytes)
        .map_err(|_| invalid("admission-component-limit"))?;
    AdmissionStorageLimits::default().check_upload(&upload, component_limit)?;
    // The v1 admission profile selects exactly one independent publisher and
    // builder. Extra evidence is ambiguous, never an order-dependent fallback.
    if upload.signatures.len() != 1 || upload.provenance.len() != 1 {
        return Err(denied("admission-required-evidence-cardinality"));
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
        limits,
    )?;
    if bundle.layout().config().kind != PackageKind::Capsule {
        return Err(denied("admission-executable-package-required"));
    }
    let subject = PackageSigningSubject::from_package(
        bundle.manifest_bytes(),
        bundle.config_bytes(),
        limits.package,
    )?;
    let signature = &signatures[0];
    let publisher = state.publisher.verify_package(
        &subject,
        SignatureEvidenceRef {
            manifest: &signature.manifest,
            config: &signature.configuration,
            payload: &signature.payload,
        },
        now,
    )?;
    if !state
        .policy
        .tenants
        .get(&tenant.0)
        .is_some_and(|publishers| publishers.contains(&publisher.publisher().0))
    {
        return Err(denied("admission-tenant-publisher-denied"));
    }
    let provenance_entry = &provenance[0];
    let builder = state.builder.verify_package(
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
        &bundle,
        &evidence,
        &state.policy.sbom,
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
    let artifact = artifact(&bundle, tenant, publisher.publisher().clone())?;
    let receipt = Receipt {
        format_version: 1,
        disposition: "admitted".to_owned(),
        tenant: tenant.0.clone(),
        package: subject.subject().digest.to_string(),
        release: artifact.descriptor.release_digest.0.clone(),
        publisher: publisher.publisher().0.clone(),
        publisher_key: publisher.key_fingerprint().to_string(),
        signature_manifest: publisher.evidence_digest().to_string(),
        signature_payload: publisher.payload_digest().to_string(),
        builder: builder.builder_id().to_owned(),
        builder_key: builder.key_fingerprint().to_string(),
        provenance_manifest: builder.evidence_digest().to_string(),
        provenance_payload: builder.payload_digest().to_string(),
        sbom_inventory: sbom.inventory_digest().map(ToString::to_string),
        sbom_referrer: sbom.referrer_digest().map(ToString::to_string),
        policy: state.policy.identity.clone(),
        policy_digest: state.policy.identity.digest()?,
        epoch: state.floor.epoch,
        verified_at: now,
        valid_until: publisher
            .valid_until()
            .min(builder.valid_until())
            .min(state.policy.identity.valid_until),
    };
    let binding = if let Some(previous) = previous {
        Receipt::recover(previous, &receipt)?;
        previous.clone()
    } else {
        AdmissionBinding {
            tenant: tenant.clone(),
            package: subject.subject().digest.clone(),
            release: artifact.descriptor.release_digest.clone(),
            receipt: receipt.encode()?,
        }
    };
    let grant = Arc::new(Grant {
        owner: Arc::clone(owner),
        binding,
        epoch: state.floor.epoch,
        publisher,
        builder,
    });
    grant.check(owner, state)?;
    let BundleInput {
        manifest,
        configuration,
        layers,
    } = bundle.into_input();
    Ok(VerifiedAdmission {
        artifact,
        upload: PackageAdmissionUpload {
            manifest,
            configuration,
            layers,
            signatures,
            provenance,
            sboms,
        },
        grant,
    })
}

fn artifact(
    bundle: &PackageBundle,
    tenant: &TenantId,
    publisher: latent_core::PublisherId,
) -> Result<CapsuleArtifact, PlatformError> {
    let content = |role| -> Result<&[u8], PlatformError> {
        let layer = bundle
            .layout()
            .config()
            .layers
            .iter()
            .find(|layer| layer.role == role)
            .ok_or_else(|| invalid("admission-package-layer-missing"))?;
        bundle
            .blob(&layer.path)
            .ok_or_else(|| invalid("admission-package-layer-missing"))
    };
    let manifest = JsonManifestCodec::new(ManifestLimits {
        max_document_bytes: 256 * 1024,
        ..ManifestLimits::default()
    })
    .decode_capsule(content(LayerRole::CapsuleManifest)?)
    .map_err(|_| invalid("admission-capsule-manifest"))?;
    if manifest.metadata.tenant.as_ref() != Some(tenant) {
        return Err(denied("admission-capsule-tenant-mismatch"));
    }
    let contracts = decode_contract_metadata(
        content(LayerRole::Contracts)?,
        ContractMetadataLimits::default(),
    )?;
    let component = content(LayerRole::Component)?;
    let release = bundle
        .layout()
        .config()
        .component_digest
        .as_ref()
        .ok_or_else(|| invalid("admission-component-missing"))?;
    Ok(CapsuleArtifact {
        descriptor: ArtifactDescriptor {
            reference: ArtifactReference(format!("package:{}", bundle.layout().digest())),
            release_digest: ReleaseDigest(release.to_string()),
            media_type: "application/wasm".to_owned(),
            size_bytes: component.len() as u64,
            publisher: Some(publisher),
            layers: Vec::new(),
            annotations: BTreeMap::new(),
        },
        manifest,
        contracts,
        component_bytes: component.to_vec(),
    })
}
