//! The injected host verifier owns test grants; policy crypto has its own tests.
use super::*;
use latent_artifacts::{
    LifecycleScope, ManagedPublicationUpload, PublicationRef, PublicationSelector, ReleaseActor,
    ReleaseActorKind, ReleaseLifecycleAction, ReleaseLifecycleReason, ReleaseMutationContext,
    ReleaseOperationPrecondition,
};

fn context(tenant: &str, operation: &str, generation: u64) -> ReleaseMutationContext {
    ReleaseMutationContext {
        scope: LifecycleScope::Tenant(TenantId(tenant.into())),
        actor: ReleaseActor {
            subject: "package-runtime-test".into(),
            kind: ReleaseActorKind::Host,
        },
        operation: Some(ReleaseOperationPrecondition {
            operation_id: operation.into(),
            expected_generation: generation,
        }),
    }
}

async fn admit(
    repository: &DirectoryArtifactRepository,
    tenant: &str,
    operation: &str,
    artifact: &latent_artifacts::CapsuleArtifact,
) -> PublicationRef {
    repository
        .publish_managed(
            context(tenant, operation, 0),
            ManagedPublicationUpload::Package(authority::upload(artifact)),
            &mut |_| Ok(()),
        )
        .await
        .unwrap()
        .publication
}

async fn prepare(
    backend: &WasmtimeBackend,
    factory: &WasmtimeComponentEngineFactory,
    repository: &Arc<DirectoryArtifactRepository>,
    publication: &PublicationRef,
) -> latent_executor::PreparedReadiness {
    let mut key = factory.preparation_key(latent_artifacts::content_digest(&component::bytes()));
    key.publication = Some(publication.id.clone());
    backend
        .prepare_ready_from_repository(repository.clone(), key)
        .await
        .unwrap()
}

#[tokio::test(flavor = "current_thread")]
async fn same_wasm_packages_and_tenants_keep_independent_enforced_runtime_grants() {
    let mut original = support::artifact_bytes(component::bytes(), &[component::CONTRACT]);
    original.manifest.metadata.tenant = None;
    let mut corrected = original.clone();
    corrected
        .manifest
        .metadata
        .annotations
        .insert("inventory-revision".into(), "corrected".into());
    let authority = authority::Authority::new_many(vec![original.clone(), corrected.clone()]);
    let directory = authority::Directory::new();
    let repository = Arc::new(
        DirectoryArtifactRepository::open_enforced(
            &directory.0,
            DirectoryArtifactRepositoryConfig::default(),
            AdmissionStorageLimits::default(),
            authority.clone(),
        )
        .unwrap(),
    );
    let first = admit(&repository, "tests", "original", &original).await;
    let second = admit(&repository, "tests", "corrected", &corrected).await;
    let other_tenant = admit(&repository, "bob", "original", &original).await;
    assert_ne!(first.id, second.id);
    assert_ne!(first.id, other_tenant.id);
    let first_grant = repository
        .execution_eligibility_selected(&original.descriptor.release_digest, Some(&first.id))
        .unwrap()
        .unwrap();
    let second_grant = repository
        .execution_eligibility_selected(&original.descriptor.release_digest, Some(&second.id))
        .unwrap()
        .unwrap();
    let other_grant = repository
        .execution_eligibility_selected(&original.descriptor.release_digest, Some(&other_tenant.id))
        .unwrap()
        .unwrap();
    assert_ne!(first_grant.package(), second_grant.package());
    assert_eq!(first_grant.package(), other_grant.package());
    let factory = WasmtimeComponentEngineFactory::with_enforced_admission(
        support::config(),
        WasmtimeHostServices::default(),
        authority,
    )
    .unwrap();
    let backend = factory.create_backend_instance();
    let stale = prepare(&backend, &factory, &repository, &first).await;
    let retained = prepare(&backend, &factory, &repository, &second).await;
    assert_ne!(
        stale.descriptor().opaque_handle,
        retained.descriptor().opaque_handle
    );
    repository
        .change_publication_lifecycle(
            context("tests", "retire-original", 1),
            &PublicationSelector::Publication(first),
            ReleaseLifecycleAction::Retire,
            ReleaseLifecycleReason::OperatorRetirement,
            &mut |_| Ok(()),
        )
        .unwrap();
    assert!(first_grant.check_current().is_err());
    second_grant.check_current().unwrap();
    other_grant.check_current().unwrap();
    assert!(backend.materialize_ready(stale).is_err());
    let active = backend.materialize_ready(retained).unwrap();
    let cancellation = support::Cancellation::new("foreign-publication");
    let mut wrong_tenant = support::request(
        active.prepared.descriptor().clone(),
        &cancellation.id,
        component::CONTRACT,
        "answer",
        b"[]",
        support::budget(),
    );
    wrong_tenant.activation.target.tenant = TenantId("bob".into());
    let rejected = backend
        .invoke_prepared_contained(wrong_tenant, active.prepared, &cancellation)
        .await;
    assert!(rejected.outcome.is_err());
    assert_eq!(backend.resource_snapshot().stores_created, 0);
    for (tenant, publication) in [("tests", &second), ("bob", &other_tenant)] {
        let active = backend
            .materialize_ready(prepare(&backend, &factory, &repository, publication).await)
            .unwrap();
        let cancellation = support::Cancellation::new(tenant);
        let mut request = support::request(
            active.prepared.descriptor().clone(),
            &cancellation.id,
            component::CONTRACT,
            "answer",
            b"[]",
            support::budget(),
        );
        request.activation.target.tenant = TenantId(tenant.into());
        let result = backend
            .invoke_prepared_contained(request, active.prepared, &cancellation)
            .await;
        assert_eq!(
            support::returned(result.outcome.unwrap()),
            serde_json::json!([7])
        );
        assert_eq!(result.cleanup, latent_executor::ExecutionCleanup::Reusable);
    }
    assert_eq!(backend.resource_snapshot().stores_created, 2);
    assert_eq!(backend.active_instance_reservations(), 0);
    assert_eq!(backend.compiler_snapshot().ready_preparations, 0);
    assert_eq!(backend.compiler_snapshot().reserved_document_bytes, 0);
    factory.quiesce_compiler().await.unwrap();
}
