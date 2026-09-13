mod capsule;
pub(crate) use capsule::inspect_capsule;

use std::collections::BTreeMap;

use latent_artifacts::package::{
    artifact_blob_digest, encode_config, encode_manifest, ArtifactDescriptor, LayerRole,
    PackageConfig, PackageKind, PackageLayer, PackageManifest, LAYER_PATH_ANNOTATION,
    LAYER_ROLE_ANNOTATION, OCI_MANIFEST_MEDIA_TYPE, PACKAGE_CONFIG_MEDIA_TYPE,
};
use latent_core::PlatformError;

use crate::{
    inspect_bundle, BuildInputIdentity, BuildReceipt, BundleInput, LayerInput, PackageBundle,
    PackageInput, PackagingLimits, BUILD_INPUTS_PATH,
};

/// Packages exact supplied content and canonical metadata, with an observed-input
/// receipt. This operation does not compile components or fabricate source/build
/// provenance. The package name is independent of the capsule's scoped service name.
pub fn build_package(
    mut input: PackageInput,
    limits: PackagingLimits,
) -> Result<PackageBundle, PlatformError> {
    validate_inputs(&input, limits)?;
    input.layers.sort_by(|a, b| a.path.cmp(&b.path));
    let initial = configuration(&input);
    // Full path/role/count/name validation before metadata conversion or receipt cloning.
    encode_config(&initial, limits.package)?;
    let mut identities = initial
        .layers
        .iter()
        .map(|layer| BuildInputIdentity {
            path: layer.path.clone(),
            role: layer.role,
            input_digest: layer.digest.to_string(),
            input_size: layer.size,
            output_digest: layer.digest.to_string(),
            output_size: layer.size,
        })
        .collect::<Vec<_>>();
    if input.kind == PackageKind::Capsule {
        capsule::canonicalize(&initial, &mut input.layers, limits)?;
    }
    let normalized = configuration(&input);
    for (identity, output) in identities.iter_mut().zip(&normalized.layers) {
        identity.output_digest = output.digest.to_string();
        identity.output_size = output.size;
    }
    let receipt = BuildReceipt::new(identities).encode(limits.package)?;
    input.layers.push(LayerInput {
        path: BUILD_INPUTS_PATH.to_owned(),
        role: LayerRole::Asset,
        media_type: "application/json".to_owned(),
        bytes: receipt,
    });
    input.layers.sort_by(|a, b| a.path.cmp(&b.path));
    let config = configuration(&input);
    let configuration = encode_config(&config, limits.package)?;
    let manifest = encode_manifest(
        &PackageManifest {
            schema_version: 2,
            media_type: OCI_MANIFEST_MEDIA_TYPE.to_owned(),
            artifact_type: config.kind.artifact_type().to_owned(),
            config: ArtifactDescriptor {
                media_type: PACKAGE_CONFIG_MEDIA_TYPE.to_owned(),
                digest: artifact_blob_digest(&configuration),
                size: configuration.len() as u64,
                annotations: None,
            },
            layers: config
                .layers
                .iter()
                .map(|layer| ArtifactDescriptor {
                    media_type: layer.media_type.clone(),
                    digest: layer.digest.clone(),
                    size: layer.size,
                    annotations: Some(BTreeMap::from([
                        (LAYER_PATH_ANNOTATION.to_owned(), layer.path.clone()),
                        (
                            LAYER_ROLE_ANNOTATION.to_owned(),
                            layer.role.as_str().to_owned(),
                        ),
                    ])),
                })
                .collect(),
            annotations: BTreeMap::new(),
        },
        limits.package,
    )?;
    inspect_bundle(
        BundleInput {
            manifest,
            configuration,
            layers: input
                .layers
                .into_iter()
                .map(|layer| (layer.path, layer.bytes))
                .collect(),
        },
        limits,
    )
}

pub(crate) fn validate_inputs(
    input: &PackageInput,
    limits: PackagingLimits,
) -> Result<(), PlatformError> {
    crate::input::check_header(
        &input.name,
        &input.version,
        &input.entrypoint,
        &input.annotations,
        input.layers.len(),
        limits,
    )?;
    let mut total = 0_u64;
    for layer in &input.layers {
        latent_artifacts::package::validate_package_path(&layer.path, limits.package)?;
        if layer.media_type.len() > 128 {
            return Err(crate::exceeded("package-input-metadata-limit"));
        }
        if layer.path == BUILD_INPUTS_PATH {
            return Err(crate::invalid("reserved-build-inputs-path"));
        }
        let size = layer.bytes.len() as u64;
        if size > limits.layer_limit(layer.role, &layer.path) {
            return Err(crate::exceeded("package-input-byte-limit"));
        }
        total = total
            .checked_add(size)
            .filter(|value| *value <= limits.package.max_total_layer_bytes)
            .ok_or_else(|| crate::exceeded("package-input-total-limit"))?;
    }
    Ok(())
}

fn configuration(input: &PackageInput) -> PackageConfig {
    let layers = input
        .layers
        .iter()
        .map(|layer| PackageLayer {
            path: layer.path.clone(),
            role: layer.role,
            media_type: layer.media_type.clone(),
            digest: artifact_blob_digest(&layer.bytes),
            size: layer.bytes.len() as u64,
        })
        .collect::<Vec<_>>();
    let component_digest = layers
        .iter()
        .find(|layer| layer.role == LayerRole::Component)
        .map(|layer| layer.digest.clone());
    PackageConfig {
        format_version: 1,
        kind: input.kind,
        name: input.name.clone(),
        version: input.version.clone(),
        entrypoint: input.entrypoint.clone(),
        component_digest,
        layers,
        annotations: input.annotations.clone(),
    }
}
