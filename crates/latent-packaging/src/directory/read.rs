mod inventory;

use std::collections::BTreeMap;
use std::path::Path;

use cap_fs_ext::DirExt;
use latent_artifacts::package::{
    artifact_blob_digest, encode_config, inspect_package, validate_package_json,
    validate_package_path, LayerRole, PackageConfig, PackageLayer,
};
use latent_core::PlatformError;

use crate::{
    inspect_bundle, BundleInput, LayerInput, PackageBundle, PackageInput, PackageSource,
    PackagingLimits, BUILD_INPUTS_PATH,
};

/// Decodes the bounded v1 explicit file-selection recipe. Source paths are
/// portable relative names below the separately supplied root capability.
pub fn decode_package_source(
    bytes: &[u8],
    limits: PackagingLimits,
) -> Result<PackageSource, PlatformError> {
    limits.validate()?;
    validate_package_json(bytes, limits.package)?;
    let source: PackageSource =
        serde_json::from_slice(bytes).map_err(|_| crate::invalid("invalid-package-source-json"))?;
    validate_source(&source, limits)?;
    Ok(source)
}

/// Reads only selected regular files, rejecting symlinks in all descendant path
/// segments. Reads charge the aggregate bound before retaining each next file.
pub fn read_package_input(
    root: &Path,
    source: &PackageSource,
    limits: PackagingLimits,
) -> Result<PackageInput, PlatformError> {
    validate_source(source, limits)?;
    let root = super::open_root(root)?;
    let mut layers = Vec::with_capacity(source.layers.len());
    let mut remaining = limits.package.max_total_layer_bytes;
    for file in &source.layers {
        let bytes = super::io::read(
            &root,
            &file.source,
            limits.document_limit(file.role).min(remaining),
            limits.package,
        )?;
        remaining -= bytes.len() as u64;
        layers.push(LayerInput {
            path: file.path.clone(),
            role: file.role,
            media_type: file.media_type.clone(),
            bytes,
        });
    }
    Ok(PackageInput {
        kind: source.kind,
        name: source.name.clone(),
        version: source.version.clone(),
        entrypoint: source.entrypoint.clone(),
        annotations: source.annotations.clone(),
        layers,
    })
}

fn validate_source(source: &PackageSource, limits: PackagingLimits) -> Result<(), PlatformError> {
    crate::input::check_header(
        &source.name,
        &source.version,
        &source.entrypoint,
        &source.annotations,
        source.layers.len(),
        limits,
    )?;
    if source.format_version != 1 {
        return Err(crate::invalid("unsupported-package-source-version"));
    }
    for file in &source.layers {
        validate_package_path(&file.path, limits.package)?;
        validate_package_path(&file.source, limits.package)?;
        if file.path == BUILD_INPUTS_PATH {
            return Err(crate::invalid("reserved-build-inputs-path"));
        }
        if file.media_type.len() > 128 {
            return Err(crate::exceeded("package-input-metadata-limit"));
        }
    }
    // Validate the complete logical role/path/header shape before touching files.
    // These are structural placeholders, never published as content identities.
    let placeholder = artifact_blob_digest(&[0]);
    let mut layers = source
        .layers
        .iter()
        .map(|file| PackageLayer {
            path: file.path.clone(),
            role: file.role,
            media_type: file.media_type.clone(),
            digest: placeholder.clone(),
            size: u64::from(file.role != LayerRole::Asset),
        })
        .collect::<Vec<_>>();
    layers.sort_by(|a, b| a.path.cmp(&b.path));
    let component_digest = layers
        .iter()
        .find(|layer| layer.role == LayerRole::Component)
        .map(|layer| layer.digest.clone());
    encode_config(
        &PackageConfig {
            format_version: 1,
            kind: source.kind,
            name: source.name.clone(),
            version: source.version.clone(),
            entrypoint: source.entrypoint.clone(),
            component_digest,
            layers,
            annotations: source.annotations.clone(),
        },
        limits.package,
    )?;
    Ok(())
}

/// Reads and inspects an exported package directory. The inventory must contain
/// exactly the envelope, config and declared blobs; extras are rejected within
/// a count bound derived from the validated logical paths.
pub fn read_package_directory(
    root: &Path,
    limits: PackagingLimits,
) -> Result<PackageBundle, PlatformError> {
    limits.validate()?;
    let root = super::open_root(root)?;
    let maximum = limits.package.max_document_bytes as u64;
    let manifest = super::io::read(&root, "manifest.json", maximum, limits.package)?;
    let configuration = super::io::read(&root, "config.json", maximum, limits.package)?;
    let layout = inspect_package(&manifest, &configuration, limits.package)?;
    let mut expected = BTreeMap::from([
        ("manifest.json".to_owned(), false),
        ("config.json".to_owned(), false),
        ("layers".to_owned(), true),
    ]);
    for layer in &layout.config().layers {
        let mut path = "layers".to_owned();
        let mut segments = layer.path.split('/').peekable();
        while let Some(segment) = segments.next() {
            path.push('/');
            path.push_str(segment);
            expected.insert(path.clone(), segments.peek().is_some());
        }
    }
    inventory::check(&root, &expected)?;
    let layer_root = root.open_dir_nofollow("layers").map_err(super::io_error)?;
    let mut layers = Vec::with_capacity(layout.config().layers.len());
    for layer in &layout.config().layers {
        let mut maximum = layer.size.min(limits.document_limit(layer.role));
        if layer.path == BUILD_INPUTS_PATH {
            maximum = maximum.min(limits.package.max_document_bytes as u64);
        }
        let bytes = super::io::read(&layer_root, &layer.path, maximum, limits.package)?;
        layers.push((layer.path.clone(), bytes));
    }
    inspect_bundle(
        BundleInput {
            manifest,
            configuration,
            layers,
        },
        limits,
    )
}
