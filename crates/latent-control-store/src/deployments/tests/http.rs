//! Metadata and catalog authority tests; guest execution has its own HTTP suite.
use super::fixtures::*;
use crate::{http_routes::*, DeploymentStore};
use latent_artifacts::{
    ArtifactRepository, DirectoryArtifactRepository, DirectoryArtifactRepositoryConfig,
    LifecycleScope, ManagedPublicationUpload, PublicationRef, PublicationSelector, ReleaseActor,
    ReleaseActorKind, ReleaseLifecycleAction, ReleaseLifecycleReason, ReleaseMutationContext,
    ReleaseOperationPrecondition,
};
use latent_core::{ContractId, DeploymentId, FunctionId, InterfaceId, TenantId, TriggerId};
use latent_ingress::http::{CanonicalTarget, Method, Scheme};
use latent_manifest::{__serde_json as json, JsonManifestCodec, ManifestCodec, TriggerManifest};
use latent_routing::{RevisionPolicySource, RouteResolver};
use std::sync::{atomic::Ordering, Arc};

mod recovery;
mod selection;
mod writers;
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
    assert_eq!(held.revision().publication.as_ref(), Some(&publication.id));
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
    held.catalog().admission_policy(held.revision()).unwrap();
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
