//! Tiny real-component lifecycle checks for both managed catalog modes.

#[path = "../../latent-control-store/tests/admission/support.rs"]
mod authority;
#[path = "admission/component.rs"]
mod component;
#[path = "generic_backend/support.rs"]
#[allow(dead_code)]
mod support;

use std::sync::Arc;

use latent_artifacts::{
    AdmissionStorageLimits, ArtifactRepository, DirectoryArtifactRepository,
    DirectoryArtifactRepositoryConfig, LifecycleScope, ReleaseActor, ReleaseActorKind,
    ReleaseLifecycleAction, ReleaseLifecycleReason, ReleaseMutationContext,
    ReleaseOperationPrecondition,
};
use latent_core::{PlatformErrorCode, TenantId};
use latent_executor::ExecutionBackend;
use latent_wasmtime::{WasmtimeBackend, WasmtimeComponentEngineFactory, WasmtimeHostServices};

struct Fixture {
    backend: WasmtimeBackend,
    factory: WasmtimeComponentEngineFactory,
    repository: Arc<DirectoryArtifactRepository>,
    _directory: authority::Directory,
}
impl Fixture {
    async fn new(enforced: bool) -> Self {
        let artifact = support::artifact_bytes(component::bytes(), &[component::CONTRACT]);
        let directory = authority::Directory::new();
        let repository = Arc::new(if enforced {
            let trusted = authority::Authority::new(artifact.clone());
            DirectoryArtifactRepository::open_enforced(
                &directory.0,
                DirectoryArtifactRepositoryConfig::default(),
                AdmissionStorageLimits::default(),
                trusted,
            )
            .unwrap()
        } else {
            DirectoryArtifactRepository::open(
                &directory.0,
                DirectoryArtifactRepositoryConfig::default(),
            )
            .unwrap()
        });
        if enforced {
            repository
                .admit_package(
                    &TenantId("tests".into()),
                    authority::upload(&artifact),
                    &mut |_| Ok(()),
                )
                .await
                .unwrap();
        } else {
            repository.publish(artifact).await.unwrap();
        }
        let factory = WasmtimeComponentEngineFactory::with_catalog(
            support::config(),
            WasmtimeHostServices::default(),
            repository.lifecycle_authority(),
        )
        .unwrap();
        let backend = factory.create_backend_instance();
        Self {
            backend,
            factory,
            repository,
            _directory: directory,
        }
    }
    fn key(&self) -> latent_executor::PreparationKey {
        self.factory
            .preparation_key(latent_artifacts::content_digest(&component::bytes()))
    }
    async fn ready(&self) -> latent_executor::PreparedReadiness {
        self.backend
            .prepare_ready_from_repository(self.repository.clone(), self.key())
            .await
            .unwrap()
    }
    async fn revoke(&self) {
        self.repository
            .change_release_lifecycle(
                ReleaseMutationContext {
                    scope: LifecycleScope::Tenant(TenantId("tests".into())),
                    actor: ReleaseActor {
                        subject: "runtime-lifecycle-test".into(),
                        kind: ReleaseActorKind::Host,
                    },
                    operation: Some(ReleaseOperationPrecondition {
                        operation_id: "revoke-test".into(),
                        expected_generation: 1,
                    }),
                },
                &self.key().release,
                ReleaseLifecycleAction::Revoke,
                ReleaseLifecycleReason::OperatorRevocation,
                &mut |_| Ok(()),
            )
            .await
            .unwrap();
    }
    fn idle(&self) {
        assert_eq!(self.backend.active_instance_reservations(), 0);
        assert_eq!(self.backend.resource_snapshot().stores_created, 0);
        assert_eq!(self.backend.compiler_snapshot().ready_preparations, 0);
    }
}

#[tokio::test(flavor = "current_thread")]
async fn both_catalog_modes_reject_raw_input_and_foreign_catalog_tokens() {
    for enforced in [false, true] {
        let fixture = Fixture::new(enforced).await;
        let artifact = support::artifact_bytes(component::bytes(), &[component::CONTRACT]);
        assert_eq!(
            fixture
                .backend
                .prepare(&artifact, &fixture.key())
                .await
                .unwrap_err()
                .code,
            PlatformErrorCode::PermissionDenied
        );
        assert_eq!(
            fixture
                .backend
                .prepare_for_use(&artifact, &fixture.key())
                .await
                .unwrap_err()
                .code,
            PlatformErrorCode::PermissionDenied
        );
        let foreign = Fixture::new(enforced).await;
        assert!(fixture
            .backend
            .prepare_ready_from_repository(foreign.repository.clone(), fixture.key())
            .await
            .is_err());
        assert!(fixture
            .backend
            .prepare_from_repository(foreign.repository.as_ref(), &fixture.key())
            .await
            .is_err());
        assert_eq!(fixture.backend.cache_snapshot().entries, 0);
        fixture.idle();
    }
}

#[tokio::test(flavor = "current_thread")]
async fn lifecycle_revocation_blocks_ready_materialization_warm_hits_and_borrowed_prepare() {
    for enforced in [false, true] {
        let fixture = Fixture::new(enforced).await;
        let first = fixture.ready().await;
        let second = fixture.ready().await;
        assert_eq!(first.descriptor(), second.descriptor());
        drop(first);
        fixture.revoke().await;
        assert!(fixture.backend.materialize_ready(second).is_err());
        assert!(fixture
            .backend
            .prepare_ready_from_repository(fixture.repository.clone(), fixture.key())
            .await
            .is_err());
        assert!(fixture
            .backend
            .prepare_from_repository(fixture.repository.as_ref(), &fixture.key())
            .await
            .is_err());
        fixture.idle();
    }
}

#[tokio::test(flavor = "current_thread")]
async fn catalog_factories_keep_cache_disabled_preparation_restricted_to_profiling() {
    for enforced in [false, true] {
        let fixture = Fixture::new(enforced).await;
        let config = latent_wasmtime::WasmtimeConfig {
            prepared_cache_enabled: false,
            ..support::config()
        };
        let failure = WasmtimeComponentEngineFactory::with_catalog(
            config,
            WasmtimeHostServices::default(),
            fixture.repository.lifecycle_authority(),
        )
        .err()
        .unwrap();
        assert_eq!(failure.code, PlatformErrorCode::InvalidArgument);
        assert_eq!(
            failure.message,
            "cache-disabled preparation is restricted to the Phase 0 profiling facade"
        );
        fixture.idle();
    }
}

#[tokio::test(flavor = "current_thread")]
async fn lifecycle_is_checked_when_prepared_invoke_is_first_polled_and_for_descriptor_only_calls() {
    for enforced in [false, true] {
        let fixture = Fixture::new(enforced).await;
        let active = fixture
            .backend
            .materialize_ready(fixture.ready().await)
            .unwrap();
        let descriptor = active.prepared.descriptor().clone();
        let cancellation = support::Cancellation::new("lifecycle-before-first-poll");
        let request = support::request(
            descriptor.clone(),
            &cancellation.id,
            component::CONTRACT,
            "answer",
            b"[]",
            support::budget(),
        );
        let invocation =
            fixture
                .backend
                .invoke_prepared_contained(request, active.prepared, &cancellation);
        fixture.revoke().await;
        assert!(invocation.await.outcome.is_err());
        assert!(fixture
            .backend
            .invoke(
                support::request(
                    descriptor,
                    &cancellation.id,
                    component::CONTRACT,
                    "answer",
                    b"[]",
                    support::budget()
                ),
                &cancellation
            )
            .await
            .is_err());
        fixture.idle();
    }
}

#[tokio::test(flavor = "current_thread")]
async fn local_catalog_drop_retires_retained_ready_and_cache_capabilities() {
    let Fixture {
        backend,
        factory,
        repository,
        _directory: directory,
    } = Fixture::new(false).await;
    let key = factory.preparation_key(latent_artifacts::content_digest(&component::bytes()));
    let ready = backend
        .prepare_ready_from_repository(repository.clone(), key)
        .await
        .unwrap();
    drop(repository);
    assert!(backend.materialize_ready(ready).is_err());
    assert_eq!(backend.active_instance_reservations(), 0);
    assert_eq!(backend.resource_snapshot().stores_created, 0);
    drop(backend);
    factory.shutdown().unwrap();
    drop(directory);
}
