//! Independently checks retained byte associations before a policy denial can
//! be classified as bounded historical state. No cryptographic trust is added.
use latent_core::PlatformError;
use latent_manifest::{JsonManifestCodec, ManifestCodec};

use super::super::corrupt;
use crate::package::{
    artifact_blob_digest, decode_referrer, inspect_package, verify_layer_bytes, EvidenceKind,
    LayerRole, PackageKind, PackageLimits,
};
use crate::{
    decode_contract_metadata, AdmissionBinding, AdmissionEvidence, ContractMetadataLimits,
    PackageAdmissionUpload, VerifiedArtifactMetadata,
};

pub(super) fn verify(
    binding: &AdmissionBinding,
    upload: &PackageAdmissionUpload,
    metadata: &VerifiedArtifactMetadata,
    codec: &JsonManifestCodec,
) -> Result<(), PlatformError> {
    let limits = PackageLimits::default();
    let layout = inspect_package(&upload.manifest, &upload.configuration, limits)?;
    if layout.digest() != &binding.package
        || layout.config().kind != PackageKind::Capsule
        || metadata.verified_digest() != &binding.release
        || metadata.manifest().metadata.tenant.as_ref() != Some(&binding.tenant)
        || upload.layers.len() != layout.config().layers.len()
    {
        return Err(corrupt("retained-package-association"));
    }
    for (layer, (path, bytes)) in layout.config().layers.iter().zip(&upload.layers) {
        if &layer.path != path {
            return Err(corrupt("retained-package-layer-set"));
        }
        verify_layer_bytes(layer, bytes, limits)?;
        match layer.role {
            LayerRole::Component => {
                if layer.digest.as_str() != binding.release.0
                    || layer.size != metadata.descriptor().size_bytes
                {
                    return Err(corrupt("retained-component-association"));
                }
            }
            LayerRole::CapsuleManifest => {
                let manifest = codec
                    .decode_capsule(bytes)
                    .map_err(|_| corrupt("retained-capsule-manifest"))?;
                if &manifest != metadata.manifest() {
                    return Err(corrupt("retained-capsule-association"));
                }
            }
            LayerRole::Contracts => {
                let contracts = decode_contract_metadata(
                    bytes,
                    ContractMetadataLimits {
                        max_document_bytes: limits.max_document_bytes,
                        ..ContractMetadataLimits::default()
                    },
                )?;
                if contracts != metadata.contracts() {
                    return Err(corrupt("retained-contract-association"));
                }
            }
            LayerRole::WitLock | LayerRole::Asset => {}
            LayerRole::Renderer => return Err(corrupt("retained-capsule-renderer")),
        }
    }
    for (kind, entries) in [
        (EvidenceKind::Signature, &upload.signatures),
        (EvidenceKind::Provenance, &upload.provenance),
        (EvidenceKind::Sbom, &upload.sboms),
    ] {
        for entry in entries {
            evidence(binding, upload.manifest.len(), kind, entry)?;
        }
    }
    Ok(())
}

fn evidence(
    binding: &AdmissionBinding,
    manifest_size: usize,
    kind: EvidenceKind,
    entry: &AdmissionEvidence,
) -> Result<(), PlatformError> {
    let value = decode_referrer(&entry.manifest, PackageLimits::default())?;
    if value.artifact_type != kind.artifact_type()
        || value.subject.digest != binding.package
        || value.subject.size != manifest_size as u64
        || entry.configuration != b"{}"
        || value.config.digest != artifact_blob_digest(&entry.configuration)
        || value.config.size != entry.configuration.len() as u64
        || value.layers.len() != 1
        || value.layers[0].digest != artifact_blob_digest(&entry.payload)
        || value.layers[0].size != entry.payload.len() as u64
    {
        return Err(corrupt("retained-evidence-association"));
    }
    Ok(())
}
