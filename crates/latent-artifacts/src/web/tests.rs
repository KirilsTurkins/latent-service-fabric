use super::{
    asset_tree_digest, inspect_web_layout, renderer_profile_digest, WebApplicationManifest,
    WebAsset, WebRenderMode, WebRenderer, WebRendererProfile, WebRoute, MAX_WEB_ASSETS,
    WEB_MANIFEST_PATH, WEB_RELEASE_PROFILE,
};
use crate::package::{
    artifact_blob_digest, encode_config, encode_manifest, inspect_package, ArtifactDescriptor,
    LayerRole, PackageConfig, PackageKind, PackageLayer, PackageLayout, PackageLimits,
    PackageManifest, LAYER_PATH_ANNOTATION, LAYER_ROLE_ANNOTATION, OCI_MANIFEST_MEDIA_TYPE,
    PACKAGE_CONFIG_MEDIA_TYPE,
};
use crate::{LifecycleScope, PublicationRef};
use latent_core::TenantId;
use std::collections::BTreeMap;

pub(crate) fn browser_test_upload() -> crate::PackageAdmissionUpload {
    test_upload(false, b"<h1>Example</h1>")
}

#[cfg(target_os = "linux")]
pub(crate) fn renderer_test_upload(html: &[u8]) -> crate::PackageAdmissionUpload {
    test_upload(true, html)
}

fn test_upload(renderer: bool, html: &[u8]) -> crate::PackageAdmissionUpload {
    let mut document = manifest(renderer);
    document.assets[0].digest = artifact_blob_digest(html).to_string();
    document.assets[0].size = html.len() as u64;
    document.assets_digest = asset_tree_digest(&document.assets).unwrap().to_string();
    if let Some(renderer) = &mut document.renderer {
        renderer.assets_digest.clone_from(&document.assets_digest);
    }
    let (layout, metadata) = package(&document);
    let mut layers = vec![
        ("public/index.html".into(), html.to_vec()),
        (WEB_MANIFEST_PATH.into(), metadata),
        ("metadata/private.json".into(), b"{}".to_vec()),
    ];
    if renderer {
        layers.push(("server/renderer.wasm".into(), b"\0asm\x0d\0\x01\0".to_vec()));
    }
    layers.sort_by(|a: &(String, Vec<u8>), b| a.0.cmp(&b.0));
    let evidence = || crate::AdmissionEvidence {
        manifest: b"{}".to_vec(),
        configuration: b"{}".to_vec(),
        payload: b"mock evidence".to_vec(),
    };
    crate::PackageAdmissionUpload {
        manifest: encode_manifest(layout.manifest(), PackageLimits::default()).unwrap(),
        configuration: encode_config(layout.config(), PackageLimits::default()).unwrap(),
        layers,
        signatures: vec![evidence()],
        provenance: vec![evidence()],
        sboms: vec![],
    }
}

fn manifest(renderer: bool) -> WebApplicationManifest {
    let assets = vec![WebAsset {
        path: "/index.html".into(),
        layer: "public/index.html".into(),
        digest: artifact_blob_digest(b"<h1>Example</h1>").to_string(),
        size: 16,
        media_type: "text/html".into(),
    }];
    let assets_digest = asset_tree_digest(&assets).unwrap().to_string();
    WebApplicationManifest {
        format_version: 1,
        profile: WEB_RELEASE_PROFILE.into(),
        assets_digest: assets_digest.clone(),
        assets,
        routes: vec![WebRoute {
            path: "/".into(),
            mode: if renderer {
                WebRenderMode::Server
            } else {
                WebRenderMode::Client
            },
            asset: if renderer {
                None
            } else {
                Some("/index.html".into())
            },
        }],
        renderer: renderer.then(|| WebRenderer {
            layer: "server/renderer.wasm".into(),
            digest: artifact_blob_digest(b"\0asm\x0d\0\x01\0").to_string(),
            size: 8,
            profile: WebRendererProfile::WasmWebBufferedV1,
            profile_digest: renderer_profile_digest(WebRendererProfile::WasmWebBufferedV1)
                .to_string(),
            assets_digest,
            backend_profile: super::WebBackendProfile::None,
        }),
    }
}

#[test]
fn backend_data_requires_an_explicit_angular_profile_and_nonoptional_import() {
    use super::{WebBackendProfile, WEB_HTTP_CONTRACT, WEB_HTTP_WORLD};
    use latent_core::ContractId;
    use latent_manifest::ContractImport;

    let mut document = manifest(true);
    assert!(!serde_json::to_string(&document)
        .unwrap()
        .contains("backendProfile"));
    document.renderer.as_mut().unwrap().backend_profile = WebBackendProfile::ScopedHttpGetV1;
    let (layout, bytes) = package(&document);
    assert!(inspect_web_layout(&layout, &bytes).is_err());
    let renderer = document.renderer.as_mut().unwrap();
    renderer.profile = WebRendererProfile::AngularSsrComponentV1;
    renderer.profile_digest = renderer_profile_digest(renderer.profile).to_string();
    let (layout, bytes) = package(&document);
    let checked = inspect_web_layout(&layout, &bytes).unwrap();
    assert_eq!(
        checked
            .manifest()
            .renderer
            .as_ref()
            .unwrap()
            .backend_profile
            .world(),
        WEB_HTTP_WORLD
    );
    let mut value = serde_json::to_value(document).unwrap();
    for unsupported in [
        serde_json::Value::Null,
        serde_json::json!("ambient-fetch"),
        serde_json::json!({}),
    ] {
        value["renderer"]["backendProfile"] = unsupported;
        assert!(serde_json::from_value::<WebApplicationManifest>(value.clone()).is_err());
    }
    let mut imports = vec![ContractImport {
        contract: ContractId(WEB_HTTP_CONTRACT.into()),
        optional: false,
    }];
    assert_eq!(
        WebBackendProfile::from_imports(&imports).unwrap(),
        WebBackendProfile::ScopedHttpGetV1
    );
    imports[0].optional = true;
    assert!(WebBackendProfile::from_imports(&imports).is_err());
    imports[0].optional = false;
    imports.push(imports[0].clone());
    assert!(WebBackendProfile::from_imports(&imports).is_err());
    assert_eq!(
        WebBackendProfile::from_imports(&[]).unwrap(),
        WebBackendProfile::None
    );
}

// Descriptor-only fixture: these tests establish layout, not executable surface
// validation or publisher/builder authority. Those gates remain independent.
fn package(document: &WebApplicationManifest) -> (PackageLayout, Vec<u8>) {
    package_bytes(document, serde_json::to_vec(document).unwrap())
}

fn package_bytes(document: &WebApplicationManifest, bytes: Vec<u8>) -> (PackageLayout, Vec<u8>) {
    let mut layers: Vec<_> = document
        .assets
        .iter()
        .map(|asset| PackageLayer {
            path: asset.layer.clone(),
            role: LayerRole::Asset,
            media_type: asset.media_type.clone(),
            digest: asset.digest.parse().unwrap(),
            size: asset.size,
        })
        .collect();
    // Private metadata uses the same broad layer role as public assets.
    for (path, data) in [
        (WEB_MANIFEST_PATH, bytes.as_slice()),
        ("metadata/private.json", b"{}".as_slice()),
    ] {
        layers.push(PackageLayer {
            path: path.into(),
            role: LayerRole::Asset,
            media_type: "application/json".into(),
            digest: artifact_blob_digest(data),
            size: data.len() as u64,
        });
    }
    if let Some(renderer) = &document.renderer {
        layers.push(PackageLayer {
            path: renderer.layer.clone(),
            role: LayerRole::Renderer,
            media_type: "application/wasm".into(),
            digest: renderer.digest.parse().unwrap(),
            size: renderer.size,
        });
    }
    layers.sort_by(|a, b| a.path.cmp(&b.path));
    let limits = PackageLimits::default();
    let config = PackageConfig {
        format_version: 1,
        kind: if document.renderer.is_some() {
            PackageKind::SsrPackage
        } else {
            PackageKind::BrowserAssets
        },
        name: "web-example".into(),
        version: "1.0.0".into(),
        entrypoint: document.renderer.as_ref().map_or_else(
            || document.assets[0].layer.clone(),
            |renderer| renderer.layer.clone(),
        ),
        component_digest: None,
        layers,
        annotations: BTreeMap::new(),
    };
    let config_bytes = encode_config(&config, limits).unwrap();
    let manifest = PackageManifest {
        schema_version: 2,
        media_type: OCI_MANIFEST_MEDIA_TYPE.into(),
        artifact_type: config.kind.artifact_type().into(),
        config: ArtifactDescriptor {
            media_type: PACKAGE_CONFIG_MEDIA_TYPE.into(),
            digest: artifact_blob_digest(&config_bytes),
            size: config_bytes.len() as u64,
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
                    (LAYER_PATH_ANNOTATION.into(), layer.path.clone()),
                    (LAYER_ROLE_ANNOTATION.into(), layer.role.as_str().into()),
                ])),
            })
            .collect(),
        annotations: BTreeMap::new(),
    };
    let manifest_bytes = encode_manifest(&manifest, limits).unwrap();
    (
        inspect_package(&manifest_bytes, &config_bytes, limits).unwrap(),
        bytes,
    )
}

#[test]
fn browser_and_ssr_layouts_have_exact_asset_and_package_identity_without_capsule_identity() {
    for renderer in [false, true] {
        let (package, bytes) = package(&manifest(renderer));
        assert!(package.component_release().is_none());
        let checked = inspect_web_layout(&package, &bytes).unwrap();
        assert_eq!(checked.package(), package.digest());
        assert!(checked.asset("/index.html").is_some());
        assert!(checked.asset("/metadata/private.json").is_none());
        assert!(checked.asset("/server/renderer.wasm").is_none());
        let alice = PublicationRef::package(
            LifecycleScope::Tenant(TenantId("alice".into())),
            package.digest(),
        )
        .unwrap();
        let bob = PublicationRef::package(
            LifecycleScope::Tenant(TenantId("bob".into())),
            package.digest(),
        )
        .unwrap();
        assert_ne!(
            checked.asset_url(&alice, "/index.html").unwrap(),
            checked.asset_url(&bob, "/index.html").unwrap()
        );
        assert!(checked.asset_url(&alice, "/metadata/private.json").is_err());
        assert!(checked.retained_bytes() < 64 * 1024);
    }
}

#[test]
fn asset_identity_and_urls_survive_selection_of_another_package() {
    let first = manifest(false);
    let mut second = first.clone();
    second.assets[0].digest = artifact_blob_digest(b"different page").to_string();
    second.assets[0].size = b"different page".len() as u64;
    second.assets_digest = asset_tree_digest(&second.assets).unwrap().to_string();
    let (p1, b1) = package(&first);
    let (p2, b2) = package(&second);
    let one = inspect_web_layout(&p1, &b1).unwrap();
    let two = inspect_web_layout(&p2, &b2).unwrap();
    let scope = LifecycleScope::Tenant(TenantId("alice".into()));
    let original = PublicationRef::package(scope.clone(), p1.digest()).unwrap();
    let selected = PublicationRef::package(scope, p2.digest()).unwrap();
    assert_ne!(
        one.asset_url(&original, "/index.html").unwrap(),
        two.asset_url(&selected, "/index.html").unwrap()
    );
    assert!(one.asset_url(&selected, "/index.html").is_err());
    assert_eq!(
        one.asset("/index.html").unwrap().digest,
        first.assets[0].digest
    );
}

#[test]
fn renderer_requires_the_same_asset_tree_and_supported_compatibility_identity() {
    for kind in 0..3 {
        let mut document = manifest(true);
        let renderer = document.renderer.as_mut().unwrap();
        match kind {
            0 => renderer.assets_digest = artifact_blob_digest(b"another tree").to_string(),
            1 => renderer.profile_digest = artifact_blob_digest(b"another engine").to_string(),
            _ => renderer.profile = WebRendererProfile::AngularSsrComponentV1,
        }
        let (package, bytes) = package(&document);
        assert!(inspect_web_layout(&package, &bytes).is_err());
    }
}

#[test]
fn unknown_fields_and_duplicate_keys_are_rejected_even_in_an_integrity_checked_package() {
    let document = manifest(false);
    for prefix in ["\"admin\":true,", "\"formatVersion\":1,"] {
        let valid = serde_json::to_string(&document).unwrap();
        let bytes = format!("{{{prefix}{}", &valid[1..]).into_bytes();
        let (package, bytes) = package_bytes(&document, bytes);
        assert!(inspect_web_layout(&package, &bytes).is_err());
    }
}

#[test]
fn public_paths_media_types_order_and_spare_capacity_are_bounded() {
    for path in [
        "//index.html",
        "/../index.html",
        "/a%2findex.html",
        "/a\\index.html",
        "/index.html?x",
        "/_lsf/assets/index.html",
    ] {
        let mut document = manifest(false);
        document.assets[0].path = path.into();
        assert!(asset_tree_digest(&document.assets).is_err(), "{path}");
    }
    let mut document = manifest(false);
    document.assets[0].layer = "metadata/private.json".into();
    assert!(asset_tree_digest(&document.assets).is_err());
    document = manifest(false);
    document.assets[0].media_type = "text/javascript".into();
    assert!(asset_tree_digest(&document.assets).is_err());
    document = manifest(false);
    document.assets.push(document.assets[0].clone());
    assert!(asset_tree_digest(&document.assets).is_err());
    document = manifest(false);
    document.assets.reserve_exact(MAX_WEB_ASSETS + 1);
    assert!(asset_tree_digest(&document.assets).is_err());
}

#[test]
fn browser_routes_cannot_claim_a_renderer_and_server_routes_cannot_name_arbitrary_files() {
    let mut document = manifest(false);
    document.routes[0].mode = WebRenderMode::Server;
    document.routes[0].asset = None;
    let (package, bytes) = package(&document);
    assert!(inspect_web_layout(&package, &bytes).is_err());
    let mut document = manifest(true);
    document.routes[0].asset = Some("/metadata/private.json".into());
    let (package, bytes) = self::package(&document);
    assert!(inspect_web_layout(&package, &bytes).is_err());
}
