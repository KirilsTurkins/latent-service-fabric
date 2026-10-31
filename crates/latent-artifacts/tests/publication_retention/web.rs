//! Explicitly injected non-cryptographic authority; tests native storage, not signature validation.
use crate::support::{context, Root};
use latent_artifacts::package::{
    artifact_blob_digest, encode_config, encode_manifest, inspect_package, ArtifactDescriptor,
    LayerRole, PackageConfig, PackageKind, PackageLayer, PackageLayout, PackageLimits,
    PackageManifest, LAYER_PATH_ANNOTATION, LAYER_ROLE_ANNOTATION, OCI_MANIFEST_MEDIA_TYPE,
    PACKAGE_CONFIG_MEDIA_TYPE,
};
use latent_artifacts::{web::*, *};
use latent_core::{PlatformError, PlatformErrorCode, TenantId};
use std::{any::Any, collections::BTreeMap, sync::Arc};
fn error(code: PlatformErrorCode, message: &str) -> PlatformError {
    PlatformError {
        code,
        message: message.into(),
        retryable: false,
        details: Vec::new(),
    }
}
pub fn open(root: &Root) -> DirectoryArtifactRepository {
    DirectoryArtifactRepository::open_enforced(
        root.path(),
        DirectoryArtifactRepositoryConfig::default(),
        AdmissionStorageLimits::default(),
        Arc::new(Host),
    )
    .unwrap()
}
pub fn publish(repo: &DirectoryArtifactRepository) -> PublicationRef {
    repo.publish_web_package(
        context("publish-web", 0),
        browser_test_upload(),
        &mut |_| Ok(()),
    )
    .unwrap()
    .receipt
    .publication
}
struct Host;
struct Grant(WebAdmissionBinding);
impl WebAdmissionGrant for Grant {
    fn as_any(&self) -> &dyn Any {
        self
    }
    fn binding(&self) -> &WebAdmissionBinding {
        &self.0
    }
    fn retained_bytes(&self) -> usize {
        1024
    }
    fn check_current(&self) -> Result<(), PlatformError> {
        Ok(())
    }
    fn with_current(
        &self,
        action: &mut dyn FnMut(&dyn AdmissionRecheck) -> Result<(), PlatformError>,
    ) -> Result<(), PlatformError> {
        action(self)
    }
}
impl AdmissionRecheck for Grant {
    fn check(&self) -> Result<(), PlatformError> {
        Ok(())
    }
    fn check_web_grant(&self, grant: &dyn WebAdmissionGrant) -> Result<(), PlatformError> {
        if !grant.as_any().is::<Grant>() {
            return Err(error(
                latent_core::PlatformErrorCode::PermissionDenied,
                "mock-web-grant",
            ));
        }
        grant.check_current()
    }
}
impl AdmissionAuthority for Host {
    fn verify(
        &self,
        _: &TenantId,
        _: PackageAdmissionUpload,
    ) -> Result<VerifiedAdmission, PlatformError> {
        Err(error(
            latent_core::PlatformErrorCode::PermissionDenied,
            "mock-capsule-unsupported",
        ))
    }
    fn recover(
        &self,
        _: &AdmissionBinding,
        _: PackageAdmissionUpload,
    ) -> Result<VerifiedAdmission, PlatformError> {
        Err(error(
            latent_core::PlatformErrorCode::PermissionDenied,
            "mock-capsule-unsupported",
        ))
    }
    fn verify_web(
        &self,
        tenant: &TenantId,
        upload: PackageAdmissionUpload,
    ) -> Result<VerifiedWebAdmission, PlatformError> {
        let package = latent_artifacts::package::inspect_package(
            &upload.manifest,
            &upload.configuration,
            latent_artifacts::package::PackageLimits::default(),
        )?;
        let metadata = &upload
            .layers
            .iter()
            .find(|(path, _)| path == WEB_MANIFEST_PATH)
            .unwrap()
            .1;
        let layout = inspect_web_layout(&package, metadata)?;
        let binding = WebAdmissionBinding {
            tenant: tenant.clone(),
            package: layout.package().clone(),
            manifest: layout.manifest_digest().clone(),
            assets: layout.assets_digest().clone(),
            receipt: b"mock web admission".to_vec(),
        };
        Ok(VerifiedWebAdmission {
            layout,
            upload,
            grant: Arc::new(Grant(binding)),
        })
    }
    fn recover_web(
        &self,
        binding: &WebAdmissionBinding,
        upload: PackageAdmissionUpload,
    ) -> Result<VerifiedWebAdmission, PlatformError> {
        let value = self.verify_web(&binding.tenant, upload)?;
        assert_eq!(value.grant.binding(), binding);
        Ok(value)
    }
}

fn browser_test_upload() -> latent_artifacts::PackageAdmissionUpload {
    test_upload(false, b"<h1>Example</h1>")
}

fn test_upload(renderer: bool, html: &[u8]) -> latent_artifacts::PackageAdmissionUpload {
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
    let evidence = || latent_artifacts::AdmissionEvidence {
        manifest: b"{}".to_vec(),
        configuration: b"{}".to_vec(),
        payload: b"mock evidence".to_vec(),
    };
    latent_artifacts::PackageAdmissionUpload {
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
        style_hashes: Vec::new(),
        static_routing: None,
        renderer: renderer.then(|| WebRenderer {
            layer: "server/renderer.wasm".into(),
            digest: artifact_blob_digest(b"\0asm\x0d\0\x01\0").to_string(),
            size: 8,
            profile: WebRendererProfile::WasmWebBufferedV1,
            profile_digest: renderer_profile_digest(WebRendererProfile::WasmWebBufferedV1)
                .to_string(),
            assets_digest,
            backend_profile: WebBackendProfile::None,
        }),
    }
}

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
