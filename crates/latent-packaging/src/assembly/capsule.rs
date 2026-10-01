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
    limits: &PackagingLimits,
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
    limits: &PackagingLimits,
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
    let host_profile = host_profile(config, blobs, &manifest)?;
    crate::semantics::validate_capsule_for_profile(
        content(LayerRole::Component)?,
        &manifest,
        &contracts,
        &lock,
        &sources,
        limits.semantics,
        host_profile,
    )
}

fn host_profile(
    config: &PackageConfig,
    blobs: &[(String, Vec<u8>)],
    manifest: &latent_manifest::CapsuleManifest,
) -> Result<latent_core::HostAbiProfile, PlatformError> {
    let Some(layer) = config
        .layers
        .iter()
        .find(|layer| layer.path == "transaction-binding.json")
    else {
        return Ok(latent_core::PHASE3_HOST_ABI_CURRENT);
    };
    if layer.role != LayerRole::Asset
        || layer.media_type != "application/vnd.latent.transaction-binding.v1+json"
    {
        return Err(crate::invalid("invalid-transaction-companion-layer"));
    }
    let bytes = blobs
        .iter()
        .find(|(path, _)| path == &layer.path)
        .map(|(_, bytes)| bytes.as_slice())
        .ok_or_else(|| crate::invalid("missing-transaction-companion"))?;
    let binding = latent_manifest::TransactionBinding::decode(bytes)
        .map_err(|_| crate::invalid("invalid-transaction-companion"))?;
    if binding.capsule != manifest.metadata.name || manifest.runtime_requirements.renderer.is_some()
    {
        return Err(crate::invalid("transaction-companion-capsule-mismatch"));
    }
    // Exact-byte layer association is already checked by inspect_bundle. The
    // companion selects only immutable ABI inspection, never an installed host,
    // deployment, namespace, policy, or execution admission.
    Ok(latent_core::PHASE4_HOST_ABI_V1)
}

fn manifest_codec(limits: &PackagingLimits) -> JsonManifestCodec {
    JsonManifestCodec::new(ManifestLimits {
        max_document_bytes: limits.package.max_document_bytes,
        max_nesting_depth: limits.package.max_depth,
        max_string_bytes: limits.package.max_string_bytes,
        max_collection_entries: limits.package.max_layers.max(16),
        max_violations: 32,
    })
}

fn contract_limits(limits: &PackagingLimits) -> ContractMetadataLimits {
    ContractMetadataLimits {
        max_document_bytes: limits.package.max_document_bytes,
        max_nodes: limits.package.max_nodes,
        max_string_bytes: limits.package.max_string_bytes,
        max_retained_bytes: limits.package.max_document_bytes.saturating_mul(8),
        ..ContractMetadataLimits::default()
    }
}
