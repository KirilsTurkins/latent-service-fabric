use std::collections::BTreeMap;

use latent_artifacts::package::{
    artifact_blob_digest, decode_wit_lock, encode_wit_lock, validate_wit_lock, LayerRole,
    PackageConfig,
};
use latent_artifacts::{
    decode_contract_metadata, encode_contract_metadata, ContractMetadataLimits,
};
use latent_core::PlatformError;
use latent_manifest::{
    JsonManifestCodec, ManifestCodec, ManifestLimits, ManifestValidator, Phase1ManifestValidator,
};

use crate::{CheckedSurface, LayerInput, PackagingLimits};

pub(super) fn canonicalize(
    config: &PackageConfig,
    layers: &mut [LayerInput],
    limits: PackagingLimits,
) -> Result<(), PlatformError> {
    let manifest_index = role_index(layers, LayerRole::CapsuleManifest)?;
    let contracts_index = role_index(layers, LayerRole::Contracts)?;
    let lock_index = role_index(layers, LayerRole::WitLock)?;
    let codec = manifest_codec(limits);
    let manifest = codec
        .decode_capsule(&layers[manifest_index].bytes)
        .map_err(|_| crate::invalid("invalid-package-capsule-manifest"))?;
    let contracts =
        decode_contract_metadata(&layers[contracts_index].bytes, contract_limits(limits))?;
    let mut lock = decode_wit_lock(&layers[lock_index].bytes, limits.package)?;
    // Reject contradictory supplied associations before normalizing any bytes.
    validate_wit_lock(config, &lock, limits.package)?;
    layers[manifest_index].bytes = codec
        .encode_capsule(&manifest)
        .map_err(|_| crate::invalid("invalid-package-capsule-manifest"))?;
    layers[contracts_index].bytes = encode_contract_metadata(&contracts, contract_limits(limits))?;
    lock.contracts_digest = artifact_blob_digest(&layers[contracts_index].bytes);
    layers[lock_index].bytes = encode_wit_lock(&lock, limits.package)?;
    Ok(())
}

fn role_index(layers: &[LayerInput], role: LayerRole) -> Result<usize, PlatformError> {
    layers
        .iter()
        .position(|layer| layer.role == role)
        .ok_or_else(|| crate::invalid("missing-capsule-content"))
}

pub(crate) fn inspect_capsule(
    config: &PackageConfig,
    blobs: &[(String, Vec<u8>)],
    limits: PackagingLimits,
) -> Result<CheckedSurface, PlatformError> {
    let content = |role| -> Result<&[u8], PlatformError> {
        let index = config
            .layers
            .iter()
            .position(|layer| layer.role == role)
            .ok_or_else(|| crate::invalid("missing-capsule-content"))?;
        Ok(&blobs[index].1)
    };
    let manifest = manifest_codec(limits)
        .decode_capsule(content(LayerRole::CapsuleManifest)?)
        .map_err(|_| crate::invalid("invalid-package-capsule-manifest"))?;
    Phase1ManifestValidator
        .validate_capsule(&manifest)
        .map_err(|_| crate::invalid("unsupported-package-capsule-manifest"))?;
    if manifest.semantic_version != config.version {
        return Err(crate::invalid("package-capsule-version-mismatch"));
    }
    let contracts =
        decode_contract_metadata(content(LayerRole::Contracts)?, contract_limits(limits))?;
    let lock = decode_wit_lock(content(LayerRole::WitLock)?, limits.package)?;
    validate_wit_lock(config, &lock, limits.package)?;
    let sources = lock
        .packages
        .iter()
        .map(|package| {
            let index = config
                .layers
                .iter()
                .position(|layer| layer.path == package.source_path)
                .expect("validated WIT source association");
            (package.source_path.clone(), blobs[index].1.as_slice())
        })
        .collect::<BTreeMap<_, _>>();
    crate::validate_capsule(
        content(LayerRole::Component)?,
        &manifest,
        &contracts,
        &lock,
        &sources,
        limits.semantics,
    )
}

fn manifest_codec(limits: PackagingLimits) -> JsonManifestCodec {
    JsonManifestCodec::new(ManifestLimits {
        max_document_bytes: limits.package.max_document_bytes,
        max_nesting_depth: limits.package.max_depth,
        max_string_bytes: limits.package.max_string_bytes,
        max_collection_entries: limits.package.max_layers.max(16),
        max_violations: 32,
    })
}

fn contract_limits(limits: PackagingLimits) -> ContractMetadataLimits {
    ContractMetadataLimits {
        max_document_bytes: limits.package.max_document_bytes,
        max_nodes: limits.package.max_nodes,
        max_string_bytes: limits.package.max_string_bytes,
        max_retained_bytes: limits.package.max_document_bytes.saturating_mul(8),
        ..ContractMetadataLimits::default()
    }
}
