use std::collections::BTreeMap;

use latent_artifacts::package::{
    artifact_blob_digest, decode_wit_lock, LayerRole, PackageKind, PackageLimits,
};
use latent_packaging::{
    generate_cyclonedx_sbom, LayerInput, PackageInput, SbomDependencyCompleteness, SbomDigestScope,
    SbomEntryKind, SbomEntryOrigin, SbomInventory, SbomInventoryEntry, SbomLimits, SbomPolicy,
    SbomPolicyConfig, SbomPresence, CYCLONEDX_JSON_MEDIA_TYPE, SBOM_PATH,
};

pub fn assets() -> PackageInput {
    PackageInput {
        kind: PackageKind::BrowserAssets,
        name: "sbom-fixture".into(),
        version: "1.0.0".into(),
        entrypoint: "index.html".into(),
        annotations: BTreeMap::new(),
        layers: vec![LayerInput {
            path: "index.html".into(),
            role: LayerRole::Asset,
            media_type: "text/html".into(),
            bytes: b"<p>inventory fixture</p>".to_vec(),
        }],
    }
}

pub fn ssr() -> PackageInput {
    let mut input = assets();
    input.kind = PackageKind::SsrPackage;
    input.entrypoint = "renderer.js".into();
    input.layers[0] = LayerInput {
        path: "renderer.js".into(),
        role: LayerRole::Renderer,
        media_type: "text/javascript".into(),
        bytes: b"export const render = () => 'fixture';".to_vec(),
    };
    input
}

pub fn inventory(input: &PackageInput) -> SbomInventory {
    let lock = input
        .layers
        .iter()
        .find(|layer| layer.role == LayerRole::WitLock)
        .map(|layer| decode_wit_lock(&layer.bytes, PackageLimits::default()).unwrap());
    let entries = input
        .layers
        .iter()
        .filter(|layer| {
            matches!(
                layer.role,
                LayerRole::Component | LayerRole::Renderer | LayerRole::Asset
            )
        })
        .map(|layer| {
            let wit = lock.as_ref().and_then(|lock| {
                lock.packages
                    .iter()
                    .find(|package| package.source_path == layer.path)
            });
            let (kind, scope) = match (layer.role, wit) {
                (_, Some(_)) => (SbomEntryKind::WitPackage, SbomDigestScope::WitSource),
                (LayerRole::Component, _) => {
                    (SbomEntryKind::Component, SbomDigestScope::OutputBytes)
                }
                (LayerRole::Renderer, _) => (SbomEntryKind::Renderer, SbomDigestScope::OutputBytes),
                _ => (SbomEntryKind::Asset, SbomDigestScope::OutputBytes),
            };
            let (name, version) = wit.map_or_else(
                || (layer.path.clone(), None),
                |wit| {
                    let (name, version) = wit.id.rsplit_once('@').unwrap();
                    (name.to_owned(), Some(version.to_owned()))
                },
            );
            SbomInventoryEntry {
                kind,
                name,
                version,
                source: None,
                license_expression: None,
                digest: Some(artifact_blob_digest(&layer.bytes)),
                digest_scope: Some(scope),
                size: Some(layer.bytes.len() as u64),
                path: Some(layer.path.clone()),
                manifest_digest: None,
                manifest_size: None,
                origin: SbomEntryOrigin::PackageInput,
            }
        })
        .collect();
    SbomInventory {
        format_version: 1,
        package_kind: input.kind,
        package_name: input.name.clone(),
        package_version: input.version.clone(),
        dependency_completeness: SbomDependencyCompleteness::DeclaredInputsIncomplete,
        source_snapshot_digest: None,
        entries,
    }
}

pub fn embed(mut input: PackageInput, inventory: SbomInventory) -> PackageInput {
    let document = generate_cyclonedx_sbom(inventory, SbomLimits::default()).unwrap();
    input.layers.push(LayerInput {
        path: SBOM_PATH.into(),
        role: LayerRole::Asset,
        media_type: CYCLONEDX_JSON_MEDIA_TYPE.into(),
        bytes: document.bytes().to_vec(),
    });
    input
}

pub fn policy(embedded: SbomPresence, detached: SbomPresence) -> SbomPolicy {
    SbomPolicy::new(SbomPolicyConfig {
        format_version: 1,
        embedded,
        detached,
        require_source: vec![],
        require_license: vec![],
    })
    .unwrap()
}
