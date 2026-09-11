use std::sync::Arc;

use latent_artifacts::{
    ArtifactRepository, DirectoryArtifactRepository, DirectoryArtifactRepositoryConfig,
};
use latent_core::PlatformErrorCode;
use latent_executor::{ExecutionBackend, ExecutionCleanup};
use latent_wasmtime::{PreparedRuntimeSnapshot, WasmtimeComponentEngineFactory};
use serde_json::json;

use super::support::{
    artifact, budget, config, idle, request, returned, Cancellation, VALUES, WATCHDOG,
};

struct Directory(std::path::PathBuf);

impl Directory {
    fn new() -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let path = std::env::temp_dir().join(format!(
            "latent-cold-ready-{}-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        std::fs::create_dir(&path).unwrap();
        Self(path)
    }

    fn open(&self) -> Arc<DirectoryArtifactRepository> {
        Arc::new(
            DirectoryArtifactRepository::open(
                &self.0,
                DirectoryArtifactRepositoryConfig::default(),
            )
            .unwrap(),
        )
    }
}

impl Drop for Directory {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires the generic component built by tools/validate_contracts.sh"]
async fn readiness_is_independent_of_instance_gate_and_pins_evicted_runtime_through_execution() {
    let directory = Directory::new();
    let repository = directory.open();
    let artifact = artifact();
    let digest = artifact.descriptor.release_digest.clone();
    repository.publish(artifact).await.unwrap();
    let mut configuration = config();
    configuration.maximum_active_instances = 1;
    configuration.maximum_ready_preparations = 2;
    configuration.prepared_cache_maximum_entries = 1;
    let factory = WasmtimeComponentEngineFactory::new(configuration).unwrap();
    let backend = factory.create_backend_instance();
    let accounting = backend.prepared_runtime_observer();
    let key = backend.preparation_key(&digest).unwrap();
    let first = tokio::time::timeout(
        WATCHDOG,
        backend.prepare_ready_from_repository(repository.clone(), key.clone()),
    )
    .await
    .unwrap()
    .unwrap();
    assert_eq!(backend.active_instance_reservations(), 0);
    assert_eq!(backend.resource_snapshot().live_stores, 0);
    let verification = repository.verification_snapshot();
    let second = backend
        .prepare_ready_from_repository(repository.clone(), key.clone())
        .await
        .unwrap();
    let unique = accounting.snapshot().unwrap();
    assert_eq!(unique.live.runtimes, 1);
    assert_eq!(unique.live, unique.resident);
    assert_eq!(unique.unpublished.runtimes, 0);
    assert_eq!(
        repository.verification_snapshot(),
        verification,
        "warm readiness must not fetch/hash/traverse metadata"
    );
    let active = backend.materialize_ready(first).unwrap();
    assert_eq!(backend.active_instance_reservations(), 1);
    let error = backend.materialize_ready(second).unwrap_err();
    assert_eq!(error.code, PlatformErrorCode::Unavailable);
    assert_eq!(backend.compiler_snapshot().ready_preparations, 0);
    assert_eq!(accounting.snapshot(), Some(unique));
    let independent = backend
        .prepare_ready_from_repository(repository.clone(), key)
        .await
        .unwrap();
    assert_eq!(backend.compiler_snapshot().ready_preparations, 1);
    drop(independent);
    assert_eq!(accounting.snapshot(), Some(unique));
    let descriptor = active.prepared.descriptor().clone();
    backend.release(descriptor.clone()).await.unwrap();
    assert_eq!(backend.cache_snapshot().entries, 0);
    let evicted = accounting.snapshot().unwrap();
    assert_eq!(evicted.live, unique.live);
    assert_eq!(evicted.evicted_live, unique.live);
    assert_eq!(evicted.resident.runtimes, 0);
    let cancellation = Cancellation::new("ready-evicted-invoke");
    let report = tokio::time::timeout(
        WATCHDOG,
        backend.invoke_prepared_contained(
            request(
                descriptor,
                &cancellation.id,
                VALUES,
                "identify",
                b"[]",
                budget(),
            ),
            active.prepared,
            &cancellation,
        ),
    )
    .await
    .unwrap();
    assert_eq!(report.cleanup, ExecutionCleanup::Reusable);
    assert_eq!(returned(report.outcome.unwrap()), json!([11]));
    idle(&backend);
    assert_eq!(backend.active_instance_reservations(), 0);
    assert_eq!(accounting.snapshot().unwrap().live.runtimes, 0);
    tokio::time::timeout(WATCHDOG, factory.quiesce_compiler())
        .await
        .unwrap()
        .unwrap();
    let compiler = factory.compiler_observer();
    drop(backend);
    factory.shutdown().unwrap();
    assert_eq!(
        accounting.snapshot(),
        Some(PreparedRuntimeSnapshot::default())
    );
    let joined = compiler.snapshot();
    assert_eq!(joined.workers_joined, joined.maximum_workers as u64);
    assert_eq!(
        (joined.ready_preparations, joined.reserved_document_bytes),
        (0, 0)
    );
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires the generic component built by tools/validate_contracts.sh"]
async fn foreign_factory_materialization_drops_ready_bytes_without_taking_an_instance() {
    let directory = Directory::new();
    let repository = directory.open();
    let artifact = artifact();
    let digest = artifact.descriptor.release_digest.clone();
    repository.publish(artifact).await.unwrap();
    let factory = WasmtimeComponentEngineFactory::new(config()).unwrap();
    let foreign_factory = WasmtimeComponentEngineFactory::new(config()).unwrap();
    let backend = factory.create_backend_instance();
    let foreign = foreign_factory.create_backend_instance();
    let key = backend.preparation_key(&digest).unwrap();
    let ready = tokio::time::timeout(
        WATCHDOG,
        backend.prepare_ready_from_repository(repository, key),
    )
    .await
    .unwrap()
    .unwrap();
    assert_eq!(backend.compiler_snapshot().ready_preparations, 1);
    let error = foreign.materialize_ready(ready).unwrap_err();
    assert_eq!(error.code, PlatformErrorCode::InvalidArgument);
    assert_eq!(backend.compiler_snapshot().ready_preparations, 0);
    assert_eq!(backend.compiler_snapshot().ready_compiled_image_bytes, 0);
    assert_eq!(foreign.active_instance_reservations(), 0);
}
