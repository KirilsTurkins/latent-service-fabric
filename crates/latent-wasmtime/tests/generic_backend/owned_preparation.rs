use std::panic::{catch_unwind, AssertUnwindSafe};
use std::task::{Context, Waker};
use std::time::Instant;

use latent_core::{
    ActivationBudget, ActivationId, ClockSample, EffectiveActivationBudget, PlatformErrorCode,
};
use latent_executor::{ExecutionBackend, ExecutionCancellation, ExecutionCleanup, PreparedUse};
use latent_wasmtime::WasmtimeComponentEngineFactory;
use serde_json::json;

use super::support::{
    artifact, budget, config, idle, request, returned, Cancellation, VALUES, WATCHDOG,
};

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires the generic component built by tools/validate_contracts.sh"]
async fn prepared_use_survives_cache_eviction_and_release_without_a_second_permit() {
    let mut config = config();
    config.maximum_active_instances = 1;
    config.prepared_cache_maximum_entries = 1;
    let factory = WasmtimeComponentEngineFactory::new(config).unwrap();
    let backend = factory.create_backend_instance();
    let peer = factory.create_backend_instance();
    let artifact = artifact();
    let key = backend
        .preparation_key(&artifact.descriptor.release_digest)
        .unwrap();
    assert_eq!(
        key,
        factory.preparation_key(artifact.descriptor.release_digest.clone())
    );
    let owned = backend.prepare_for_use(&artifact, &key).await.unwrap();
    let descriptor = owned.descriptor().clone();
    assert_eq!(backend.active_instance_reservations(), 1);
    let mut replacement = artifact.clone();
    replacement
        .manifest
        .metadata
        .annotations
        .insert("changed".to_owned(), "metadata".to_owned());
    let replacement = peer.prepare(&replacement, &key).await.unwrap();
    assert_ne!(replacement.opaque_handle, descriptor.opaque_handle);
    peer.release(replacement).await.unwrap();
    backend.release(descriptor.clone()).await.unwrap();
    assert_eq!(backend.cache_snapshot().entries, 0);
    assert_eq!(backend.active_instance_reservations(), 1);
    let cancellation = Cancellation::new("evicted-owner");
    let report = tokio::time::timeout(
        WATCHDOG,
        peer.invoke_prepared_contained(
            request(
                descriptor,
                &cancellation.id,
                VALUES,
                "identify",
                b"[]",
                budget(),
            ),
            owned,
            &cancellation,
        ),
    )
    .await
    .unwrap();
    assert_eq!(report.cleanup, ExecutionCleanup::Reusable);
    assert_eq!(returned(report.outcome.unwrap()), json!([11]));
    assert_eq!(backend.active_instance_reservations(), 0);
    assert_eq!(backend.cache_snapshot().entries, 0);
    idle(&backend);
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires the generic component built by tools/validate_contracts.sh"]
async fn prepared_use_gate_is_refunded_on_unused_future_unwind_and_preparation_error() {
    let mut config = config();
    config.maximum_active_instances = 1;
    let factory = WasmtimeComponentEngineFactory::new(config).unwrap();
    let backend = factory.create_backend_instance();
    let artifact = artifact();
    let key = backend
        .preparation_key(&artifact.descriptor.release_digest)
        .unwrap();
    let owned = backend.prepare_for_use(&artifact, &key).await.unwrap();
    let error = backend.prepare_for_use(&artifact, &key).await.unwrap_err();
    assert_eq!(error.code, PlatformErrorCode::Unavailable);
    assert!(error.retryable);
    let cancellation = Cancellation::new("never-polled-owner");
    let request = request(
        owned.descriptor().clone(),
        &cancellation.id,
        VALUES,
        "identify",
        b"[]",
        budget(),
    );
    drop(backend.invoke_prepared_contained(request, owned, &cancellation));
    assert_eq!(backend.active_instance_reservations(), 0);
    let owned = backend.prepare_for_use(&artifact, &key).await.unwrap();
    assert!(catch_unwind(AssertUnwindSafe(move || {
        let _owned = owned;
        panic!("materialization abandoned");
    }))
    .is_err());
    assert_eq!(backend.active_instance_reservations(), 0);
    let mut corrupt = artifact.clone();
    corrupt.component_bytes[0] ^= 1;
    assert_eq!(
        backend
            .prepare_for_use(&corrupt, &key)
            .await
            .unwrap_err()
            .code,
        PlatformErrorCode::CorruptArtifact
    );
    assert_eq!(backend.active_instance_reservations(), 0);
    assert_eq!(backend.cache_snapshot().preparing, 0);
    drop(backend.prepare_for_use(&artifact, &key).await.unwrap());
    assert_eq!(backend.active_instance_reservations(), 0);
    assert_eq!(backend.stores_created(), 0);
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires the generic component built by tools/validate_contracts.sh"]
async fn foreign_factory_changed_descriptor_and_foreign_guard_fail_before_store_creation() {
    let factory = WasmtimeComponentEngineFactory::new(config()).unwrap();
    let other_factory = WasmtimeComponentEngineFactory::new(config()).unwrap();
    let backend = factory.create_backend_instance();
    let other = other_factory.create_backend_instance();
    let artifact = artifact();
    let key = backend
        .preparation_key(&artifact.descriptor.release_digest)
        .unwrap();
    assert_eq!(
        key,
        other
            .preparation_key(&artifact.descriptor.release_digest)
            .unwrap()
    );
    let cancellation = Cancellation::new("wrong-owner");
    for mode in 0..3 {
        let owned = backend.prepare_for_use(&artifact, &key).await.unwrap();
        let mut descriptor = owned.descriptor().clone();
        let target = if mode == 0 { &other } else { &backend };
        if mode == 1 {
            descriptor
                .metadata
                .insert("forged".to_owned(), "value".to_owned());
        }
        let owned = if mode == 2 {
            drop(owned);
            PreparedUse::new(descriptor.clone(), ())
        } else {
            owned
        };
        let report = target
            .invoke_prepared_contained(
                request(
                    descriptor,
                    &cancellation.id,
                    VALUES,
                    "identify",
                    b"[]",
                    budget(),
                ),
                owned,
                &cancellation,
            )
            .await;
        assert_eq!(
            report.outcome.unwrap_err().code,
            PlatformErrorCode::InvalidArgument
        );
        assert_eq!(report.cleanup, ExecutionCleanup::Reusable);
        assert_eq!(backend.active_instance_reservations(), 0);
    }
    assert_eq!(backend.stores_created(), 0);
    assert_eq!(other.stores_created(), 0);
}

struct AccountedCancellation {
    id: ActivationId,
    budget: ActivationBudget,
}

impl ExecutionCancellation for AccountedCancellation {
    fn activation_id(&self) -> &ActivationId {
        &self.id
    }
    fn is_cancelled(&self) -> bool {
        false
    }
    fn reason(&self) -> Option<String> {
        None
    }
    fn budget_accounting(&self) -> Option<&ActivationBudget> {
        Some(&self.budget)
    }
}

fn accounted(id: &str) -> AccountedCancellation {
    let mut budget = budget();
    // Finite fuel bounds guest work even if cooperative yielding regresses,
    // independently of the watchdog and epoch ticker scheduling.
    budget.cpu_fuel = 100_000;
    let grant = EffectiveActivationBudget::admit_at(
        &budget,
        &budget,
        &budget,
        None,
        ClockSample::new(1_000, Instant::now()),
    )
    .unwrap();
    AccountedCancellation {
        id: ActivationId(id.to_owned()),
        budget: ActivationBudget::new(grant),
    }
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires the generic component built by tools/validate_contracts.sh"]
async fn dropped_and_unwinding_pending_guests_preserve_unsampled_fuel_and_memory() {
    let mut config = config();
    config.fuel_async_yield_interval = Some(1_000);
    let factory = WasmtimeComponentEngineFactory::new(config).unwrap();
    let backend = factory.create_backend_instance();
    let artifact = artifact();
    let key = backend
        .preparation_key(&artifact.descriptor.release_digest)
        .unwrap();
    for unwind in [false, true] {
        let owned = backend.prepare_for_use(&artifact, &key).await.unwrap();
        let cancellation = accounted("abandoned-store");
        let request = request(
            owned.descriptor().clone(),
            &cancellation.id,
            VALUES,
            "spin",
            b"[]",
            cancellation.budget.granted().clone(),
        );
        let mut future = backend.invoke_prepared_contained(request, owned, &cancellation);
        tokio::time::timeout(WATCHDOG, async {
            let mut context = Context::from_waker(Waker::noop());
            // Cooperative fuel yields are independent of epoch thread timing.
            // The fixture has no context checkpoints that charge the ledger.
            for attempt in 0..2 {
                let polled = future.as_mut().poll(&mut context);
                assert!(polled.is_pending(), "yield {attempt}: {polled:?}");
            }
        })
        .await
        .expect("bounded guest yield watchdog");
        assert_eq!(backend.resource_snapshot().live_stores, 1);
        assert_eq!(cancellation.budget.snapshot_at(Instant::now()).cpu_fuel, 0);
        if unwind {
            assert!(catch_unwind(AssertUnwindSafe(move || {
                let _future = future;
                panic!("owner unwinds while guest is suspended");
            }))
            .is_err());
        } else {
            drop(future);
        }
        let consumed = cancellation.budget.snapshot_at(Instant::now());
        assert!(consumed.cpu_fuel > 0);
        assert!(consumed.peak_memory_bytes > 0);
        assert!(consumed.cpu_fuel <= cancellation.budget.granted().cpu_fuel);
        assert!(consumed.peak_memory_bytes <= cancellation.budget.granted().memory_bytes);
        assert!(cancellation.budget.finalization().is_none());
        assert_eq!(backend.active_instance_reservations(), 0);
        idle(&backend);
    }
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires the generic component built by tools/validate_contracts.sh"]
async fn normal_completion_and_store_drop_charge_the_same_fuel_only_once() {
    let factory = WasmtimeComponentEngineFactory::new(config()).unwrap();
    let backend = factory.create_backend_instance();
    let artifact = artifact();
    let key = backend
        .preparation_key(&artifact.descriptor.release_digest)
        .unwrap();
    let owned = backend.prepare_for_use(&artifact, &key).await.unwrap();
    let cancellation = accounted("completed-store");
    let report = backend
        .invoke_prepared_contained(
            request(
                owned.descriptor().clone(),
                &cancellation.id,
                VALUES,
                "identify",
                b"[]",
                cancellation.budget.granted().clone(),
            ),
            owned,
            &cancellation,
        )
        .await;
    let latent_executor::GuestOutcome::Returned { consumption, .. } = report.outcome.unwrap()
    else {
        panic!("returned");
    };
    let actual = cancellation.budget.snapshot_at(Instant::now());
    assert!(actual.cpu_fuel > 0);
    assert_eq!(actual.cpu_fuel, consumption.cpu_fuel);
    assert_eq!(actual.peak_memory_bytes, consumption.peak_memory_bytes);
    assert_eq!(backend.active_instance_reservations(), 0);
    idle(&backend);
}
