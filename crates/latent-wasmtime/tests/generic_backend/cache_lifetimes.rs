use latent_executor::{ExecutionBackend, ExecutionCleanup, GuestOutcome};
use latent_wasmtime::{PreparedRuntimeSnapshot, WasmtimeComponentEngineFactory};
use serde_json::json;

use super::support::{
    artifact, artifact_bytes, budget, config, idle, request, returned, Cancellation, ALTERNATE,
    VALUES, WATCHDOG,
};

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires the generic component built by tools/validate_contracts.sh"]
async fn five_real_components_in_four_slots_keep_evicted_owner_executable_and_charged() {
    let mut configuration = config();
    configuration.prepared_cache_maximum_entries = 4;
    let factory = WasmtimeComponentEngineFactory::new(configuration).unwrap();
    let backend = factory.create_backend_instance();
    let observer = backend.prepared_runtime_observer();
    let base = artifact();
    let key = backend
        .preparation_key(&base.descriptor.release_digest)
        .unwrap();
    let held = tokio::time::timeout(WATCHDOG, backend.prepare_for_use(&base, &key))
        .await
        .unwrap()
        .unwrap();
    let first = observer.snapshot().unwrap();
    assert_eq!(first.live.runtimes, 1);
    let mut descriptors = Vec::new();
    for ordinal in 1..5_u8 {
        let mut component = base.component_bytes.clone();
        // Legal, distinct custom sections preserve the actual exports.
        component.extend_from_slice(&[0, 3, 1, b'x', ordinal]);
        let variant = artifact_bytes(component, &[VALUES, ALTERNATE]);
        let key = backend
            .preparation_key(&variant.descriptor.release_digest)
            .unwrap();
        descriptors.push(
            tokio::time::timeout(WATCHDOG, backend.prepare(&variant, &key))
                .await
                .unwrap()
                .unwrap(),
        );
    }
    let churn = backend.cache_accounting_snapshot();
    let live = churn.runtimes.unwrap();
    assert_eq!(churn.resident.entries, 4);
    assert_eq!(churn.resident.evictions, 1);
    assert_eq!(live.live.runtimes, 5);
    assert_eq!(live.resident.runtimes, 4);
    assert_eq!(live.evicted_live, first.live);
    assert_eq!(live.unpublished.runtimes, 0);
    assert_eq!(
        live.resident.compiled_image_bytes,
        churn.resident.compiled_image_bytes as u64
    );
    let cancellation = Cancellation::new("held-after-five-component-churn");
    let invocation = request(
        held.descriptor().clone(),
        &cancellation.id,
        VALUES,
        "identify",
        b"[]",
        budget(),
    );
    let result = tokio::time::timeout(
        WATCHDOG,
        backend.invoke_prepared_contained(invocation, held, &cancellation),
    )
    .await
    .unwrap();
    assert_eq!(result.cleanup, ExecutionCleanup::Reusable);
    assert_eq!(returned(result.outcome.unwrap()), json!([11]));
    let completed = observer.snapshot().unwrap();
    assert_eq!(completed.live, live.resident);
    assert_eq!(completed.evicted_live.runtimes, 0);
    idle(&backend);
    for descriptor in descriptors {
        backend.release(descriptor).await.unwrap();
    }
    assert_eq!(
        observer.snapshot(),
        Some(PreparedRuntimeSnapshot::default())
    );
    tokio::time::timeout(WATCHDOG, factory.quiesce_compiler())
        .await
        .unwrap()
        .unwrap();
    drop(backend);
    factory.shutdown().unwrap();
    assert_eq!(
        observer.snapshot(),
        Some(PreparedRuntimeSnapshot::default())
    );
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires the generic component built by tools/validate_contracts.sh"]
async fn evicted_last_runtime_remains_owned_until_native_trap_is_classified() {
    let factory = WasmtimeComponentEngineFactory::new(config()).unwrap();
    let backend = factory.create_backend_instance();
    let observer = backend.prepared_runtime_observer();
    let artifact = artifact();
    let key = backend
        .preparation_key(&artifact.descriptor.release_digest)
        .unwrap();
    let held = backend.prepare_for_use(&artifact, &key).await.unwrap();
    let descriptor = held.descriptor().clone();
    backend.release(descriptor.clone()).await.unwrap();
    assert_eq!(observer.snapshot().unwrap().evicted_live.runtimes, 1);
    let cancellation = Cancellation::new("evicted-last-runtime-trap");
    let report = tokio::time::timeout(
        WATCHDOG,
        backend.invoke_prepared_contained(
            request(
                descriptor,
                &cancellation.id,
                VALUES,
                "trap",
                b"[]",
                budget(),
            ),
            held,
            &cancellation,
        ),
    )
    .await
    .unwrap();
    assert_eq!(report.cleanup, ExecutionCleanup::Reusable);
    let GuestOutcome::Trapped { trap, .. } = report.outcome.unwrap() else {
        panic!("real export must trap");
    };
    assert_eq!(trap.code, "guest-trap");
    assert!(trap.guest_backtrace.is_empty());
    idle(&backend);
    assert_eq!(backend.active_instance_reservations(), 0);
    assert_eq!(
        observer.snapshot(),
        Some(PreparedRuntimeSnapshot::default())
    );
    tokio::time::timeout(WATCHDOG, factory.quiesce_compiler())
        .await
        .unwrap()
        .unwrap();
    drop(backend);
    factory.shutdown().unwrap();
    assert_eq!(
        observer.snapshot(),
        Some(PreparedRuntimeSnapshot::default())
    );
}
