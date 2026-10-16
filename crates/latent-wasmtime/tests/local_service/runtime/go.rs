//! Ordinary compiler-built Go APIs through signed V5 node admission.
use super::*;

fn checkpoint_component(
    variable: &str,
    profile: &str,
) -> (latent_packaging::PackageBundle, Vec<u8>) {
    let prepared = std::path::PathBuf::from(
        std::env::var_os(variable).expect("compile the Go checkpoint fixture"),
    );
    let source = std::fs::read(prepared.join("src/main.go")).unwrap();
    let timers = profile == "go-component-activation-v3";
    let expected: &[u8] = if timers {
        include_bytes!("../../../../../sdk/go-guest/runtime/timers-conformance/main.go")
    } else {
        include_bytes!("../../../../../sdk/go-guest/runtime/checkpoints-conformance/main.go")
    };
    assert_eq!(source.as_slice(), expected);
    let record: serde_json::Value = serde_json::from_slice(
        &std::fs::read(prepared.join("GO-ACTIVATION-COMPILE.json")).unwrap(),
    )
    .unwrap();
    assert_eq!(record["profile"], profile);
    assert_eq!(
        record["fixture"],
        if timers { "timers" } else { "checkpoints" }
    );
    assert_eq!(record["sourceUnchanged"], true);
    assert_eq!(
        record["sourceDigest"],
        latent_artifacts::package::artifact_blob_digest(&source).as_str()
    );
    if profile == "go-component-activation-v2" || timers {
        assert_eq!(
            record["nativeReference"]["modes"],
            if timers {
                serde_json::json!([0, 1, 2, 3, 5, 6, 18, 19, 20, 9, 11, 12, 13, 14, 15, 16, 17])
            } else {
                serde_json::json!([0, 1, 4])
            }
        );
        assert_eq!(record["nativeReference"]["output"], 42);
        assert_eq!(record["nativeReference"]["freshProcessPerMode"], true);
        assert_eq!(
            record["nativeReference"]["sourceDigest"],
            record["sourceDigest"]
        );
    }
    let bytes = std::fs::read(prepared.join("build/component.wasm")).unwrap();
    assert_eq!(
        record["componentDigest"],
        latent_artifacts::package::artifact_blob_digest(&bytes).as_str()
    );
    let wit = std::fs::read_to_string(prepared.join("wit/world.wit")).unwrap();
    (packages::go_activation_runtime(bytes, &wit), source)
}

#[tokio::test]
#[ignore = "requires the pinned Go standard timer fixture and explicit go profile"]
async fn signed_standard_timers_contexts_and_rearm_keep_original_heap_owners() {
    assert_eq!(std::env::var("LSF_GUEST_SDK_LANGUAGE").as_deref(), Ok("go"));
    let root = tempfile::tempdir().unwrap();
    let f = prepare_checkpoint_fixture(
        root.path(),
        "LSF_GO_TIMER_FIXTURE",
        "go-component-activation-v3",
    )
    .await;
    let modes = [
        0, 1, 2, 3, 4, 5, 6, 18, 19, 20, 9, 11, 12, 13, 14, 15, 16, 17,
    ];
    for iteration in 0..2 {
        for mode in modes {
            let began = std::time::Instant::now();
            let receipt = success(
                f.manager
                    .start(f.request(&format!("go-timers-{iteration}-{mode}"), mode))
                    .unwrap()
                    .await,
            );
            assert_eq!(
                serde_json::from_slice::<Vec<u32>>(&receipt.output).unwrap(),
                [42]
            );
            assert!(receipt.consumption.cpu_fuel > 0);
            assert!(receipt.consumption.peak_memory_bytes <= packages::budget().memory_bytes);
            if mode == 4 {
                assert!(
                    began.elapsed() >= Duration::from_millis(20),
                    "accepted AfterFunc escaped result drain"
                );
            }
            eprintln!(
                "go-component-activation-v3 iteration={iteration} mode={mode} consumption={:?}",
                receipt.consumption
            );
            f.idle().await;
            assert_eq!(f.read_wait.active.load(Ordering::Acquire), 0);
        }
        // Consume and reconcile every observation before the next finite batch.
        // The fixture keeps its original 32-entry telemetry bound.
        let expected = modes
            .into_iter()
            .map(|mode| format!("go-timers-{iteration}-{mode}"))
            .collect::<std::collections::BTreeSet<_>>();
        let starts = std::mem::take(&mut *f.observations.starts.lock().unwrap());
        let terminals = std::mem::take(&mut *f.observations.terminals.lock().unwrap());
        assert_eq!(starts.len(), modes.len());
        assert_eq!(terminals.len(), modes.len());
        assert_eq!(
            starts
                .into_iter()
                .map(|context| context.activation_id.0)
                .collect::<std::collections::BTreeSet<_>>(),
            expected
        );
        assert_eq!(
            terminals
                .into_iter()
                .map(|(context, _)| context.activation_id.0)
                .collect::<std::collections::BTreeSet<_>>(),
            expected
        );
    }
    for mode in [8, 10] {
        assert_eq!(
            failure(
                f.manager
                    .start(f.request(&format!("go-timer-reject-{mode}"), mode))
                    .unwrap()
                    .await
            )
            .code,
            PlatformErrorCode::GuestTrap
        );
        f.idle().await;
        assert_eq!(
            value(
                f.manager
                    .start(f.request(&format!("go-timer-fresh-{mode}"), 0))
                    .unwrap()
                    .await
            ),
            42
        );
        f.idle().await;
    }
    let id = ActivationId("go-cancel-standard-timer".into());
    let mut invocation = Box::pin(f.manager.start(f.request(&id.0, 7)).unwrap());
    pending_timer(invocation.as_mut(), &f).await;
    f.manager
        .cancel_for(&TenantId("tenant-a".into()), &id, "go-timer-cancel")
        .unwrap();
    assert_eq!(failure(invocation.await).code, PlatformErrorCode::Cancelled);
    f.idle().await;
    let mut deadline = f.request("go-timer-original-root-deadline", 7);
    deadline.budget.wall_time_limit_millis = Some(100);
    assert_eq!(
        failure(f.manager.start(deadline).unwrap().await).code,
        PlatformErrorCode::DeadlineExceeded
    );
    f.idle().await;
    assert_eq!(
        value(
            f.manager
                .start(f.request("go-timer-fresh-after-cancel-deadline", 0))
                .unwrap()
                .await
        ),
        42
    );
    f.idle().await;
}

async fn prepare_checkpoint_fixture(
    root: &std::path::Path,
    variable: &str,
    profile: &str,
) -> Fixture {
    let (caller, source) = checkpoint_component(variable, profile);
    let release = packages::release(&caller);
    let f = signed_runtime_with_limits(
        root,
        1,
        120_000,
        caller,
        &source,
        RuntimeLimits {
            tasks: 4,
            waits: 4,
            ..limits()
        },
    )
    .await;
    let mut key = f.backend.preparation_key(&release).unwrap();
    key.publication = Some(
        f.catalog
            .execution_eligibility_selected(&release, None)
            .unwrap()
            .unwrap()
            .publication()
            .clone(),
    );
    let ready = tokio::time::timeout(
        Duration::from_secs(600),
        f.backend
            .prepare_ready_from_repository(f.catalog.clone(), key),
    )
    .await
    .unwrap()
    .unwrap();
    drop(f.backend.materialize_ready(ready).unwrap());
    f.idle().await;
    assert_eq!(f.backend.resource_snapshot().stores_created, 0);
    f
}

#[tokio::test]
#[ignore = "requires pinned checkpoint and unmodified negative components and explicit go profile"]
async fn signed_compiler_checkpoints_progress_cpu_siblings_and_cancel_original_activation() {
    assert_eq!(std::env::var("LSF_GUEST_SDK_LANGUAGE").as_deref(), Ok("go"));
    let root = tempfile::tempdir().unwrap();
    let f = prepare_checkpoint_fixture(
        root.path(),
        "LSF_GO_CHECKPOINT_FIXTURE",
        "go-component-activation-v2",
    )
    .await;
    for iteration in 0..3 {
        for mode in [0, 1, 4] {
            let receipt = success(
                f.manager
                    .start(f.request(&format!("go-checkpoints-{iteration}-{mode}"), mode))
                    .unwrap()
                    .await,
            );
            assert_eq!(
                serde_json::from_slice::<Vec<u32>>(&receipt.output).unwrap(),
                [42]
            );
            assert!(receipt.consumption.cpu_fuel > 0);
            assert!(receipt.consumption.peak_memory_bytes <= packages::budget().memory_bytes);
            eprintln!(
                "go-component-activation-v2 iteration={iteration} mode={mode} consumption={:?}",
                receipt.consumption
            );
            f.idle().await;
            assert_eq!(f.read_wait.active.load(Ordering::Acquire), 0);
        }
    }
    assert_eq!(
        failure(
            f.manager
                .start(f.request("go-non-suspendable-path", 3))
                .unwrap()
                .await
        )
        .code,
        PlatformErrorCode::GuestTrap
    );
    f.idle().await;
    let id = ActivationId("go-cancel-cpu-checkpoint".into());
    let mut invocation = Box::pin(f.manager.start(f.request(&id.0, 2)).unwrap());
    tokio::time::timeout(
        Duration::from_secs(5),
        std::future::poll_fn(|context| match invocation.as_mut().poll(context) {
            Poll::Ready(receipt) => panic!("CPU checkpoint should yield: {:?}", receipt.outcome),
            Poll::Pending
                if f.backend.resource_snapshot().live_stores == 1
                    && f.broker.snapshot().calls != 0 =>
            {
                Poll::Ready(())
            }
            Poll::Pending => Poll::Pending,
        }),
    )
    .await
    .expect("observe a live original Store at the CPU checkpoint");
    assert_eq!(f.read_wait.active.load(Ordering::Acquire), 0);
    f.manager
        .cancel_for(&TenantId("tenant-a".into()), &id, "go-cpu-cancel")
        .unwrap();
    assert_eq!(failure(invocation.await).code, PlatformErrorCode::Cancelled);
    f.idle().await;
    let mut deadline = f.request("go-cpu-original-root-deadline", 2);
    deadline.budget.wall_time_limit_millis = Some(100);
    assert_eq!(
        failure(f.manager.start(deadline).unwrap().await).code,
        PlatformErrorCode::DeadlineExceeded
    );
    f.idle().await;
    assert_eq!(
        value(
            f.manager
                .start(f.request("go-cpu-fresh-after-retirement", 4))
                .unwrap()
                .await
        ),
        42
    );
    f.idle().await;

    // Identical ordinary source without compiler checkpoints cannot make the
    // sibling progress. Fuel bounds this negative experiment; its exhaustion
    // is not accepted as progress evidence for the maintained profile.
    let negative_root = tempfile::tempdir().unwrap();
    let negative = prepare_checkpoint_fixture(
        negative_root.path(),
        "LSF_GO_NO_CHECKPOINT_FIXTURE",
        "go-component-activation-v1",
    )
    .await;
    let mut blocked = negative.request("go-no-checkpoint-cannot-progress", 0);
    blocked.budget.cpu_fuel = 5_000_000;
    assert_eq!(
        failure(negative.manager.start(blocked).unwrap().await).code,
        PlatformErrorCode::ResourceExhausted
    );
    negative.idle().await;
    assert_eq!(
        value(
            negative
                .manager
                .start(negative.request("go-no-checkpoint-fresh", 4))
                .unwrap()
                .await
        ),
        42
    );
    negative.idle().await;
}

#[tokio::test]
#[ignore = "requires the pinned Go activation fixture and explicit go profile"]
async fn signed_standard_goroutines_sleep_and_drain_use_original_activation_owners() {
    assert_eq!(std::env::var("LSF_GUEST_SDK_LANGUAGE").as_deref(), Ok("go"));
    let prepared = std::path::PathBuf::from(
        std::env::var_os("LSF_GO_ACTIVATION_FIXTURE").expect("compile the Go activation fixture"),
    );
    let source = std::fs::read(prepared.join("src/main.go")).unwrap();
    assert_eq!(
        source.as_slice(),
        include_bytes!("../../../../../sdk/go-guest/runtime/conformance/main.go")
    );
    let record: serde_json::Value = serde_json::from_slice(
        &std::fs::read(prepared.join("GO-ACTIVATION-COMPILE.json")).unwrap(),
    )
    .unwrap();
    assert_eq!(record["profile"], "go-component-activation-v1");
    assert_eq!(record["sourceUnchanged"], true);
    assert_eq!(
        record["sourceDigest"],
        latent_artifacts::package::artifact_blob_digest(&source).as_str()
    );
    let bytes = std::fs::read(prepared.join("build/component.wasm")).unwrap();
    assert_eq!(
        record["componentDigest"],
        latent_artifacts::package::artifact_blob_digest(&bytes).as_str()
    );
    let wit = std::fs::read_to_string(prepared.join("wit/world.wit")).unwrap();
    let caller = packages::go_activation_runtime(bytes, &wit);
    let release = packages::release(&caller);
    let root = tempfile::tempdir().unwrap();
    let runtime_limits = RuntimeLimits {
        tasks: 4,
        waits: 4,
        ..limits()
    };
    let f =
        signed_runtime_with_limits(root.path(), 1, 120_000, caller, &source, runtime_limits).await;
    let publication = f
        .catalog
        .execution_eligibility_selected(&release, None)
        .unwrap()
        .unwrap()
        .publication()
        .clone();
    let mut key = f.backend.preparation_key(&release).unwrap();
    key.publication = Some(publication);
    let ready = tokio::time::timeout(
        Duration::from_secs(600),
        f.backend
            .prepare_ready_from_repository(f.catalog.clone(), key),
    )
    .await
    .unwrap()
    .unwrap();
    drop(f.backend.materialize_ready(ready).unwrap());
    f.idle().await;
    assert_eq!(f.backend.resource_snapshot().stores_created, 0);
    for iteration in 0..3 {
        for mode in [0, 4, 5] {
            let began = std::time::Instant::now();
            let receipt = success(
                f.manager
                    .start(f.request(&format!("go-{iteration}-{mode}"), mode))
                    .unwrap()
                    .await,
            );
            assert_eq!(
                serde_json::from_slice::<Vec<u32>>(&receipt.output).unwrap(),
                [42]
            );
            assert!(receipt.consumption.cpu_fuel > 0);
            assert!(receipt.consumption.peak_memory_bytes <= packages::budget().memory_bytes);
            if mode == 4 {
                assert!(
                    began.elapsed() >= Duration::from_millis(30),
                    "root result bypassed accepted sleeping sibling"
                );
            }
            eprintln!(
                "go-component-activation-v1 iteration={iteration} mode={mode} consumption={:?}",
                receipt.consumption
            );
            f.idle().await;
        }
    }
    for mode in [1, 2, 3, 6, 8, 9] {
        assert_eq!(
            failure(
                f.manager
                    .start(f.request(&format!("go-reject-{mode}"), mode))
                    .unwrap()
                    .await
            )
            .code,
            PlatformErrorCode::GuestTrap
        );
        f.idle().await;
        assert_eq!(
            value(
                f.manager
                    .start(f.request(&format!("go-fresh-{mode}"), 0))
                    .unwrap()
                    .await
            ),
            42
        );
        f.idle().await;
    }
    let id = ActivationId("go-cancel-real-sleep".into());
    let mut invocation = Box::pin(f.manager.start(f.request(id.0.as_str(), 7)).unwrap());
    pending_timer(invocation.as_mut(), &f).await;
    f.manager
        .cancel_for(&TenantId("tenant-a".into()), &id, "go-sleep-cancel")
        .unwrap();
    assert_eq!(failure(invocation.await).code, PlatformErrorCode::Cancelled);
    f.idle().await;
    let mut deadline = f.request("go-original-root-deadline", 7);
    deadline.budget.wall_time_limit_millis = Some(100);
    assert_eq!(
        failure(f.manager.start(deadline).unwrap().await).code,
        PlatformErrorCode::DeadlineExceeded
    );
    f.idle().await;
    assert_eq!(
        value(
            f.manager
                .start(f.request("go-fresh-after-cancel-deadline", 0))
                .unwrap()
                .await
        ),
        42
    );
    f.idle().await;
}
