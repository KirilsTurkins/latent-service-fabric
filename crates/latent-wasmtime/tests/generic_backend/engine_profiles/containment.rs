use std::future::poll_fn;
use std::task::Poll;

use latent_core::{ActivationId, BoxFuture};
use latent_executor::{
    ExecutionBackend, ExecutionCancellation, ExecutionReport, GuestInterruptionKind, GuestOutcome,
    PreparedComponent,
};
use latent_wasmtime::{InvocationInputObserver, InvocationInputPhase};

use super::*;
use crate::support::run;

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires the generic component built by tools/validate_contracts.sh"]
async fn every_profile_preserves_dispatch_traps_budgets_cancellation_and_fresh_state() {
    let artifact = artifact();
    for policy in profiles() {
        let factory = WasmtimeComponentEngineFactory::new(policy).unwrap();
        let backend = factory.create_backend_instance();
        let prepared = backend
            .prepare(
                &artifact,
                &factory.preparation_key(artifact.descriptor.release_digest.clone()),
            )
            .await
            .unwrap();
        assert_eq!(
            returned(call(&backend, &prepared, "identify", b"[]").await),
            json!([11])
        );
        assert_eq!(
            returned(call(&backend, &prepared, "combine", b"[4,5]").await),
            json!([9])
        );
        match call(&backend, &prepared, "trap", b"[]").await {
            GuestOutcome::Trapped { trap, .. } => {
                assert_eq!(trap.code, "guest-trap");
                assert!(trap.guest_backtrace.is_empty());
            }
            other => panic!("expected contained trap: {other:?}"),
        }
        recover(&backend, &prepared).await;
        budgets(&backend, &prepared).await;
        cancellation(&backend, &prepared).await;
        backend.release(prepared).await.unwrap();
        finish(factory, backend).await;
    }
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires the generic component built by tools/validate_contracts.sh"]
async fn every_profile_drops_pending_native_ownership_and_recovers_the_only_slot() {
    let artifact = artifact();
    for mut policy in profiles() {
        // A leaked native pool slot cannot hide behind another free slot.
        policy.pooling_maximum_instances = 1;
        policy.maximum_active_instances = 1;
        let factory = WasmtimeComponentEngineFactory::new(policy).unwrap();
        let backend = factory.create_backend_instance();
        let observer = backend.invocation_input_observer();
        let ids = ["profile-running-drop", "bump"].map(|id| ActivationId(id.to_owned()));
        observer.enable(&ids).unwrap();
        let key = factory.preparation_key(artifact.descriptor.release_digest.clone());
        let owner = backend.prepare_for_use(&artifact, &key).await.unwrap();
        let prepared = owner.descriptor().clone();
        assert_eq!(backend.active_instance_reservations(), 1);
        let cancellation = Cancellation::new(&ids[0].0);
        let mut invocation = backend.invoke_prepared_contained(
            request(
                prepared.clone(),
                &cancellation.id,
                VALUES,
                "spin",
                b"[]",
                budget(),
            ),
            owner,
            &cancellation,
        );
        pending_guest(&mut invocation, &observer).await;
        let live = backend.resource_snapshot();
        assert_eq!(live.active_invocations, 1);
        assert_eq!(live.live_stores, 1);
        assert_eq!(live.live_host_states, 1);
        assert_eq!(live.live_component_instances, 1);
        assert_eq!(live.live_cancellation_probes, 1);
        assert_eq!(backend.active_instance_reservations(), 1);
        assert!(!cancellation.is_cancelled());

        // This abandons the actual polled future; no cooperative Cancel or
        // terminal report is used as a substitute for destruction.
        drop(invocation);
        idle(&backend);
        assert_eq!(backend.active_instance_reservations(), 0);
        let dropped = observer.snapshot();
        assert!(!dropped.overflowed);
        assert_eq!(dropped.started_invocations, 1);
        assert_eq!(dropped.finished_invocations, 0);
        assert_eq!(dropped.dropped_invocations, 1);
        assert_eq!(dropped.live_invocations, 0);
        assert_eq!(dropped.live_raw_owners, 0);
        assert_eq!(dropped.live_raw_capacity_bytes, 0);
        assert_eq!(backend.stores_created(), 1);

        recover(&backend, &prepared).await;
        assert_eq!(backend.stores_created(), 2);
        let recovered = observer.snapshot();
        assert!(!recovered.overflowed);
        assert_eq!(recovered.started_invocations, 2);
        assert_eq!(recovered.finished_invocations, 1);
        assert_eq!(recovered.dropped_invocations, 1);
        assert_eq!(recovered.live_invocations, 0);
        backend.release(prepared).await.unwrap();
        finish(factory, backend).await;
    }
}

async fn pending_guest(
    invocation: &mut BoxFuture<'_, ExecutionReport>,
    observer: &InvocationInputObserver,
) {
    tokio::time::timeout(
        WATCHDOG,
        poll_fn(|context| {
            let result = invocation.as_mut().poll(context);
            assert!(
                result.is_pending(),
                "spin completed before direct Drop: {result:?}"
            );
            let snapshot = observer.snapshot();
            assert!(!snapshot.overflowed);
            if snapshot
                .records
                .iter()
                .any(|record| record.phase == InvocationInputPhase::GuestCallStart)
            {
                Poll::Ready(())
            } else {
                Poll::Pending
            }
        }),
    )
    .await
    .expect("actual guest dispatch and Pending within watchdog");
}

async fn budgets(backend: &WasmtimeBackend, prepared: &PreparedComponent) {
    for (function, expected) in [
        ("spin", GuestInterruptionKind::FuelExhausted),
        ("grow", GuestInterruptionKind::MemoryExhausted),
    ] {
        let cancellation = Cancellation::new(function);
        let mut grant = budget();
        if function == "spin" {
            grant.cpu_fuel = 50_000;
        } else {
            grant.memory_bytes = 4 * 1024 * 1024;
        }
        let outcome = run(
            backend,
            request(
                prepared.clone(),
                &cancellation.id,
                VALUES,
                function,
                b"[]",
                grant.clone(),
            ),
            &cancellation,
        )
        .await
        .unwrap();
        match outcome {
            GuestOutcome::Interrupted {
                kind, consumption, ..
            } => {
                assert_eq!(kind, expected);
                assert!(consumption.peak_memory_bytes <= grant.memory_bytes);
            }
            other => panic!("expected bounded interruption: {other:?}"),
        }
        recover(backend, prepared).await;
    }
}

async fn cancellation(backend: &WasmtimeBackend, prepared: &PreparedComponent) {
    let cancellation = Cancellation::new("profile-running-cancel");
    let invocation = run(
        backend,
        request(
            prepared.clone(),
            &cancellation.id,
            VALUES,
            "spin",
            b"[]",
            budget(),
        ),
        &cancellation,
    );
    let cancel = async {
        tokio::time::timeout(WATCHDOG, async {
            while backend.resource_snapshot().live_component_instances == 0 {
                tokio::task::yield_now().await;
            }
        })
        .await
        .unwrap();
        cancellation.cancel();
    };
    let (outcome, ()) = tokio::join!(invocation, cancel);
    assert!(matches!(
        outcome.unwrap(),
        GuestOutcome::Interrupted {
            kind: GuestInterruptionKind::Cancelled,
            ..
        }
    ));
    recover(backend, prepared).await;
}

async fn recover(backend: &WasmtimeBackend, prepared: &PreparedComponent) {
    idle(backend);
    assert_eq!(
        returned(call(backend, prepared, "bump", b"[]").await),
        json!([1])
    );
    idle(backend);
}
