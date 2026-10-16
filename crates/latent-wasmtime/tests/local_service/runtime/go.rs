//! Ordinary compiler-built Go APIs through signed V5 node admission.
use super::*;

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
