use std::sync::atomic::{AtomicUsize, Ordering};

use latent_artifacts::ArtifactRepository;
use latent_core::{ContractId, PlatformErrorCode};
use latent_executor::{ExecutionBackend, ExecutionReport, PreparedUse};
use latent_manifest::ContractImport;
use latent_wasmtime::{WasmtimeBackend, WasmtimeComponentEngineFactory};
use serde_json::json;

use super::super::support::{
    artifact, budget, config, request, returned, Cancellation, VALUES, WATCHDOG,
};
use super::support::{no_reservations, Directory, Repository};

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires the generic component built by tools/validate_contracts.sh"]
async fn warm_lookup_does_no_reads_and_owned_runtime_survives_release_and_disk_corruption() {
    let directory = Directory::new();
    let repository = directory.open();
    let release = repository.publish(artifact()).await.unwrap().release_digest;
    let mut bounded = config();
    bounded.maximum_active_instances = 1;
    let factory = WasmtimeComponentEngineFactory::new(bounded).unwrap();
    let backend = factory.create_backend_instance();
    let key = factory.preparation_key(release.clone());
    drop(
        backend
            .prepare_from_repository(&repository, &key)
            .await
            .unwrap(),
    );
    let verified = repository.verification_snapshot();
    let prepared = backend.preparation_activity_snapshot();
    assert_eq!(verified.full_fetch_attempts, 1);
    assert_eq!(prepared.repository_fetches, 1);
    assert_eq!(prepared.component_hashes, 0);
    assert_eq!(prepared.metadata_fingerprints, 1);
    directory.corrupt_component(&release);

    let owned = backend
        .prepare_from_repository(&repository, &key)
        .await
        .unwrap();
    let warm = backend.preparation_activity_snapshot();
    assert_eq!(warm.authenticated_hits, prepared.authenticated_hits + 1);
    assert_eq!(warm.repository_fetches, prepared.repository_fetches);
    assert_eq!(warm.component_hashes, prepared.component_hashes);
    assert_eq!(warm.metadata_fingerprints, prepared.metadata_fingerprints);
    assert_eq!(repository.verification_snapshot(), verified);
    assert_eq!(backend.active_instance_reservations(), 1);
    assert_eq!(
        backend
            .prepare_from_repository(&repository, &key)
            .await
            .unwrap_err()
            .code,
        PlatformErrorCode::Unavailable
    );
    assert_eq!(repository.verification_snapshot(), verified);

    let descriptor = owned.prepared.descriptor().clone();
    backend.release(descriptor.clone()).await.unwrap();
    assert_eq!(backend.cache_snapshot().entries, 0);
    let report = identify(&backend, owned.prepared, "authenticated-evicted-owner").await;
    assert_eq!(returned(report.outcome.unwrap()), json!([11]));
    no_reservations(&backend);

    assert_eq!(
        backend
            .prepare_from_repository(&repository, &key)
            .await
            .unwrap_err()
            .code,
        PlatformErrorCode::CorruptArtifact
    );
    assert_eq!(repository.verification_snapshot().full_fetch_attempts, 2);
    assert_eq!(backend.cache_snapshot().entries, 0);
    no_reservations(&backend);
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires the generic component built by tools/validate_contracts.sh"]
async fn delegated_reads_epochs_imports_and_evicted_factory_ownership_remain_distinct() {
    let directory = Directory::new();
    let repository = directory.open();
    let other_directory = Directory::new();
    let other_repository = other_directory.open();
    let value = artifact();
    let release = repository
        .publish(value.clone())
        .await
        .unwrap()
        .release_digest;
    let mut changed = value.clone();
    changed.manifest.execution.resource_budget_ceiling.cpu_fuel = 500_000;
    changed.manifest.imports = ["latent:log/log@0.1.0", "latent:context/context@0.1.0"]
        .map(|name| ContractImport {
            contract: ContractId(name.to_owned()),
            optional: true,
        })
        .to_vec();
    other_repository.publish(changed.clone()).await.unwrap();
    let delegated = Repository {
        source: Some(&repository),
        fallback: Some(changed),
        fetches: AtomicUsize::new(0),
    };
    let mut bounded = config();
    bounded.prepared_cache_maximum_entries = 1;
    let factory = WasmtimeComponentEngineFactory::new(bounded.clone()).unwrap();
    let backend = factory.create_backend_instance();
    let key = factory.preparation_key(release);
    let initial = backend
        .prepare_from_repository(&delegated, &key)
        .await
        .unwrap();
    assert!(initial.imports.is_empty());
    let descriptor = initial.prepared.descriptor().clone();
    drop(initial);
    let owned = backend
        .prepare_from_repository(&delegated, &key)
        .await
        .unwrap();
    assert_eq!(delegated.fetches.load(Ordering::Relaxed), 0);
    assert_eq!(repository.verification_snapshot().full_fetch_attempts, 1);

    let different = backend
        .prepare_from_repository(&other_repository, &key)
        .await
        .unwrap();
    assert_eq!(
        different
            .imports
            .iter()
            .map(|id| id.0.as_str())
            .collect::<Vec<_>>(),
        ["latent:log/log@0.1.0", "latent:context/context@0.1.0"]
    );
    assert_ne!(
        different.prepared.descriptor().opaque_handle,
        descriptor.opaque_handle
    );
    assert_eq!(backend.cache_snapshot().entries, 1);
    assert_eq!(backend.cache_snapshot().evictions, 1);
    backend.release(descriptor.clone()).await.unwrap();
    assert_eq!(backend.cache_snapshot().entries, 1);

    let report = identify(&backend, owned.prepared, "repository-a-owner").await;
    assert_eq!(returned(report.outcome.unwrap()), json!([11]));
    let foreign_factory = WasmtimeComponentEngineFactory::new(bounded).unwrap();
    let foreign = foreign_factory.create_backend_instance();
    let rejected = identify(&foreign, different.prepared, "foreign-factory").await;
    assert_eq!(
        rejected.outcome.unwrap_err().code,
        PlatformErrorCode::InvalidArgument
    );
    assert_eq!(foreign.stores_created(), 0);
    no_reservations(&backend);
    no_reservations(&foreign);
}

async fn identify(backend: &WasmtimeBackend, prepared: PreparedUse, id: &str) -> ExecutionReport {
    let cancellation = Cancellation::new(id);
    tokio::time::timeout(
        WATCHDOG,
        backend.invoke_prepared_contained(
            request(
                prepared.descriptor().clone(),
                &cancellation.id,
                VALUES,
                "identify",
                b"[]",
                budget(),
            ),
            prepared,
            &cancellation,
        ),
    )
    .await
    .unwrap()
}
