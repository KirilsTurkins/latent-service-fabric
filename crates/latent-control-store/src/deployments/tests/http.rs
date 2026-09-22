//! Metadata and catalog authority tests; guest execution has its own HTTP suite.
use super::fixtures::*;
use crate::{http_routes::*, DeploymentStore};
use latent_artifacts::package::{
    artifact_blob_digest, encode_config as encode_package_config,
    encode_manifest as encode_package_manifest, inspect_package, ArtifactDescriptor, LayerRole,
    PackageConfig, PackageKind, PackageLayer, PackageLimits, PackageManifest,
    LAYER_PATH_ANNOTATION, LAYER_ROLE_ANNOTATION, OCI_MANIFEST_MEDIA_TYPE,
    PACKAGE_CONFIG_MEDIA_TYPE,
};
use latent_artifacts::web::{
    asset_tree_digest, inspect_web_layout, StaticDirectoryIndexMode, StaticFallbackMode,
    StaticWebFallback, StaticWebRouting, StaticWebRoutingProfile, VerifiedWebAdmission,
    WebAdmissionBinding, WebAdmissionGrant, WebApplicationManifest, WebAsset, WebRenderMode,
    WebRoute, WEB_MANIFEST_PATH, WEB_RELEASE_PROFILE,
};
use latent_artifacts::{
    AdmissionAuthority, AdmissionBinding, AdmissionEvidence, AdmissionRecheck,
    AdmissionStorageLimits, ArtifactRepository, DirectoryArtifactRepository,
    DirectoryArtifactRepositoryConfig, LifecycleScope, ManagedPublicationUpload,
    PackageAdmissionUpload, PublicationRef, PublicationSelector, ReleaseActor, ReleaseActorKind,
    ReleaseLifecycleAction, ReleaseLifecycleReason, ReleaseMutationContext,
    ReleaseOperationPrecondition, VerifiedAdmission,
};
use latent_core::{
    ContractId, DeploymentId, FunctionId, InterfaceId, PlatformError, PlatformErrorCode, TenantId,
    TriggerId,
};
use latent_ingress::http::{CanonicalTarget, Method, Scheme};
use latent_manifest::{__serde_json as json, JsonManifestCodec, ManifestCodec, TriggerManifest};
use latent_routing::{RevisionPolicySource, RouteResolver};
use std::any::Any;
use std::collections::BTreeMap;
use std::sync::{atomic::Ordering, Arc};

mod recovery;
mod selection;
mod writers;

struct StaticWebHost;
struct StaticWebGrant(WebAdmissionBinding);

impl WebAdmissionGrant for StaticWebGrant {
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
impl AdmissionRecheck for StaticWebGrant {
    fn check(&self) -> Result<(), PlatformError> {
        Ok(())
    }
    fn check_web_grant(&self, grant: &dyn WebAdmissionGrant) -> Result<(), PlatformError> {
        if !grant.as_any().is::<StaticWebGrant>() {
            return Err(static_web_denied("static-web-test-grant"));
        }
        grant.check_current()
    }
}
impl AdmissionAuthority for StaticWebHost {
    fn verify(
        &self,
        _: &TenantId,
        _: PackageAdmissionUpload,
    ) -> Result<VerifiedAdmission, PlatformError> {
        Err(static_web_denied("static-web-test-capsule"))
    }
    fn recover(
        &self,
        _: &AdmissionBinding,
        _: PackageAdmissionUpload,
    ) -> Result<VerifiedAdmission, PlatformError> {
        Err(static_web_denied("static-web-test-capsule"))
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
            .ok_or_else(|| static_web_denied("static-web-test-manifest"))?
            .1;
        let layout = inspect_web_layout(&package, metadata)?;
        let binding = WebAdmissionBinding {
            tenant: tenant.clone(),
            package: layout.package().clone(),
            manifest: layout.manifest_digest().clone(),
            assets: layout.assets_digest().clone(),
            receipt: b"static web test admission".to_vec(),
        };
        Ok(VerifiedWebAdmission {
            layout,
            upload,
            grant: Arc::new(StaticWebGrant(binding)),
        })
    }
    fn recover_web(
        &self,
        binding: &WebAdmissionBinding,
        upload: PackageAdmissionUpload,
    ) -> Result<VerifiedWebAdmission, PlatformError> {
        let value = self.verify_web(&binding.tenant, upload)?;
        if value.grant.binding() != binding {
            return Err(static_web_denied("static-web-test-recovery"));
        }
        Ok(value)
    }
}

fn static_web_denied(message: &'static str) -> PlatformError {
    PlatformError {
        code: PlatformErrorCode::PermissionDenied,
        message: message.into(),
        retryable: false,
        details: Vec::new(),
    }
}

fn static_web_upload() -> PackageAdmissionUpload {
    let html = b"<h1>Static</h1>".to_vec();
    let assets = vec![WebAsset {
        path: "/index.html".into(),
        layer: "public/index.html".into(),
        digest: artifact_blob_digest(&html).to_string(),
        size: html.len() as u64,
        media_type: "text/html".into(),
    }];
    let assets_digest = asset_tree_digest(&assets).unwrap().to_string();
    let document = WebApplicationManifest {
        format_version: 1,
        profile: WEB_RELEASE_PROFILE.into(),
        assets_digest: assets_digest.clone(),
        assets,
        routes: vec![WebRoute {
            path: "/".into(),
            mode: WebRenderMode::Client,
            asset: Some("/index.html".into()),
        }],
        static_routing: Some(StaticWebRouting {
            profile: StaticWebRoutingProfile::StaticSiteV1,
            entry_document: "/index.html".into(),
            directory_index: StaticDirectoryIndexMode::Redirect,
            directory_index_document: "/index.html".into(),
            fallback: StaticWebFallback {
                mode: StaticFallbackMode::Spa,
                document: Some("/index.html".into()),
            },
        }),
        renderer: None,
    };
    let metadata = json::to_vec(&document).unwrap();
    let mut layers = vec![
        PackageLayer {
            path: "public/index.html".into(),
            role: LayerRole::Asset,
            media_type: "text/html".into(),
            digest: artifact_blob_digest(&html),
            size: html.len() as u64,
        },
        PackageLayer {
            path: WEB_MANIFEST_PATH.into(),
            role: LayerRole::Asset,
            media_type: "application/json".into(),
            digest: artifact_blob_digest(&metadata),
            size: metadata.len() as u64,
        },
    ];
    layers.sort_by(|a, b| a.path.cmp(&b.path));
    let config = PackageConfig {
        format_version: 1,
        kind: PackageKind::BrowserAssets,
        name: "static-web-test".into(),
        version: "1.0.0".into(),
        entrypoint: "public/index.html".into(),
        component_digest: None,
        layers,
        annotations: BTreeMap::new(),
    };
    let limits = PackageLimits::default();
    let configuration = encode_package_config(&config, limits).unwrap();
    let package = PackageManifest {
        schema_version: 2,
        media_type: OCI_MANIFEST_MEDIA_TYPE.into(),
        artifact_type: config.kind.artifact_type().into(),
        config: ArtifactDescriptor {
            media_type: PACKAGE_CONFIG_MEDIA_TYPE.into(),
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
                    (LAYER_PATH_ANNOTATION.into(), layer.path.clone()),
                    (LAYER_ROLE_ANNOTATION.into(), layer.role.as_str().into()),
                ])),
            })
            .collect(),
        annotations: BTreeMap::new(),
    };
    let manifest = encode_package_manifest(&package, limits).unwrap();
    let evidence = || AdmissionEvidence {
        manifest: b"{}".to_vec(),
        configuration: b"{}".to_vec(),
        payload: b"static web test evidence".to_vec(),
    };
    PackageAdmissionUpload {
        manifest,
        configuration,
        layers: vec![
            ("public/index.html".into(), html),
            (WEB_MANIFEST_PATH.into(), metadata),
        ],
        signatures: vec![evidence()],
        provenance: vec![evidence()],
        sboms: Vec::new(),
    }
}

fn static_repo(root: &TempRoot) -> Arc<DirectoryArtifactRepository> {
    Arc::new(
        DirectoryArtifactRepository::open_enforced(
            &root.0,
            DirectoryArtifactRepositoryConfig::default(),
            AdmissionStorageLimits::default(),
            Arc::new(StaticWebHost),
        )
        .unwrap(),
    )
}

fn publish_static(repo: &DirectoryArtifactRepository, tenant: &str) -> PublicationRef {
    repo.publish_web_package(
        publication_context(tenant, "publish-static", 0),
        static_web_upload(),
        &mut |_| Ok(()),
    )
    .unwrap()
    .receipt
    .publication
}

fn static_definition(
    tenant: &str,
    id: &str,
    publication: &PublicationRef,
    path: &str,
    kind: &str,
) -> TriggerManifest {
    let value = json::json!({
        "apiVersion":"latent.dev/v1alpha1",
        "kind":"HttpTrigger",
        "metadata":{"name":id,"tenant":tenant},
        "spec":{
            "target":{"kind":"static-web","publication":publication.id.as_str()},
            "configuration":{
                "profile":"static-site-v1","scheme":"https",
                "host":format!("{tenant}.example.test"),"path":path,
                "pathMatch":kind,"method":"GET"
            }
        }
    });
    JsonManifestCodec::default()
        .decode_trigger(&json::to_vec(&value).unwrap())
        .unwrap()
}

fn actor() -> ReleaseActor {
    ReleaseActor {
        subject: "http-control-test".into(),
        kind: ReleaseActorKind::Host,
    }
}
fn publication_context(tenant: &str, operation: &str, generation: u64) -> ReleaseMutationContext {
    ReleaseMutationContext {
        scope: LifecycleScope::Tenant(TenantId(tenant.into())),
        actor: actor(),
        operation: Some(ReleaseOperationPrecondition {
            operation_id: operation.into(),
            expected_generation: generation,
        }),
    }
}
fn publish(repo: &DirectoryArtifactRepository, tenant: &str, variant: &str) -> PublicationRef {
    let mut value = artifact("http-shared-executable");
    value.manifest.metadata.tenant = Some(TenantId(tenant.into()));
    value
        .manifest
        .metadata
        .annotations
        .insert("inventory-revision".into(), variant.into());
    let contract = ContractId(latent_ingress::http::CONTRACT.into());
    value.manifest.world = ContractId(format!("{tenant}:browser/service@0.1.0"));
    value.manifest.exports[0].contract = contract.clone();
    value.contracts[0].id = contract.clone();
    value.contracts[0].package_name = "latent:web".into();
    value.contracts[0].semantic_version = "0.1.0".into();
    value.contracts[0].interfaces[0].id = InterfaceId(contract.0);
    value.contracts[0].interfaces[0].functions[0].id = FunctionId("handle".into());
    value.contracts[0].interfaces[0].functions[0].name = "handle".into();
    value.contracts[0].interfaces[0].functions[0].asynchronous = true;
    run(repo.publish_managed(
        publication_context(tenant, variant, 0),
        ManagedPublicationUpload::Local(value),
        &mut |_| Ok(()),
    ))
    .unwrap()
    .publication
}
fn repo(root: &TempRoot) -> Arc<DirectoryArtifactRepository> {
    Arc::new(
        DirectoryArtifactRepository::open(&root.0, DirectoryArtifactRepositoryConfig::default())
            .unwrap(),
    )
}
fn catalog(root: &TempRoot, repo: &Arc<DirectoryArtifactRepository>) -> Store {
    run(Store::open_with_catalog(
        &root.0,
        repo.clone(),
        Limits::default(),
        repo.lifecycle_authority(),
        super::lifecycle::profile("47.0.4"),
    ))
    .unwrap()
}
fn deploy(store: &Store, reference: &PublicationRef, id: &str) {
    let mut value = deployment(
        id,
        &reference.scope.tenant().unwrap().0,
        &artifact("http-shared-executable").descriptor.release_digest,
    );
    value.publication = Some(reference.id.clone());
    run(store.apply(value)).unwrap();
}
fn definition(
    store: &Store,
    tenant: &str,
    id: &str,
    deployment: &str,
    path: &str,
    kind: &str,
) -> TriggerManifest {
    let mut target = super::fixtures::target(tenant, Some(deployment));
    target.contract = ContractId(latent_ingress::http::CONTRACT.into());
    target.function = FunctionId("handle".into());
    let selected = store.resolve(&target, None).unwrap();
    let generation = store.read_publication().routes.versions[&DeploymentId(deployment.into())];
    let value = json::json!({"apiVersion":"latent.dev/v1alpha1", "kind":"HttpTrigger", "metadata":{"name":id, "tenant":tenant},
        "spec":{"target":{"service":"echo", "contract":target.contract.0, "function":"handle", "route":deployment,
            "publication":selected.publication.unwrap().as_str(), "revision":selected.revision.0, "deploymentGeneration":generation},
            "configuration":{"profile":"buffered-v1", "scheme":"https", "host":format!("{tenant}.example.test"), "path":path, "pathMatch":kind, "method":"GET"}}});
    JsonManifestCodec::default()
        .decode_trigger(&json::to_vec(&value).unwrap())
        .unwrap()
}
fn request(
    store: &Store,
    operation: &str,
    manifest: TriggerManifest,
    generation: u64,
) -> TriggerOperationRequest {
    TriggerOperationRequest::Apply {
        context: TriggerOperationContext {
            tenant: manifest.metadata.tenant.clone().unwrap(),
            actor: actor(),
            operation_id: operation.into(),
            expected_state_version: store.read_publication().transaction,
        },
        manifest,
        expected_generation: generation,
    }
}
fn execute(store: &Store, request: TriggerOperationRequest) -> TriggerRead<TriggerOperationCommit> {
    let prepared = store.prepare_trigger_operation(request).unwrap();
    let expected = prepared.preview().clone();
    let result = store.commit_trigger_operation(prepared).unwrap();
    assert_eq!(result.value().receipt, expected);
    result.value().durability.as_ref().unwrap();
    result
}
fn delete(
    store: &Store,
    operation: &str,
    tenant: &str,
    id: &str,
    generation: u64,
) -> TriggerRead<TriggerOperationCommit> {
    execute(
        store,
        TriggerOperationRequest::Delete {
            context: TriggerOperationContext {
                tenant: TenantId(tenant.into()),
                actor: actor(),
                operation_id: operation.into(),
                expected_state_version: store.read_publication().transaction,
            },
            id: TriggerId(id.into()),
            expected_generation: generation,
        },
    )
}
fn selected(
    store: &Store,
    tenant: &str,
    path: &str,
) -> Result<AcceptedHttpRoute, latent_core::PlatformError> {
    store.select_http(
        &CanonicalTarget::parse(Scheme::Https, &format!("{tenant}.example.test"), path).unwrap(),
        Method::Get,
    )
}
fn get(store: &Store, tenant: &str, id: &str) -> TriggerRead<TriggerSnapshot> {
    store
        .get_trigger(&TenantId(tenant.into()), &TriggerId(id.into()))
        .unwrap()
}
fn setup() -> (
    [TempRoot; 2],
    Arc<DirectoryArtifactRepository>,
    Store,
    PublicationRef,
) {
    let roots = [TempRoot::new(), TempRoot::new()];
    let repo = repo(&roots[0]);
    let publication = publish(&repo, "alice", "first");
    let store = catalog(&roots[1], &repo);
    deploy(&store, &publication, "web");
    (roots, repo, store, publication)
}

#[test]
fn http_atomic_routes_exact_replay_delete_recreate_and_restart() {
    let (roots, repo, store, publication) = setup();
    let definition = definition(&store, "alice", "browser", "web", "/", "prefix");
    let command = request(&store, "create", definition.clone(), 0);
    let receipt = execute(&store, command.clone()).value().receipt.clone();
    let held = selected(&store, "alice", "/anything").unwrap();
    assert_eq!(
        held.revision().unwrap().publication.as_ref(),
        Some(&publication.id)
    );
    assert_eq!(held.state_version(), receipt.state_version);
    let original = std::fs::read(roots[1].0.join("catalog.json")).unwrap();
    assert!(execute(&store, command.clone()).value().replayed);
    assert_eq!(
        original,
        std::fs::read(roots[1].0.join("catalog.json")).unwrap()
    );
    assert_eq!(
        json::from_slice::<json::Value>(&original).unwrap()["format_version"],
        7
    );
    delete(
        &store,
        "delete",
        "alice",
        "browser",
        receipt.object_generation,
    );
    assert!(selected(&store, "alice", "/anything").is_err());
    held.catalog()
        .unwrap()
        .admission_policy(held.revision().unwrap())
        .unwrap();
    assert!(execute(&store, command.clone()).value().replayed);
    assert!(get(&store, "alice", "browser").value().trigger.is_none());
    let next = execute(&store, request(&store, "recreate", definition, 0))
        .value()
        .receipt
        .clone();
    assert!(next.object_generation > receipt.object_generation);
    assert!(get(&store, "bob", "browser").value().trigger.is_none());
    drop(held);
    drop(store);
    let store = catalog(&roots[1], &repo);
    assert_eq!(
        selected(&store, "alice", "/anything")
            .unwrap()
            .trigger_generation(),
        next.object_generation
    );
    assert_eq!(
        store
            .get_trigger_operation(&TenantId("alice".into()), "create")
            .unwrap()
            .value(),
        &TriggerOperationLookup::Found(receipt)
    );
    assert!(execute(&store, command).value().replayed);
}
