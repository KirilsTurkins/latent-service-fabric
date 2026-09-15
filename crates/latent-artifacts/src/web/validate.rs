use super::{
    exhausted, incompatible, invalid, CheckedWebLayout, WebApplicationManifest, WebAsset,
    WebRenderMode, MAX_WEB_ASSETS, MAX_WEB_ASSET_BYTES, MAX_WEB_ASSET_TREE_BYTES,
    MAX_WEB_MANIFEST_BYTES, MAX_WEB_RENDERER_BYTES, MAX_WEB_ROUTES, WEB_MANIFEST_PATH,
    WEB_RELEASE_PROFILE,
};
use crate::package::{
    artifact_blob_digest, validate_package_json, validate_package_path, verify_layer_bytes,
    LayerRole, PackageKind, PackageLayout, PackageLimits,
};
use latent_core::{ArtifactBlobDigest, PlatformError};
use sha2::{Digest, Sha256};
use std::collections::BTreeSet;

/// Domain-separated, ordered asset table identity. Empty trees, ambiguous paths,
/// duplicate layer aliases, unsupported media types and excessive capacity fail.
pub fn asset_tree_digest(assets: &Vec<WebAsset>) -> Result<ArtifactBlobDigest, PlatformError> {
    if assets.is_empty() || assets.capacity() > MAX_WEB_ASSETS {
        return Err(exhausted());
    }
    let mut hash = Sha256::new();
    part(&mut hash, b"lsf-web-public-assets-v1");
    let mut paths = BTreeSet::new();
    let mut previous: Option<&str> = None;
    let mut total = 0u64;
    for asset in assets {
        path(&asset.path)?;
        validate_package_path(&asset.layer, PackageLimits::default())?;
        if !asset.layer.starts_with("public/")
            || asset.layer.capacity() > 240
            || asset.digest.capacity() > 71
            || asset.media_type.capacity() > 64
            || previous.is_some_and(|value| value >= asset.path.as_str())
            || !paths.insert(&asset.layer)
        {
            return Err(invalid("web-public-asset-path"));
        }
        asset
            .digest
            .parse::<ArtifactBlobDigest>()
            .map_err(|_| invalid("web-asset-digest"))?;
        if media_type(&asset.path) != Some(asset.media_type.as_str())
            || media_type(&asset.layer) != Some(asset.media_type.as_str())
        {
            return Err(invalid("web-asset-media-type"));
        }
        total = total.checked_add(asset.size).ok_or_else(exhausted)?;
        if asset.size > MAX_WEB_ASSET_BYTES || total > MAX_WEB_ASSET_TREE_BYTES {
            return Err(exhausted());
        }
        for value in [&asset.path, &asset.layer, &asset.digest, &asset.media_type] {
            part(&mut hash, value.as_bytes());
        }
        part(&mut hash, &asset.size.to_le_bytes());
        previous = Some(&asset.path);
    }
    Ok(finish(hash))
}

pub use latent_manifest::renderer_profile_digest;

/// Checks the exact manifest blob and every declared descriptor association.
/// Callers must separately verify all layer bytes, renderer semantics and trust.
pub fn inspect_web_layout(
    package: &PackageLayout,
    bytes: &[u8],
) -> Result<CheckedWebLayout, PlatformError> {
    let limits = PackageLimits {
        max_document_bytes: MAX_WEB_MANIFEST_BYTES,
        max_layers: MAX_WEB_ASSETS.max(MAX_WEB_ROUTES),
        max_depth: 8,
        max_string_bytes: 512,
        ..PackageLimits::default()
    };
    validate_package_json(bytes, limits)?;
    let manifest: WebApplicationManifest =
        serde_json::from_slice(bytes).map_err(|_| invalid("web-manifest-schema"))?;
    if manifest.format_version != 1 || manifest.profile != WEB_RELEASE_PROFILE {
        return Err(incompatible());
    }
    let config = package.config();
    if !matches!(
        config.kind,
        PackageKind::BrowserAssets | PackageKind::SsrPackage
    ) || config.component_digest.is_some()
    {
        return Err(incompatible());
    }
    let metadata = config
        .layers
        .iter()
        .find(|layer| layer.path == WEB_MANIFEST_PATH)
        .ok_or_else(|| invalid("web-manifest-missing"))?;
    if metadata.role != LayerRole::Asset || metadata.media_type != "application/json" {
        return Err(invalid("web-manifest-layer"));
    }
    verify_layer_bytes(metadata, bytes, limits)?;
    let assets_digest = asset_tree_digest(&manifest.assets)?;
    if manifest.assets_digest != assets_digest.as_str() {
        return Err(invalid("web-asset-tree-mismatch"));
    }
    for asset in &manifest.assets {
        let layer = config
            .layers
            .iter()
            .find(|layer| layer.path == asset.layer)
            .ok_or_else(|| invalid("web-asset-layer-missing"))?;
        if layer.role != LayerRole::Asset
            || layer.digest.as_str() != asset.digest
            || layer.size != asset.size
            || layer.media_type != asset.media_type
        {
            return Err(invalid("web-asset-layer-mismatch"));
        }
    }
    match (&manifest.renderer, config.kind) {
        (None, PackageKind::BrowserAssets) => {
            if !manifest
                .assets
                .iter()
                .any(|asset| asset.layer == config.entrypoint)
            {
                return Err(invalid("web-entrypoint-not-public"));
            }
        }
        (Some(renderer), PackageKind::SsrPackage) => {
            let layer = config
                .layers
                .iter()
                .find(|layer| layer.path == renderer.layer)
                .ok_or_else(|| invalid("web-renderer-missing"))?;
            if renderer.layer != config.entrypoint
                || layer.role != LayerRole::Renderer
                || layer.media_type != "application/wasm"
                || layer.digest.as_str() != renderer.digest
                || layer.size != renderer.size
                || renderer.assets_digest != assets_digest.as_str()
                || renderer.profile_digest != renderer_profile_digest(renderer.profile).as_str()
            {
                return Err(incompatible());
            }
            if renderer.size == 0 || renderer.size > MAX_WEB_RENDERER_BYTES {
                return Err(exhausted());
            }
        }
        _ => return Err(incompatible()),
    }
    routes(&manifest)?;
    Ok(CheckedWebLayout {
        package: package.digest().clone(),
        manifest_digest: artifact_blob_digest(bytes),
        assets_digest,
        manifest,
    })
}

fn routes(manifest: &WebApplicationManifest) -> Result<(), PlatformError> {
    if manifest.routes.is_empty() || manifest.routes.capacity() > MAX_WEB_ROUTES {
        return Err(exhausted());
    }
    let mut previous: Option<&str> = None;
    for route in &manifest.routes {
        path(&route.path)?;
        if previous.is_some_and(|value| value >= route.path.as_str()) {
            return Err(invalid("web-route-path"));
        }
        previous = Some(&route.path);
        match (route.mode, &route.asset) {
            (WebRenderMode::Server, None) if manifest.renderer.is_some() => (),
            (WebRenderMode::Client | WebRenderMode::Prerender, Some(path)) => {
                let asset = manifest
                    .assets
                    .iter()
                    .find(|asset| &asset.path == path)
                    .ok_or_else(|| invalid("web-route-asset-missing"))?;
                if asset.media_type != "text/html" {
                    return Err(invalid("web-route-document-type"));
                }
            }
            _ => return Err(invalid("web-route-mode")),
        }
    }
    Ok(())
}

fn path(path: &String) -> Result<(), PlatformError> {
    if path.capacity() > 240
        || !path.starts_with('/')
        || path.starts_with(super::IMMUTABLE_ASSET_PREFIX)
    {
        return Err(invalid("web-canonical-path"));
    }
    if path != "/" {
        validate_package_path(&path[1..], PackageLimits::default())?;
    }
    Ok(())
}

fn media_type(path: &str) -> Option<&'static str> {
    match path.rsplit('.').next()? {
        "html" => Some("text/html"),
        "js" | "mjs" => Some("text/javascript"),
        "css" => Some("text/css"),
        "json" => Some("application/json"),
        "txt" => Some("text/plain"),
        "svg" => Some("image/svg+xml"),
        "png" => Some("image/png"),
        "jpg" | "jpeg" => Some("image/jpeg"),
        "webp" => Some("image/webp"),
        "ico" => Some("image/x-icon"),
        "woff2" => Some("font/woff2"),
        _ => None,
    }
}

fn part(hash: &mut Sha256, value: &[u8]) {
    hash.update((value.len() as u64).to_le_bytes());
    hash.update(value);
}

fn finish(hash: Sha256) -> ArtifactBlobDigest {
    format!("sha256:{:x}", hash.finalize())
        .parse()
        .expect("SHA-256")
}
