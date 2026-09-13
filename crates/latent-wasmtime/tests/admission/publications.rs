use super::*;
use latent_artifacts::{
    LifecycleScope, ManagedPublicationUpload, PublicationRef, PublicationSelector, ReleaseActor,
    ReleaseActorKind, ReleaseLifecycleAction, ReleaseLifecycleReason, ReleaseMutationContext,
    ReleaseOperationPrecondition,
};
use latent_core::{RevisionId, RouteGeneration};
use latent_executor::{ExecutionCleanup, PreparationKey};
use latent_routing::ResolvedRevision;

fn context(operation: &str, generation: u64) -> ReleaseMutationContext {
    ReleaseMutationContext {
        scope: LifecycleScope::Tenant(TenantId("tests".into())),
        actor: ReleaseActor {
            subject: "publication-runtime-test".into(),
            kind: ReleaseActorKind::Host,
        },
        operation: Some(ReleaseOperationPrecondition {
            operation_id: operation.into(),
            expected_generation: generation,
        }),
    }
}
async fn publish(repository: &DirectoryArtifactRepository, variant: &str) -> PublicationRef {
    let mut artifact = support::artifact_bytes(component::bytes(), &[component::CONTRACT]);
    artifact.manifest.metadata.tenant = Some(TenantId("tests".into()));
    artifact
        .manifest
        .metadata
        .annotations
        .insert("inventory-revision".into(), variant.into());
    repository
        .publish_managed(
            context(variant, 0),
            ManagedPublicationUpload::Local(artifact),
            &mut |_| Ok(()),
        )
        .await
        .unwrap()
        .publication
}
fn key(factory: &WasmtimeComponentEngineFactory, publication: &PublicationRef) -> PreparationKey {
    let mut key = factory.preparation_key(latent_artifacts::content_digest(&component::bytes()));
    key.publication = Some(publication.id.clone());
    key
}

#[tokio::test(flavor = "current_thread")]
async fn independent_ready_and_warm_owners_check_publication_at_real_guest_start() {
    let directory = authority::Directory::new();
    let repository = Arc::new(
        DirectoryArtifactRepository::open(
            &directory.0,
            DirectoryArtifactRepositoryConfig::default(),
        )
        .unwrap(),
    );
    let first = publish(&repository, "original").await;
    let factory = WasmtimeComponentEngineFactory::with_catalog(
        support::config(),
        WasmtimeHostServices::default(),
        repository.lifecycle_authority(),
    )
    .unwrap();
    let backend = factory.create_backend_instance();
    let first_key = key(&factory, &first);
    let ready = backend
        .prepare_ready_from_repository(repository.clone(), first_key.clone())
        .await
        .unwrap();
    let active = backend
        .materialize_ready(
            backend
                .prepare_ready_from_repository(repository.clone(), first_key.clone())
                .await
                .unwrap(),
        )
        .unwrap();
    assert_eq!(ready.descriptor(), active.prepared.descriptor());
    assert_eq!(backend.cache_snapshot().entries, 1);
    let cancellation = support::Cancellation::new("stale-after-selection");
    // Constructing the future is deliberately separated from polling it.
    let pending = backend.invoke_prepared_contained(
        support::request(
            active.prepared.descriptor().clone(),
            &cancellation.id,
            component::CONTRACT,
            "answer",
            b"[]",
            support::budget(),
        ),
        active.prepared,
        &cancellation,
    );
    let second = publish(&repository, "corrected").await;
    let second_key = key(&factory, &second);
    let new_ready = backend
        .prepare_ready_from_repository(repository.clone(), second_key.clone())
        .await
        .unwrap();
    assert_ne!(
        ready.descriptor().opaque_handle,
        new_ready.descriptor().opaque_handle
    );
    assert_eq!(backend.cache_snapshot().entries, 2);
    let good_descriptor = new_ready.descriptor().clone();
    drop(new_ready);
    let mut wrong = support::request(
        good_descriptor.clone(),
        &cancellation.id,
        component::CONTRACT,
        "answer",
        b"[]",
        support::budget(),
    );
    wrong.activation.resolved_revision = Some(ResolvedRevision {
        target: wrong.activation.target.clone(),
        revision: RevisionId("held-route".into()),
        release: second_key.release.clone(),
        publication: Some(first.id.clone()),
        route_generation: RouteGeneration(1),
        attributes: Default::default(),
    });
    assert!(backend.invoke(wrong, &cancellation).await.is_err());
    assert_eq!(backend.resource_snapshot().stores_created, 0);

    repository
        .change_publication_lifecycle(
            context("revoke-original", 1),
            &PublicationSelector::Publication(first),
            ReleaseLifecycleAction::Revoke,
            ReleaseLifecycleReason::OperatorRevocation,
            &mut |_| Ok(()),
        )
        .unwrap();
    let failed = pending.await;
    assert!(failed.outcome.is_err());
    assert_eq!(failed.cleanup, ExecutionCleanup::Reusable);
    assert!(backend.materialize_ready(ready).is_err());
    assert!(backend
        .prepare_ready_from_repository(repository.clone(), first_key)
        .await
        .is_err());
    assert_eq!(backend.resource_snapshot().stores_created, 0);

    for id in ["fresh-one", "fresh-two"] {
        let selected = backend
            .prepare_ready_from_repository(repository.clone(), second_key.clone())
            .await
            .unwrap();
        assert_eq!(selected.descriptor(), &good_descriptor);
        let active = backend.materialize_ready(selected).unwrap();
        let cancellation = support::Cancellation::new(id);
        let result = backend
            .invoke_prepared_contained(
                support::request(
                    active.prepared.descriptor().clone(),
                    &cancellation.id,
                    component::CONTRACT,
                    "answer",
                    b"[]",
                    support::budget(),
                ),
                active.prepared,
                &cancellation,
            )
            .await;
        assert!(result.outcome.is_ok(), "{result:?}");
        assert_eq!(result.cleanup, ExecutionCleanup::Reusable);
    }
    // Reusing compiled state still creates a fresh store for every actual call.
    assert_eq!(backend.resource_snapshot().stores_created, 2);
    assert_eq!(backend.active_instance_reservations(), 0);
    assert_eq!(backend.compiler_snapshot().ready_preparations, 0);
    assert_eq!(backend.compiler_snapshot().reserved_document_bytes, 0);
    assert_eq!(backend.cache_snapshot().preparing, 0);
    factory.quiesce_compiler().await.unwrap();
}
