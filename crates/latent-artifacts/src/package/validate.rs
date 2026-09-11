use super::{
    artifact_blob_digest, exceeded, invalid, paths, ArtifactDescriptor, EvidenceKind, LayerRole,
    PackageConfig, PackageKind, PackageLimits, PackageManifest, ReferrerManifest,
    CAPSULE_MANIFEST_MEDIA_TYPE, COMPONENT_MEDIA_TYPE, CONTRACTS_MEDIA_TYPE,
    EMPTY_CONFIG_MEDIA_TYPE, LAYER_PATH_ANNOTATION, LAYER_ROLE_ANNOTATION, OCI_MANIFEST_MEDIA_TYPE,
    PACKAGE_CONFIG_MEDIA_TYPE, WIT_LOCK_MEDIA_TYPE,
};
use latent_core::PlatformError;
use std::collections::BTreeMap;

pub(super) fn config(value: &PackageConfig, limits: PackageLimits) -> Result<(), PlatformError> {
    limits.validate()?;
    if value.format_version != 1 || !paths::name(&value.name) || !paths::version(&value.version) {
        return Err(invalid("invalid-package-config"));
    }
    text(&value.name, limits)?;
    text(&value.version, limits)?;
    annotations(&value.annotations, limits)?;
    layers_count(value.layers.len(), limits)?;
    paths::unique_paths(value.layers.iter().map(|layer| layer.path.as_str()), limits)?;
    paths::path(&value.entrypoint, limits)?;
    text(&value.entrypoint, limits)?;
    let mut counts = BTreeMap::new();
    let mut total = 0;
    for layer in &value.layers {
        layer_fields(
            layer.role,
            &layer.path,
            &layer.media_type,
            layer.size,
            limits,
        )?;
        add_size(&mut total, layer.size, limits)?;
        *counts.entry(layer.role).or_insert(0) += 1;
    }
    kind_roles(value.kind, &counts)?;
    let entry = value
        .layers
        .iter()
        .find(|layer| layer.path == value.entrypoint)
        .ok_or_else(|| invalid("missing-package-entrypoint"))?;
    let expected = match value.kind {
        PackageKind::Capsule => LayerRole::Component,
        PackageKind::BrowserAssets => LayerRole::Asset,
        PackageKind::SsrPackage => LayerRole::Renderer,
    };
    if entry.role != expected {
        return Err(invalid("invalid-package-entrypoint-role"));
    }
    match (&value.component_digest, value.kind) {
        (Some(digest), PackageKind::Capsule) if *digest == entry.digest => (),
        (None, PackageKind::BrowserAssets | PackageKind::SsrPackage) => (),
        _ => return Err(invalid("invalid-package-component-association")),
    }
    Ok(())
}

pub(super) fn manifest(
    value: &PackageManifest,
    limits: PackageLimits,
) -> Result<(), PlatformError> {
    limits.validate()?;
    header(value.schema_version, &value.media_type)?;
    let kind = [
        PackageKind::Capsule,
        PackageKind::BrowserAssets,
        PackageKind::SsrPackage,
    ]
    .into_iter()
    .find(|kind| kind.artifact_type() == value.artifact_type)
    .ok_or_else(|| invalid("unsupported-package-artifact-type"))?;
    annotations(&value.annotations, limits)?;
    config_descriptor(&value.config, limits)?;
    layers_count(value.layers.len(), limits)?;
    let mut counts = BTreeMap::new();
    let mut total = 0;
    for layer in &value.layers {
        let (path, role) = layer_annotations(layer, limits)?;
        let role = [
            LayerRole::Component,
            LayerRole::CapsuleManifest,
            LayerRole::Contracts,
            LayerRole::WitLock,
            LayerRole::Asset,
            LayerRole::Renderer,
        ]
        .into_iter()
        .find(|candidate| candidate.as_str() == role)
        .ok_or_else(|| invalid("unknown-package-layer-role"))?;
        layer_fields(role, path, &layer.media_type, layer.size, limits)?;
        add_size(&mut total, layer.size, limits)?;
        *counts.entry(role).or_insert(0) += 1;
    }
    paths::unique_paths(
        value.layers.iter().map(|layer| {
            layer.annotations.as_ref().expect("checked")[LAYER_PATH_ANNOTATION].as_str()
        }),
        limits,
    )?;
    kind_roles(kind, &counts)
}

pub(super) fn referrer(
    value: &ReferrerManifest,
    limits: PackageLimits,
) -> Result<(), PlatformError> {
    limits.validate()?;
    header(value.schema_version, &value.media_type)?;
    let kind = [
        EvidenceKind::Signature,
        EvidenceKind::Provenance,
        EvidenceKind::Sbom,
    ]
    .into_iter()
    .find(|kind| kind.artifact_type() == value.artifact_type)
    .ok_or_else(|| invalid("unsupported-package-evidence-type"))?;
    annotations(&value.annotations, limits)?;
    if value.config.media_type != EMPTY_CONFIG_MEDIA_TYPE
        || value.config.size != 2
        || value.config.digest != artifact_blob_digest(b"{}")
        || value.config.annotations.is_some()
        || value.subject.media_type != OCI_MANIFEST_MEDIA_TYPE
        || value.subject.size == 0
        || value.subject.size > limits.max_document_bytes as u64
        || value.layers.len() != 1
    {
        return Err(invalid("invalid-package-evidence-association"));
    }
    let layer = &value.layers[0];
    let (path, role) = layer_annotations(layer, limits)?;
    paths::path(path, limits)?;
    if role != "evidence" || layer.media_type != kind.payload_media_type() || layer.size == 0 {
        return Err(invalid("invalid-package-evidence-layer"));
    }
    let mut total = 0;
    add_size(&mut total, layer.size, limits)
}

fn header(version: u32, media_type: &str) -> Result<(), PlatformError> {
    if version != 2 || media_type != OCI_MANIFEST_MEDIA_TYPE {
        return Err(invalid("invalid-package-manifest-header"));
    }
    Ok(())
}
fn config_descriptor(
    value: &ArtifactDescriptor,
    limits: PackageLimits,
) -> Result<(), PlatformError> {
    if value.media_type != PACKAGE_CONFIG_MEDIA_TYPE
        || value.annotations.is_some()
        || value.size == 0
    {
        return Err(invalid("invalid-package-config-descriptor"));
    }
    if value.size > limits.max_document_bytes as u64 {
        return Err(exceeded("package-config-size-limit"));
    }
    Ok(())
}
fn kind_roles(kind: PackageKind, counts: &BTreeMap<LayerRole, usize>) -> Result<(), PlatformError> {
    let required: &[LayerRole] = match kind {
        PackageKind::Capsule => &[
            LayerRole::Component,
            LayerRole::CapsuleManifest,
            LayerRole::Contracts,
            LayerRole::WitLock,
        ],
        PackageKind::BrowserAssets => &[],
        PackageKind::SsrPackage => &[LayerRole::Renderer],
    };
    if required.iter().any(|role| counts.get(role) != Some(&1))
        || counts
            .keys()
            .any(|role| *role != LayerRole::Asset && !required.contains(role))
    {
        return Err(invalid("invalid-package-kind-roles"));
    }
    Ok(())
}
pub(super) fn layer_fields(
    role: LayerRole,
    path: &str,
    media_type: &str,
    size: u64,
    limits: PackageLimits,
) -> Result<(), PlatformError> {
    paths::path(path, limits)?;
    text(path, limits)?;
    text(media_type, limits)?;
    let valid = match role {
        LayerRole::Component => media_type == COMPONENT_MEDIA_TYPE,
        LayerRole::CapsuleManifest => media_type == CAPSULE_MANIFEST_MEDIA_TYPE,
        LayerRole::Contracts => media_type == CONTRACTS_MEDIA_TYPE,
        LayerRole::WitLock => media_type == WIT_LOCK_MEDIA_TYPE,
        LayerRole::Renderer => matches!(media_type, COMPONENT_MEDIA_TYPE | "text/javascript"),
        LayerRole::Asset => paths::media_type(media_type),
    };
    if !valid || (size == 0 && role != LayerRole::Asset) {
        return Err(invalid("invalid-package-layer"));
    }
    if size > limits.max_layer_bytes {
        return Err(exceeded("package-layer-size-limit"));
    }
    Ok(())
}
fn layer_annotations(
    value: &ArtifactDescriptor,
    limits: PackageLimits,
) -> Result<(&str, &str), PlatformError> {
    let values = value
        .annotations
        .as_ref()
        .ok_or_else(|| invalid("missing-package-layer-annotations"))?;
    annotations(values, limits)?;
    match (
        values.get(LAYER_PATH_ANNOTATION),
        values.get(LAYER_ROLE_ANNOTATION),
    ) {
        (Some(path), Some(role)) if values.len() == 2 => Ok((path, role)),
        _ => Err(invalid("invalid-package-layer-annotations")),
    }
}
fn layers_count(count: usize, limits: PackageLimits) -> Result<(), PlatformError> {
    if count == 0 {
        return Err(invalid("empty-package-layers"));
    }
    if count > limits.max_layers {
        return Err(exceeded("package-layer-count-limit"));
    }
    Ok(())
}
fn add_size(total: &mut u64, size: u64, limits: PackageLimits) -> Result<(), PlatformError> {
    *total = total
        .checked_add(size)
        .filter(|n| *n <= limits.max_total_layer_bytes && size <= limits.max_layer_bytes)
        .ok_or_else(|| exceeded("package-total-size-limit"))?;
    Ok(())
}
fn text(value: &str, limits: PackageLimits) -> Result<(), PlatformError> {
    if value.len() > limits.max_string_bytes {
        return Err(exceeded("package-string-limit"));
    }
    Ok(())
}
fn annotations(
    values: &BTreeMap<String, String>,
    limits: PackageLimits,
) -> Result<(), PlatformError> {
    if values.len() > limits.max_annotations {
        return Err(exceeded("package-annotation-limit"));
    }
    for (key, value) in values {
        if key.is_empty()
            || key.len() > 128
            || !key
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'.' | b'_' | b'/' | b'-'))
            || value.chars().any(char::is_control)
        {
            return Err(invalid("invalid-package-annotation"));
        }
        text(key, limits)?;
        text(value, limits)?;
    }
    Ok(())
}
