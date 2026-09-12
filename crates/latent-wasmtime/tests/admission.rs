//! Real tiny-component tests of runtime currentness, separate from policy crypto.

#[path = "../../latent-control-store/tests/admission/support.rs"]
mod authority;
#[path = "admission/component.rs"]
mod component;
#[path = "generic_backend/support.rs"]
#[allow(dead_code)]
mod support;

use std::sync::atomic::Ordering;
use std::sync::Arc;

use latent_artifacts::{
    AdmissionAuthority, AdmissionStorageLimits, ArtifactRepository, DirectoryArtifactRepository,
    DirectoryArtifactRepositoryConfig,
};
use latent_core::{PlatformErrorCode, TenantId};
use latent_executor::ExecutionBackend;
use latent_wasmtime::{WasmtimeBackend, WasmtimeComponentEngineFactory, WasmtimeHostServices};

struct Fixture {
    backend: WasmtimeBackend,
    factory: WasmtimeComponentEngineFactory,
    repository: Arc<DirectoryArtifactRepository>,
    authority: Arc<authority::Authority>,
    _directory: authority::Directory,
}

impl Fixture {
    async fn new() -> Self {
        let artifact = support::artifact_bytes(component::bytes(), &[component::CONTRACT]);
        let authority = authority::Authority::new(artifact.clone());
        let directory = authority::Directory::new();
        let trusted: Arc<dyn AdmissionAuthority> = authority.clone();
        let repository = Arc::new(
            DirectoryArtifactRepository::open_enforced(
                &directory.0,
                DirectoryArtifactRepositoryConfig::default(),
                AdmissionStorageLimits::default(),
                trusted.clone(),
            )
            .unwrap(),
        );
        repository
            .admit_package(
                &TenantId("tests".to_owned()),
                authority::upload(&artifact),
                &mut |_| Ok(()),
            )
            .await
            .unwrap();
        let factory = WasmtimeComponentEngineFactory::with_enforced_admission(
            support::config(),
            WasmtimeHostServices::default(),
            trusted,
        )
        .unwrap();
        let backend = factory.create_backend_instance();
        Self {
            backend,
            factory,
            repository,
            authority,
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
    fn assert_idle(&self) {
        assert_eq!(self.backend.active_instance_reservations(), 0);
        assert_eq!(self.backend.resource_snapshot().stores_created, 0);
        assert_eq!(self.backend.compiler_snapshot().ready_preparations, 0);
        assert_eq!(self.backend.cache_snapshot().preparing, 0);
    }
}

#[tokio::test(flavor = "current_thread")]
async fn enforced_raw_preparation_rejects_before_compilation_but_explicit_local_still_works() {
    let fixture = Fixture::new().await;
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
    assert_eq!(fixture.backend.cache_snapshot().entries, 0);
    fixture.assert_idle();
    let local = WasmtimeComponentEngineFactory::new(support::config()).unwrap();
    local
        .create_backend_instance()
        .prepare(
            &artifact,
            &local.preparation_key(artifact.descriptor.release_digest.clone()),
        )
        .await
        .unwrap();
}

#[tokio::test(flavor = "current_thread")]
async fn warm_readiness_is_reused_but_revocation_blocks_materialization_and_new_hits() {
    let fixture = Fixture::new().await;
    let first = fixture.ready().await;
    let second = fixture.ready().await;
    assert_eq!(first.descriptor(), second.descriptor());
    assert_eq!(fixture.backend.cache_snapshot().entries, 1);
    drop(first);
    fixture
        .authority
        .state
        .active
        .store(false, Ordering::SeqCst);
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
    fixture.assert_idle();
}

#[tokio::test(flavor = "current_thread")]
async fn materialized_use_checks_expiry_when_invoke_future_is_polled() {
    let fixture = Fixture::new().await;
    let active = fixture
        .backend
        .materialize_ready(fixture.ready().await)
        .unwrap();
    let cancellation = support::Cancellation::new("expires-before-first-poll");
    let invoke = fixture.backend.invoke_prepared_contained(
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
    fixture.authority.state.now.store(200, Ordering::SeqCst);
    assert!(invoke.await.outcome.is_err());
    fixture.assert_idle();
}

#[tokio::test(flavor = "current_thread")]
async fn descriptor_only_invocation_and_wrong_tenant_cannot_bypass_currentness() {
    let fixture = Fixture::new().await;
    let active = fixture
        .backend
        .materialize_ready(fixture.ready().await)
        .unwrap();
    let descriptor = active.prepared.descriptor().clone();
    drop(active);
    let cancellation = support::Cancellation::new("descriptor-tenant");
    let mut request = support::request(
        descriptor.clone(),
        &cancellation.id,
        component::CONTRACT,
        "answer",
        b"[]",
        support::budget(),
    );
    request.activation.target.tenant = TenantId("another".to_owned());
    assert!(fixture
        .backend
        .invoke(request, &cancellation)
        .await
        .is_err());
    fixture
        .authority
        .state
        .active
        .store(false, Ordering::SeqCst);
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
    fixture.assert_idle();
}

#[tokio::test(flavor = "current_thread")]
async fn contended_authority_fails_without_waiting_for_the_control_writer() {
    let fixture = Fixture::new().await;
    let ready = fixture.ready().await;
    let guard = fixture.authority.state.fence.lock().unwrap();
    std::thread::scope(|scope| {
        let (sender, receiver) = std::sync::mpsc::sync_channel(1);
        let backend = &fixture.backend;
        let worker = scope.spawn(move || {
            sender
                .send(backend.materialize_ready(ready).is_err())
                .unwrap();
        });
        let observed = receiver.recv_timeout(std::time::Duration::from_secs(1));
        // Always release before joining/asserting, including a regressed blocking
        // implementation: this test reports failure instead of leaving a worker.
        drop(guard);
        worker.join().unwrap();
        assert!(observed.unwrap());
    });
    fixture.assert_idle();
}

#[tokio::test(flavor = "current_thread")]
async fn another_configured_authority_is_rejected_before_any_prepare() {
    let fixture = Fixture::new().await;
    let unrelated = authority::Authority::new(support::artifact_bytes(
        component::bytes(),
        &[component::CONTRACT],
    ));
    let factory = WasmtimeComponentEngineFactory::with_enforced_admission(
        support::config(),
        WasmtimeHostServices::default(),
        unrelated,
    )
    .unwrap();
    let backend = factory.create_backend_instance();
    assert!(backend
        .prepare_ready_from_repository(fixture.repository.clone(), fixture.key())
        .await
        .is_err());
    assert_eq!(backend.cache_snapshot().entries, 0);
    assert_eq!(backend.resource_snapshot().stores_created, 0);
}

#[tokio::test(flavor = "current_thread")]
async fn retiring_catalog_owner_invalidates_retained_ready_and_cached_descriptors() {
    let fixture = Fixture::new().await;
    let ready = fixture.ready().await;
    let Fixture {
        backend,
        factory,
        repository,
        authority: _,
        _directory: directory,
    } = fixture;
    drop(repository);
    assert!(backend.materialize_ready(ready).is_err());
    assert_eq!(backend.active_instance_reservations(), 0);
    assert_eq!(backend.resource_snapshot().stores_created, 0);
    drop(backend);
    factory.shutdown().unwrap();
    drop(directory);
}

#[tokio::test(flavor = "current_thread")]
async fn accepted_start_may_finish_but_its_descriptor_cannot_start_again_after_revocation() {
    let fixture = Fixture::new().await;
    let active = fixture
        .backend
        .materialize_ready(fixture.ready().await)
        .unwrap();
    let descriptor = active.prepared.descriptor().clone();
    let cancellation = support::Cancellation::new("accepted-before-revocation");
    fixture
        .authority
        .state
        .revoke_after_fence
        .store(true, Ordering::SeqCst);
    let result = fixture
        .backend
        .invoke_prepared_contained(
            support::request(
                descriptor.clone(),
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
    assert_eq!(
        support::returned(result.outcome.unwrap()),
        serde_json::json!([7])
    );
    assert_eq!(fixture.backend.resource_snapshot().stores_created, 1);
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
    assert_eq!(fixture.backend.resource_snapshot().stores_created, 1);
    assert_eq!(fixture.backend.active_instance_reservations(), 0);
}
