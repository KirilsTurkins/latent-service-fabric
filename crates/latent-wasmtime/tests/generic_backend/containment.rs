use std::time::{Duration, Instant};

use latent_core::{ClockSample, EffectiveActivationBudget};
use latent_executor::{ExecutionBackend, GuestInterruptionKind, GuestOutcome};
use latent_wasmtime::WasmtimeComponentEngineFactory;
use serde_json::json;

use super::support::{
    adversarial, artifact, budget, call, config, idle, now_millis, prepared, request, returned,
    run, Cancellation, ADVERSARIAL, VALUES, WATCHDOG,
};

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires the generic component built by tools/validate_contracts.sh"]
async fn preserves_expired_admission_monotonic_deadline_when_unix_representation_is_future() {
    let (backend, prepared) = prepared(config()).await;
    let grant = budget();
    let sampled_wall = now_millis() + 10_000;
    let admitted = EffectiveActivationBudget::admit_at(
        &grant,
        &grant,
        &grant,
        Some(sampled_wall + 25),
        ClockSample::new(
            sampled_wall,
            Instant::now()
                .checked_sub(Duration::from_millis(100))
                .expect("test clock supports a past admission"),
        ),
    )
    .expect("deterministic admission sample");
    assert!(admitted.deadline.is_expired_at(Instant::now()));
    assert!(admitted.deadline.unix_millis().expect("wall deadline") > now_millis());
    let mut cancellation = Cancellation::new("original-monotonic-deadline");
    let mut request = request(
        prepared,
        &cancellation.id,
        VALUES,
        "identify",
        b"[]",
        admitted.budget,
    );
    request.activation.deadline_unix_millis = admitted.deadline.unix_millis();
    cancellation.deadline = Some(admitted.deadline);
    let outcome = run(&backend, request, &cancellation)
        .await
        .expect("expired deadline outcome");
    assert!(matches!(
        outcome,
        GuestOutcome::Interrupted {
            kind: GuestInterruptionKind::DeadlineExceeded,
            ..
        }
    ));
    assert_eq!(backend.resource_snapshot().stores_created, 0);
    idle(&backend);
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires the generic component built by tools/validate_contracts.sh"]
async fn tightened_request_deadline_stops_before_store_despite_live_admission_deadline() {
    let (backend, prepared) = prepared(config()).await;
    let grant = budget();
    let sampled_wall = now_millis();
    let admitted = EffectiveActivationBudget::admit_at(
        &grant,
        &grant,
        &grant,
        Some(sampled_wall + 10_000),
        ClockSample::new(sampled_wall, Instant::now()),
    )
    .expect("future admission deadline");
    assert!(!admitted.deadline.is_expired_at(Instant::now()));
    let mut cancellation = Cancellation::new("tightened-request-deadline");
    let mut request = request(
        prepared,
        &cancellation.id,
        VALUES,
        "identify",
        b"[]",
        admitted.budget,
    );
    request.activation.deadline_unix_millis = Some(
        sampled_wall
            .checked_sub(1)
            .expect("test wall clock follows the Unix epoch"),
    );
    cancellation.deadline = Some(admitted.deadline);
    let outcome = run(&backend, request, &cancellation)
        .await
        .expect("tightened deadline outcome");
    assert!(matches!(
        outcome,
        GuestOutcome::Interrupted {
            kind: GuestInterruptionKind::DeadlineExceeded,
            ..
        }
    ));
    assert_eq!(backend.resource_snapshot().stores_created, 0);
    idle(&backend);
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires the generic component built by tools/validate_contracts.sh"]
async fn contains_direct_trap_fuel_and_memory_exports_then_recovers() {
    let (backend, prepared) = prepared(config()).await;
    match call(&backend, &prepared, "trap", b"[]").await {
        GuestOutcome::Trapped { trap, .. } => {
            assert_eq!(trap.code, "guest-trap");
            assert!(trap.message.len() <= 512);
            assert!(trap.guest_backtrace.is_empty());
        }
        other => panic!("expected trap, got {other:?}"),
    }
    idle(&backend);
    assert_eq!(
        returned(call(&backend, &prepared, "bump", b"[]").await),
        json!([1])
    );
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
            &backend,
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
        .expect("contained interruption");
        match outcome {
            GuestOutcome::Interrupted {
                kind,
                consumption,
                reason,
            } => {
                assert_eq!(kind, expected);
                assert!(reason.len() <= 512);
                assert!(consumption.peak_memory_bytes <= grant.memory_bytes);
            }
            other => panic!("expected interruption, got {other:?}"),
        }
        idle(&backend);
        assert_eq!(
            returned(call(&backend, &prepared, "bump", b"[]").await),
            json!([1])
        );
    }
    idle(&backend);
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires the generic component built by tools/validate_contracts.sh"]
async fn deadline_stops_non_cooperative_guest_while_another_activation_completes() {
    let (backend, prepared) = prepared(config()).await;
    let cancellation = Cancellation::new("deadline-spin");
    let mut request = request(
        prepared.clone(),
        &cancellation.id,
        VALUES,
        "spin",
        b"[]",
        budget(),
    );
    request.activation.deadline_unix_millis = Some(now_millis() + 30);
    let started = Instant::now();
    let spin = run(&backend, request, &cancellation);
    let healthy = async {
        wait_for_guest(&backend).await;
        assert_eq!(
            returned(call(&backend, &prepared, "identify", b"[]").await),
            json!([11])
        );
    };
    let (outcome, ()) = tokio::join!(spin, healthy);
    assert!(matches!(
        outcome.expect("deadline outcome"),
        GuestOutcome::Interrupted {
            kind: GuestInterruptionKind::DeadlineExceeded,
            ..
        }
    ));
    assert!(
        started.elapsed() < Duration::from_millis(531),
        "30ms deadline + 1ms epoch + 500ms CI allowance"
    );
    idle(&backend);
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires the generic component built by tools/validate_contracts.sh"]
async fn cancellation_reaches_running_guest_and_drops_the_live_probe() {
    let (backend, prepared) = prepared(config()).await;
    let cancellation = Cancellation::new("cancel-spin");
    let spin = run(
        &backend,
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
        wait_for_guest(&backend).await;
        cancellation.cancel();
    };
    let (outcome, ()) = tokio::join!(spin, cancel);
    assert!(matches!(
        outcome.expect("cancel outcome"),
        GuestOutcome::Interrupted {
            kind: GuestInterruptionKind::Cancelled,
            ..
        }
    ));
    idle(&backend);
    assert_eq!(std::sync::Arc::strong_count(&cancellation.state), 1);
    assert_eq!(
        returned(call(&backend, &prepared, "bump", b"[]").await),
        json!([1])
    );
    idle(&backend);
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires the WAT components built by tools/validate_contracts.sh"]
async fn canonical_post_return_failure_is_contained_before_cleanup_proof() {
    let factory = WasmtimeComponentEngineFactory::new(config()).expect("factory");
    let backend = factory.create_backend_instance();
    let fault_artifact = adversarial("bad-post-return");
    let prepared = backend
        .prepare(
            &fault_artifact,
            &factory.preparation_key(fault_artifact.descriptor.release_digest.clone()),
        )
        .await
        .expect("post-return fixture prepares");
    let cancellation = Cancellation::new("post-return");
    let outcome = run(
        &backend,
        request(
            prepared,
            &cancellation.id,
            ADVERSARIAL,
            "value",
            b"[]",
            budget(),
        ),
        &cancellation,
    )
    .await
    .expect("post-return failure remains a guest outcome");
    assert!(
        matches!(outcome, GuestOutcome::Trapped { .. }),
        "must execute the trapping post-return"
    );
    idle(&backend);
    let artifact = artifact();
    let healthy = backend
        .prepare(
            &artifact,
            &factory.preparation_key(artifact.descriptor.release_digest.clone()),
        )
        .await
        .expect("healthy fixture after post-return failure");
    assert_eq!(
        returned(call(&backend, &healthy, "identify", b"[]").await),
        json!([11])
    );
    idle(&backend);
}

async fn wait_for_guest(backend: &latent_wasmtime::WasmtimeBackend) {
    tokio::time::timeout(WATCHDOG, async {
        while backend.resource_snapshot().live_component_instances == 0 {
            tokio::task::yield_now().await;
        }
    })
    .await
    .expect("a live guest must be observable");
}
