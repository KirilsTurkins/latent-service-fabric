use latent_executor::{ExecutionBackend, GuestInterruptionKind, GuestOutcome, PreparedComponent};

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
