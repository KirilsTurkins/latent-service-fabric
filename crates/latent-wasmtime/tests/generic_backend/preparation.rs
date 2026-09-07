use latent_core::PlatformErrorCode;
use latent_executor::ExecutionBackend;
use latent_wasmtime::WasmtimeComponentEngineFactory;
use serde_json::json;

use super::support::{
    artifact, budget, call, config, idle, request, returned, run, Cancellation, VALUES,
};

#[cfg(target_os = "linux")]
#[tokio::test(flavor = "current_thread")]
#[ignore = "requires the generic component and serial tests from tools/validate_contracts.sh"]
async fn dormant_preparation_keeps_helper_threads_fixed_and_creates_no_stores() {
    let mut bounded = config();
    bounded.prepared_cache_maximum_entries = 4;
    let factory = WasmtimeComponentEngineFactory::new(bounded).expect("factory");
    let backend = factory.create_backend_instance();
    let mut artifact = artifact();
    let key = factory.preparation_key(artifact.descriptor.release_digest.clone());
    backend
        .prepare(&artifact, &key)
        .await
        .expect("warm preparation");
    let baseline_threads = linux_task_count();
    assert_eq!(backend.resource_snapshot().stores_created, 0);
    idle(&backend);
    for index in 0..3 {
        artifact
            .manifest
            .metadata
            .annotations
            .insert("dormant-fixture".to_owned(), index.to_string());
        backend
            .prepare(&artifact, &key)
            .await
            .expect("bounded additional preparation");
        let observed_threads = linux_task_count();
        eprintln!("dormant prepared={} warm_threads={baseline_threads} observed_threads={observed_threads} stores_created=0", index + 2);
        assert!(observed_threads <= baseline_threads,
            "dormant preparation increased helper threads from {baseline_threads} to {observed_threads}");
        assert_eq!(backend.resource_snapshot().stores_created, 0);
        idle(&backend);
    }
    assert_eq!(backend.cache_snapshot().entries, 4);
}

#[cfg(target_os = "linux")]
fn linux_task_count() -> usize {
    std::fs::read_dir("/proc/self/task")
        .expect("Linux task directory")
        .try_fold(0, |count, entry| entry.map(|_| count + 1))
        .expect("Linux task entries")
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires the generic component built by tools/validate_contracts.sh"]
async fn factory_backends_share_preparation_but_metadata_changes_cannot_reuse_old_budgets() {
    let factory = WasmtimeComponentEngineFactory::new(config()).expect("factory");
    let first = factory.create_backend_instance();
    let second = factory.create_backend_instance();
    let mut artifact = artifact();
    let key = factory.preparation_key(artifact.descriptor.release_digest.clone());
    let initial = first
        .prepare(&artifact, &key)
        .await
        .expect("first preparation");
    assert_eq!(second.cache_snapshot().entries, 1);
    assert_eq!(
        returned(call(&second, &initial, "identify", b"[]").await),
        json!([11])
    );
    let reused = second
        .prepare(&artifact, &key)
        .await
        .expect("same prepared identity");
    assert_eq!(initial.opaque_handle, reused.opaque_handle);

    // The component digest is unchanged; metadata still changes compatibility.
    artifact.manifest.execution.resource_budget_ceiling.cpu_fuel = 500_000;
    let restricted = second
        .prepare(&artifact, &key)
        .await
        .expect("new bounded metadata");
    assert_ne!(initial.opaque_handle, restricted.opaque_handle);
    let cancellation = Cancellation::new("metadata-budget");
    let before = first.resource_snapshot().stores_created;
    let error = run(
        &first,
        request(
            restricted.clone(),
            &cancellation.id,
            VALUES,
            "identify",
            b"[]",
            budget(),
        ),
        &cancellation,
    )
    .await
    .expect_err("old large budget cannot cross metadata boundary");
    assert_eq!(error.code, PlatformErrorCode::ResourceExhausted);
    assert_eq!(first.resource_snapshot().stores_created, before);
    let mut grant = budget();
    grant.cpu_fuel = 500_000;
    let outcome = run(
        &first,
        request(
            restricted.clone(),
            &cancellation.id,
            VALUES,
            "identify",
            b"[]",
            grant,
        ),
        &cancellation,
    )
    .await
    .expect("restricted compatible budget");
    assert_eq!(returned(outcome), json!([11]));
    first.release(restricted).await.expect("shared release");
    assert_eq!(second.cache_snapshot().entries, 1);
    assert_eq!(
        returned(call(&second, &initial, "bump", b"[]").await),
        json!([1])
    );
    idle(&first);
    idle(&second);
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires the generic component built by tools/validate_contracts.sh"]
async fn eviction_and_release_remove_preparation_without_breaking_later_healthy_calls() {
    let mut limited = config();
    limited.prepared_cache_maximum_entries = 1;
    let factory = WasmtimeComponentEngineFactory::new(limited).expect("factory");
    let backend = factory.create_backend_instance();
    let mut artifact = artifact();
    let key = factory.preparation_key(artifact.descriptor.release_digest.clone());
    let old = backend
        .prepare(&artifact, &key)
        .await
        .expect("old metadata");
    artifact
        .manifest
        .metadata
        .annotations
        .insert("fixture".to_owned(), "new-metadata".to_owned());
    let retained = backend
        .prepare(&artifact, &key)
        .await
        .expect("new metadata");
    assert_eq!(backend.cache_snapshot().entries, 1);
    let cancellation = Cancellation::new("evicted");
    let error = run(
        &backend,
        request(old, &cancellation.id, VALUES, "identify", b"[]", budget()),
        &cancellation,
    )
    .await
    .expect_err("old metadata evicted");
    assert_eq!(error.code, PlatformErrorCode::NotFound);
    assert_eq!(backend.resource_snapshot().stores_created, 0);
    assert_eq!(
        returned(call(&backend, &retained, "identify", b"[]").await),
        json!([11])
    );
    backend.release(retained.clone()).await.expect("release");
    assert_eq!(backend.cache_snapshot().entries, 0);
    let error = run(
        &backend,
        request(
            retained,
            &cancellation.id,
            VALUES,
            "identify",
            b"[]",
            budget(),
        ),
        &cancellation,
    )
    .await
    .expect_err("released metadata unavailable");
    assert_eq!(error.code, PlatformErrorCode::NotFound);
    let replacement = backend
        .prepare(&artifact, &key)
        .await
        .expect("prepare after release");
    assert_eq!(
        returned(call(&backend, &replacement, "bump", b"[]").await),
        json!([1])
    );
    idle(&backend);
}
