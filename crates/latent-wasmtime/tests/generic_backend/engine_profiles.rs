//! The same real component under every supported allocation/compiler policy.

#[path = "engine_profiles/containment.rs"]
mod containment;

use latent_core::PlatformErrorCode;
use latent_executor::{ExecutionBackend, ExecutionCleanup};
use latent_wasmtime::{
    CompilerOptimization, InstanceAllocator, WasmtimeBackend, WasmtimeComponentEngineFactory,
    WasmtimeConfig,
};
use serde_json::json;

use super::support::{
    artifact, budget, call, config, idle, request, returned, Cancellation, VALUES, WATCHDOG,
};

pub(super) fn profiles() -> impl Iterator<Item = WasmtimeConfig> {
    [InstanceAllocator::OnDemand, InstanceAllocator::Pooling]
        .into_iter()
        .flat_map(|allocator| {
            [
                CompilerOptimization::Speed,
                CompilerOptimization::SpeedAndSize,
            ]
            .into_iter()
            .map(move |optimization| WasmtimeConfig {
                instance_allocator: allocator,
                compiler_optimization: optimization,
                pooling_maximum_instances: 4,
                maximum_active_instances: 4,
                fuel_async_yield_interval: Some(1_000),
                ..config()
            })
        })
}

pub(super) async fn finish(factory: WasmtimeComponentEngineFactory, backend: WasmtimeBackend) {
    idle(&backend);
    assert_eq!(backend.active_instance_reservations(), 0);
    let runtimes = factory.prepared_runtime_observer();
    let compiler = factory.compiler_observer();
    drop(backend);
    tokio::time::timeout(WATCHDOG, factory.quiesce_compiler())
        .await
        .unwrap()
        .unwrap();
    factory.shutdown().unwrap();
    assert_eq!(runtimes.snapshot().unwrap(), Default::default());
    let joined = compiler.snapshot();
    assert!(!joined.accepting && !joined.failed);
    assert_eq!(joined.workers_live, 0);
    assert_eq!(joined.workers_joined, joined.maximum_workers as u64);
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires the generic component built by tools/validate_contracts.sh"]
async fn every_profile_bounds_affine_owners_and_refunds_capacity_before_recovery() {
    let artifact = artifact();
    for policy in profiles() {
        let factory = WasmtimeComponentEngineFactory::new(policy).unwrap();
        let backend = factory.create_backend_instance();
        let key = factory.preparation_key(artifact.descriptor.release_digest.clone());
        let mut owners = Vec::new();
        for _ in 0..4 {
            owners.push(backend.prepare_for_use(&artifact, &key).await.unwrap());
        }
        assert_eq!(backend.active_instance_reservations(), 4);
        let error = backend.prepare_for_use(&artifact, &key).await.unwrap_err();
        assert_eq!(error.code, PlatformErrorCode::Unavailable);
        assert!(error.retryable);
        assert_eq!(
            backend.stores_created(),
            0,
            "this is the affine gate, not a native pool allocation"
        );
        drop(owners.pop());
        let owner = backend.prepare_for_use(&artifact, &key).await.unwrap();
        let cancellation = Cancellation::new("profile-capacity-recovery");
        let report = backend
            .invoke_prepared_contained(
                request(
                    owner.descriptor().clone(),
                    &cancellation.id,
                    VALUES,
                    "bump",
                    b"[]",
                    budget(),
                ),
                owner,
                &cancellation,
            )
            .await;
        assert_eq!(report.cleanup, ExecutionCleanup::Reusable);
        assert_eq!(returned(report.outcome.unwrap()), json!([1]));
        assert_eq!(backend.active_instance_reservations(), 3);
        drop(owners);
        finish(factory, backend).await;
    }
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires the generic component built by tools/validate_contracts.sh"]
async fn foreign_profile_prepared_ownership_is_rejected_before_native_instantiation() {
    let artifact = artifact();
    let source_factory = WasmtimeComponentEngineFactory::new(profiles().next().unwrap()).unwrap();
    let source = source_factory.create_backend_instance();
    let source_key = source_factory.preparation_key(artifact.descriptor.release_digest.clone());
    for policy in profiles().skip(1) {
        let factory = WasmtimeComponentEngineFactory::new(policy).unwrap();
        let backend = factory.create_backend_instance();
        let key = factory.preparation_key(artifact.descriptor.release_digest.clone());
        assert_ne!(
            source_key.engine_configuration_digest,
            key.engine_configuration_digest
        );
        assert_eq!(
            backend
                .prepare(&artifact, &source_key)
                .await
                .unwrap_err()
                .code,
            PlatformErrorCode::IncompatibleContract
        );
        let owner = source
            .prepare_for_use(&artifact, &source_key)
            .await
            .unwrap();
        let cancellation = Cancellation::new("foreign-profile");
        let report = backend
            .invoke_prepared_contained(
                request(
                    owner.descriptor().clone(),
                    &cancellation.id,
                    VALUES,
                    "identify",
                    b"[]",
                    budget(),
                ),
                owner,
                &cancellation,
            )
            .await;
        assert_eq!(report.cleanup, ExecutionCleanup::Reusable);
        assert_eq!(
            report.outcome.unwrap_err().code,
            PlatformErrorCode::InvalidArgument
        );
        assert_eq!(source.active_instance_reservations(), 0);
        assert_eq!(backend.stores_created(), 0);
        assert_eq!(backend.cache_snapshot().misses, 0);
        finish(factory, backend).await;
    }
    finish(source_factory, source).await;
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires the generic component built by tools/validate_contracts.sh"]
async fn insufficient_native_memory_pool_rejects_without_leaking_prepared_or_active_owners() {
    let artifact = artifact();
    let factory = WasmtimeComponentEngineFactory::new(WasmtimeConfig {
        instance_allocator: InstanceAllocator::Pooling,
        pooling_maximum_memories_per_component: 0,
        ..config()
    })
    .unwrap();
    let backend = factory.create_backend_instance();
    let key = factory.preparation_key(artifact.descriptor.release_digest.clone());
    // The component needs linear memory. Wasmtime may reject its resource
    // shape while pre-instantiating; it must never execute successfully.
    match backend.prepare(&artifact, &key).await {
        Err(error) => assert!(matches!(
            error.code,
            PlatformErrorCode::CorruptArtifact | PlatformErrorCode::IncompatibleContract
        )),
        Ok(prepared) => {
            let cancellation = Cancellation::new("zero-native-memory-pool");
            let report = backend
                .invoke_contained(
                    request(
                        prepared,
                        &cancellation.id,
                        VALUES,
                        "identify",
                        b"[]",
                        budget(),
                    ),
                    &cancellation,
                )
                .await;
            assert_eq!(report.cleanup, ExecutionCleanup::Reusable);
            match report.outcome.unwrap() {
                latent_executor::GuestOutcome::Trapped { trap, .. } => {
                    assert_eq!(trap.code, "guest-runtime-error")
                }
                other => panic!("expected native resource rejection, got {other:?}"),
            }
        }
    }
    assert_eq!(backend.cache_snapshot().preparing, 0);
    finish(factory, backend).await;
}
