//! Recover an immutable manifest profile from the exact admitted package.
//! This is a byte association check, never a namespace or execution grant.

use latent_core::{PlatformError, PlatformErrorCode};
use latent_manifest::{CapsuleManifest, JsonManifestCodec, ManifestCodec, TransactionBinding};

use super::corrupt;
use crate::package::{
    inspect_package, verify_layer_bytes, LayerRole, PackageKind, PackageLayer, PackageLimits,
};
use crate::{AdmissionBinding, PackageAdmissionUpload};

pub(super) fn from_upload(
    upload: &PackageAdmissionUpload,
    binding: &AdmissionBinding,
    capsule: &CapsuleManifest,
) -> Result<bool, PlatformError> {
    from_package(
        &upload.manifest,
        &upload.configuration,
        binding,
        capsule,
        |layer| {
            let bytes = upload
                .layers
                .iter()
                .find(|(path, _)| path == &layer.path)
                .map(|(_, bytes)| bytes)
                .ok_or_else(|| corrupt("transaction-profile-layer-missing"))?;
            verify_layer_bytes(layer, bytes, PackageLimits::default())?;
            Ok(bytes.clone())
        },
    )
}

/// Reads at most the original capsule document and the finite companion.
/// The caller has already checked upload/storage limits and admission binding.
pub(super) fn from_package(
    manifest: &[u8],
    configuration: &[u8],
    binding: &AdmissionBinding,
    capsule: &CapsuleManifest,
    mut read: impl FnMut(&PackageLayer) -> Result<Vec<u8>, PlatformError>,
) -> Result<bool, PlatformError> {
    let limits = PackageLimits::default();
    let layout = inspect_package(manifest, configuration, limits)?;
    if layout.digest() != &binding.package
        || layout.config().kind != PackageKind::Capsule
        || layout.component_release().as_ref() != Some(&binding.release)
        || capsule.component_digest != binding.release
        || capsule
            .metadata
            .tenant
            .as_ref()
            .is_some_and(|tenant| tenant != &binding.tenant)
    {
        return Err(corrupt("transaction-profile-package-association"));
    }
    let Some(layer) = layout
        .config()
        .layers
        .iter()
        .find(|layer| layer.path == "transaction-binding.json")
    else {
        return Ok(false);
    };
    if layer.role != LayerRole::Asset
        || layer.media_type != "application/vnd.latent.transaction-binding.v1+json"
        || layer.size > 128 * 1024
    {
        return Err(corrupt("transaction-profile-companion-layer"));
    }
    let original = layout
        .config()
        .layers
        .iter()
        .find(|layer| layer.role == LayerRole::CapsuleManifest)
        .ok_or_else(|| corrupt("transaction-profile-capsule-missing"))?;
    if original.size > limits.max_document_bytes as u64 {
        return Err(corrupt("transaction-profile-capsule-size"));
    }
    let bytes = read(original)?;
    verify_layer_bytes(original, &bytes, limits)?;
    let decoded = JsonManifestCodec::default()
        .decode_capsule(&bytes)
        .map_err(|_| corrupt("transaction-profile-capsule-document"))?;
    if &decoded != capsule {
        return Err(corrupt("transaction-profile-capsule-association"));
    }
    let bytes = read(layer)?;
    verify_layer_bytes(layer, &bytes, limits)?;
    let declaration = TransactionBinding::decode(&bytes)
        .map_err(|_| corrupt("transaction-profile-companion-document"))?;
    if declaration.capsule != capsule.metadata.name
        || capsule.runtime_requirements.renderer.is_some()
    {
        return Err(corrupt("transaction-profile-companion-association"));
    }
    Ok(true)
}

pub(super) fn validate_capsule(
    capsule: &CapsuleManifest,
    selected: bool,
) -> Result<(), Vec<latent_manifest::ManifestViolation>> {
    use latent_manifest::{
        ManifestValidator, Phase1ManifestValidator, Phase4TransactionManifestValidator,
    };
    if selected {
        Phase4TransactionManifestValidator.validate_capsule(capsule)
    } else {
        Phase1ManifestValidator.validate_capsule(capsule)
    }
}

pub(super) fn publication_error() -> PlatformError {
    super::error(
        PlatformErrorCode::InvalidArgument,
        "capsule manifest validation failed",
    )
}
