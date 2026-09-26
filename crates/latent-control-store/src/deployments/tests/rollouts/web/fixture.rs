use super::*;
use latent_artifacts::package::{
    artifact_blob_digest, inspect_package, LayerRole, PackageKind, PackageLimits,
};
use latent_artifacts::{
    web::{
        asset_tree_digest, inspect_web_layout, VerifiedWebAdmission, WebAdmissionBinding,
        WebAdmissionGrant, WebApplicationManifest, WebAsset, WebBackendProfile, WebRenderer,
        WebRendererProfile, WebRoute, WEB_MANIFEST_PATH, WEB_RELEASE_PROFILE,
    },
    AdmissionAuthority, AdmissionBinding, AdmissionRecheck, AdmissionStorageLimits,
    PackageAdmissionUpload, ReleaseMutationContext, ReleaseOperationPrecondition,
    VerifiedAdmission,
};
use latent_core::PlatformError;
use latent_manifest::{renderer_profile_digest, RendererRequirement, RuntimeCompatibilityProfile};
use latent_packaging::{build_package, LayerInput, PackageInput, PackagingLimits};
use std::{any::Any, borrow::Cow, result::Result};

pub(super) struct Host;
struct Grant(WebAdmissionBinding);

fn denied() -> PlatformError {
    crate::rollouts::error(Code::PermissionDenied, "web-rollout-test-authority")
}

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
        if !grant.as_any().is::<Self>() {
            return Err(denied());
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
            receipt: b"injected test authority, not signed evidence".to_vec(),
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
        let verified = self.verify_web(&binding.tenant, upload)?;
        if verified.grant.binding() != binding {
            return Err(denied());
        }
        Ok(verified)
    }
}

pub(super) fn mutation(operation: &str, generation: u64) -> ReleaseMutationContext {
    ReleaseMutationContext {
        scope: LifecycleScope::Tenant(alice()),
        actor: context(operation, 0).actor,
        operation: Some(ReleaseOperationPrecondition {
            operation_id: operation.into(),
            expected_generation: generation,
        }),
    }
}

pub(super) fn open_artifacts(root: &TempRoot) -> Arc<DirectoryArtifactRepository> {
    Arc::new(
        DirectoryArtifactRepository::open_enforced(
            &root.0,
            DirectoryArtifactRepositoryConfig::default(),
            AdmissionStorageLimits::default(),
            Arc::new(Host),
        )
        .unwrap(),
    )
}

pub(super) fn open_store(root: &TempRoot, artifacts: &Arc<DirectoryArtifactRepository>) -> Store {
    let profile = RuntimeCompatibilityProfile::new(
        "wasmtime",
        "47.0.4",
        "x86_64-unknown-linux-gnu",
        &["x86_64.sse2"],
        256 * 1024 * 1024,
        2_000_000_000,
    )
    .unwrap()
    .with_renderer(RendererRequirement {
        profile: WebRendererProfile::AngularSsrComponentV1,
        profile_digest: renderer_profile_digest(WebRendererProfile::AngularSsrComponentV1)
            .to_string(),
    })
    .unwrap();
    run(Store::open_with_catalog(
        &root.0,
        artifacts.clone(),
        Limits::default(),
        artifacts.lifecycle_authority(),
        Arc::new(profile),
    ))
    .unwrap()
}

pub(super) fn publish(
    artifacts: &DirectoryArtifactRepository,
    variant: &str,
    mutate: impl FnOnce(&mut WebApplicationManifest),
) -> PublicationRef {
    let mut component = wasm_encoder::Component::new();
    component.section(&wasm_encoder::CustomSection {
        name: Cow::Borrowed("variant"),
        data: Cow::Borrowed(variant.as_bytes()),
    });
    let renderer = component.finish();
    let html = format!("<h1>{variant}</h1>").into_bytes();
    let assets = vec![WebAsset {
        path: "/index.html".into(),
        layer: "public/index.html".into(),
        digest: artifact_blob_digest(&html).to_string(),
        size: html.len() as u64,
        media_type: "text/html".into(),
    }];
    let assets_digest = asset_tree_digest(&assets).unwrap().to_string();
    let mut manifest = WebApplicationManifest {
        format_version: 1,
        profile: WEB_RELEASE_PROFILE.into(),
        assets_digest: assets_digest.clone(),
        assets,
        routes: vec![WebRoute {
            path: "/".into(),
            mode: WebRenderMode::Server,
            asset: None,
        }],
        static_routing: None,
        renderer: Some(WebRenderer {
            layer: "server/renderer.wasm".into(),
            digest: artifact_blob_digest(&renderer).to_string(),
            size: renderer.len() as u64,
            profile: WebRendererProfile::AngularSsrComponentV1,
            profile_digest: renderer_profile_digest(WebRendererProfile::AngularSsrComponentV1)
                .to_string(),
            assets_digest,
            backend_profile: WebBackendProfile::None,
        }),
    };
    mutate(&mut manifest);
    let bundle = build_package(
        PackageInput {
            kind: PackageKind::SsrPackage,
            name: "web-rollout".into(),
            version: "1.0.0".into(),
            entrypoint: "server/renderer.wasm".into(),
            annotations: Default::default(),
            layers: vec![
                LayerInput {
                    path: "public/index.html".into(),
                    role: LayerRole::Asset,
                    media_type: "text/html".into(),
                    bytes: html,
                },
                LayerInput {
                    path: "server/renderer.wasm".into(),
                    role: LayerRole::Renderer,
                    media_type: "application/wasm".into(),
                    bytes: renderer,
                },
                LayerInput {
                    path: WEB_MANIFEST_PATH.into(),
                    role: LayerRole::Asset,
                    media_type: "application/json".into(),
                    bytes: json::to_vec(&manifest).unwrap(),
                },
            ],
        },
        PackagingLimits::default(),
    )
    .unwrap();
    let input = bundle.into_input();
    artifacts
        .publish_web_package(
            mutation(variant, 0),
            PackageAdmissionUpload {
                manifest: input.manifest,
                configuration: input.configuration,
                layers: input.layers,
                signatures: vec![latent_artifacts::AdmissionEvidence {
                    manifest: b"{}".to_vec(),
                    configuration: b"{}".to_vec(),
                    payload: b"injected unit-test publisher".to_vec(),
                }],
                provenance: vec![latent_artifacts::AdmissionEvidence {
                    manifest: b"{}".to_vec(),
                    configuration: b"{}".to_vec(),
                    payload: b"injected unit-test builder".to_vec(),
                }],
                sboms: vec![],
            },
            &mut |_| Ok(()),
        )
        .unwrap()
        .receipt
        .publication
}

pub(super) fn selected(
    artifacts: &DirectoryArtifactRepository,
    publication: &PublicationRef,
    name: &str,
) -> latent_manifest::DeploymentManifest {
    let selection = artifacts.select_web_publication(publication).unwrap();
    let layout = selection.eligibility().layout();
    let release =
        latent_core::ReleaseDigest(layout.manifest().renderer.as_ref().unwrap().digest.clone());
    let mut manifest = deployment(name, "alice", &release);
    manifest.publication = Some(publication.id.clone());
    manifest.service.0 = layout.name().into();
    manifest.route_weight = 10000;
    manifest.resources =
        run(artifacts.fetch_verified_metadata_selected(&release, Some(&publication.id)))
            .unwrap()
            .manifest()
            .execution
            .resource_budget_ceiling
            .clone();
    manifest
}
