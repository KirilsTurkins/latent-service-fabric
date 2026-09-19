//! Test-only authority: these tests exercise storage/admission separation, not
//! cryptographic publisher verification (covered by latent-policy).
use latent_artifacts::{package::*, web::*, *};
use latent_core::{PlatformError, PlatformErrorCode, TenantId};
use std::{
    any::Any,
    collections::BTreeMap,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
};

pub(super) struct Authority(pub Arc<AtomicBool>);
struct Grant {
    binding: WebAdmissionBinding,
    current: Arc<AtomicBool>,
}
impl AdmissionRecheck for Grant {
    fn check(&self) -> Result<(), PlatformError> {
        if self.current.load(Ordering::Acquire) {
            Ok(())
        } else {
            Err(denied())
        }
    }
}
impl WebAdmissionGrant for Grant {
    fn as_any(&self) -> &dyn Any {
        self
    }
    fn binding(&self) -> &WebAdmissionBinding {
        &self.binding
    }
    fn retained_bytes(&self) -> usize {
        1024
    }
    fn check_current(&self) -> Result<(), PlatformError> {
        self.check()
    }
    fn with_current(
        &self,
        action: &mut dyn FnMut(&dyn AdmissionRecheck) -> Result<(), PlatformError>,
    ) -> Result<(), PlatformError> {
        self.check()?;
        action(self)
    }
}
impl AdmissionAuthority for Authority {
    fn verify(
        &self,
        _: &TenantId,
        _: PackageAdmissionUpload,
    ) -> Result<VerifiedAdmission, PlatformError> {
        Err(denied())
    }
    fn recover(
        &self,
        _: &AdmissionBinding,
        _: PackageAdmissionUpload,
    ) -> Result<VerifiedAdmission, PlatformError> {
        Err(denied())
    }
    fn verify_web(
        &self,
        tenant: &TenantId,
        upload: PackageAdmissionUpload,
    ) -> Result<VerifiedWebAdmission, PlatformError> {
        let package = inspect_package(
            &upload.manifest,
            &upload.configuration,
            PackageLimits::default(),
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
            receipt: b"test web authority".to_vec(),
        };
        let grant = Arc::new(Grant {
            binding,
            current: Arc::clone(&self.0),
        });
        Ok(VerifiedWebAdmission {
            layout,
            upload,
            grant,
        })
    }
    fn recover_web(
        &self,
        binding: &WebAdmissionBinding,
        upload: PackageAdmissionUpload,
    ) -> Result<VerifiedWebAdmission, PlatformError> {
        self.verify_web(&binding.tenant, upload)
    }
}
fn denied() -> PlatformError {
    PlatformError {
        code: PlatformErrorCode::PermissionDenied,
        message: "test-authority-denied".into(),
        retryable: false,
        details: Vec::new(),
    }
}
pub(super) fn context(operation: &str, generation: u64) -> ReleaseMutationContext {
    ReleaseMutationContext {
        scope: LifecycleScope::Tenant(TenantId("tests".into())),
        actor: ReleaseActor {
            subject: "asset-test-host".into(),
            kind: ReleaseActorKind::Host,
        },
        operation: Some(ReleaseOperationPrecondition {
            operation_id: operation.into(),
            expected_generation: generation,
        }),
    }
}
pub(super) fn publish(
    repo: &DirectoryArtifactRepository,
    operation: &str,
    page: &[u8],
) -> PublicationRef {
    repo.publish_web_package(context(operation, 0), upload(page), &mut |_| Ok(()))
        .unwrap()
        .receipt
        .publication
}
fn upload(page: &[u8]) -> PackageAdmissionUpload {
    let script = b"globalThis.assetTest = 1;\n";
    browser_upload(&[
        ("/app.js", "text/javascript", script),
        ("/index.html", "text/html", page),
    ])
}
pub(super) fn browser_upload(files: &[(&str, &str, &[u8])]) -> PackageAdmissionUpload {
    let mut assets: Vec<_> = files
        .iter()
        .map(|(path, media, bytes)| WebAsset {
            path: (*path).into(),
            layer: format!("public{path}"),
            digest: artifact_blob_digest(bytes).to_string(),
            size: bytes.len() as u64,
            media_type: (*media).into(),
        })
        .collect();
    assets.sort_by(|left, right| left.path.cmp(&right.path));
    let media = assets
        .iter()
        .map(|asset| (asset.layer.clone(), asset.media_type.clone()))
        .collect();
    let document = WebApplicationManifest {
        format_version: 1,
        profile: WEB_RELEASE_PROFILE.into(),
        assets_digest: asset_tree_digest(&assets).unwrap().to_string(),
        assets,
        routes: vec![WebRoute {
            path: "/".into(),
            mode: WebRenderMode::Client,
            asset: Some("/index.html".into()),
        }],
        renderer: None,
    };
    let mut layers = vec![
        (
            "metadata/private.json".into(),
            b"{\"private\":true}".to_vec(),
        ),
        (
            WEB_MANIFEST_PATH.into(),
            serde_json::to_vec(&document).unwrap(),
        ),
    ];
    layers.extend(
        files
            .iter()
            .map(|(path, _, bytes)| (format!("public{path}"), bytes.to_vec())),
    );
    encode_upload(layers, &media)
}
fn encode_upload(
    layers: Vec<(String, Vec<u8>)>,
    media: &BTreeMap<String, String>,
) -> PackageAdmissionUpload {
    let config = PackageConfig {
        format_version: 1,
        kind: PackageKind::BrowserAssets,
        name: "asset-owner-tests".into(),
        version: "1.0.0".into(),
        entrypoint: "public/index.html".into(),
        component_digest: None,
        layers: layers
            .iter()
            .map(|(path, bytes)| PackageLayer {
                path: path.clone(),
                role: LayerRole::Asset,
                media_type: media
                    .get(path)
                    .cloned()
                    .unwrap_or_else(|| "application/json".into()),
                digest: artifact_blob_digest(bytes),
                size: bytes.len() as u64,
            })
            .collect(),
        annotations: BTreeMap::new(),
    };
    let limits = PackageLimits::default();
    let configuration = encode_config(&config, limits).unwrap();
    let manifest = PackageManifest {
        schema_version: 2,
        media_type: OCI_MANIFEST_MEDIA_TYPE.into(),
        artifact_type: config.kind.artifact_type().into(),
        config: latent_artifacts::package::ArtifactDescriptor {
            media_type: PACKAGE_CONFIG_MEDIA_TYPE.into(),
            digest: artifact_blob_digest(&configuration),
            size: configuration.len() as u64,
            annotations: None,
        },
        layers: config
            .layers
            .iter()
            .map(|layer| latent_artifacts::package::ArtifactDescriptor {
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
    let evidence = || AdmissionEvidence {
        manifest: b"{}".to_vec(),
        configuration: b"{}".to_vec(),
        payload: b"mock evidence, not a signature".to_vec(),
    };
    PackageAdmissionUpload {
        manifest: encode_manifest(&manifest, limits).unwrap(),
        configuration,
        layers,
        signatures: vec![evidence()],
        provenance: vec![evidence()],
        sboms: Vec::new(),
    }
}
