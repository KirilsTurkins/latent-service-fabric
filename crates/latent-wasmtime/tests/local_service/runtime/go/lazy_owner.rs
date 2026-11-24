//! One ordinary, successful Go root on the original activation budget.

#[tokio::test]
#[ignore = "requires the exact captured v2 Go checkpoint fixture"]
async fn signed_go_first_owner_uses_original_lazy_backing() {
    #[cfg(not(feature = "development-go-lazy-owner-observer"))]
    panic!("requires the development-go-lazy-owner-observer feature");
    #[cfg(feature = "development-go-lazy-owner-observer")]
    run_signed_go_first_owner_uses_original_lazy_backing().await;
}

#[cfg(feature = "development-go-lazy-owner-observer")]
async fn run_signed_go_first_owner_uses_original_lazy_backing() {
    use super::*;
    use latent_wasmtime::development_go_lazy_owner_observer as witness;

    assert_eq!(std::env::var("LSF_GUEST_SDK_LANGUAGE").as_deref(), Ok("go"));
    let input = std::path::PathBuf::from(
        std::env::var_os("LSF_GO_CHECKPOINT_FIXTURE").expect("captured checkpoint fixture"),
    );
    let (caller, source) =
        checkpoint_component("LSF_GO_CHECKPOINT_FIXTURE", "go-component-activation-v2");
    let record: serde_json::Value =
        serde_json::from_slice(&std::fs::read(input.join("GO-ACTIVATION-COMPILE.json")).unwrap())
            .unwrap();
    assert_eq!(record["fixture"], "checkpoints-captured");
    assert_eq!(
        std::fs::read(input.join("wit/world.wit")).unwrap(),
        include_bytes!("../../../../../../sdk/go-guest/runtime/checkpoints-conformance/world.wit")
    );
    let bridge = include_bytes!("../../../../../../sdk/go-guest/runtime/activation_bridge.go.in");
    let overlay = std::fs::read(input.join("build/runtime-overlay/runtime_os_wasip1.go")).unwrap();
    assert_eq!(
        overlay
            .windows(bridge.len())
            .filter(|window| *window == bridge)
            .count(),
        1
    );
    assert_eq!(
        std::fs::read(input.join("work/vendor/lsf/sdk/go-guest/toolchain.lock.json")).unwrap(),
        include_bytes!("../../../../../../sdk/go-guest/toolchain.lock.json")
    );
    let transformations = std::fs::read(input.join("go-runtime-transformations.json")).unwrap();
    assert_eq!(
        record["capturedDependency"]["transformationsDigest"],
        latent_artifacts::package::artifact_blob_digest(&transformations).as_str()
    );

    // A large configured maximum makes eager versus lazy backing observable;
    // the ordinary v2 mode below creates no application siblings or timers.
    let limits = RuntimeLimits {
        tasks: 2,
        executors: 0,
        queued_work: 8188,
        waits: 2,
        timers: 0,
        results: 0,
        native_owners: 0,
    };
    assert_eq!(limits.total(), 8192);
    let release = packages::release(&caller);
    let root = tempfile::tempdir().unwrap();
    let f = signed_runtime_with_limits(root.path(), 1, 120_000, caller, &source, limits).await;
    let mut key = f.backend.preparation_key(&release).unwrap();
    key.publication = Some(
        f.catalog
            .execution_eligibility_selected(&release, None)
            .unwrap()
            .unwrap()
            .publication()
            .clone(),
    );
    let prepared = tokio::time::timeout(
        Duration::from_secs(600),
        f.backend
            .prepare_ready_from_repository(f.catalog.clone(), key),
    )
    .await
    .unwrap()
    .unwrap();
    drop(f.backend.materialize_ready(prepared).unwrap());
    f.idle().await;
    assert_eq!(f.backend.resource_snapshot().stores_created, 0);

    let guard = witness::arm().expect("the one original owner observer must be available");
    let request = f.request(witness::ACTIVATION, 4);
    let original_memory = request.budget.memory_bytes;
    let receipt = f.manager.start(request).unwrap().await;
    let selected = receipt
        .resolved_revision
        .as_ref()
        .expect("selected publication");
    assert_eq!(selected.release, release);
    assert!(selected.publication.is_some());
    let receipt = success(receipt);
    assert_eq!(
        serde_json::from_slice::<Vec<u32>>(&receipt.output).unwrap(),
        [42]
    );
    assert!(receipt.consumption.cpu_fuel > 0);
    assert!(receipt.consumption.peak_memory_bytes <= original_memory);
    let observed = guard
        .snapshot()
        .expect("the first original owner must be observed");
    assert_eq!(observed.calls, 1);
    assert!(!observed.table_preexisting);
    assert_eq!(observed.granted_bytes, original_memory);
    assert_eq!((observed.owner.before, observed.owner.after), (0, 1));
    assert_eq!(observed.owner.capacity, 1);
    assert_eq!((observed.owner.tasks, observed.owner.other_owners), (1, 0));
    assert!(observed.owner.live_token);
    assert!(observed.owner.same_original_budget);
    drop(guard);

    f.idle().await;
    let backend = f.backend.resource_snapshot();
    assert_eq!(backend.stores_created, 1);
    assert_eq!(backend.live_stores, 0);
    assert_eq!(backend.live_component_instances, 0);
    assert_eq!(f.backend.active_instance_reservations(), 0);
    let quota = f.quotas.usage().unwrap();
    assert_eq!(quota.reserved_cpu_fuel, 0);
    assert_eq!(quota.reserved_memory_bytes, 0);
    println!(
        "GO_LAZY_FIRST_OWNER {}",
        serde_json::json!({
            "componentDigest":record["componentDigest"], "sourceDigest":record["sourceDigest"],
            "transformationsDigest":record["capturedDependency"]["transformationsDigest"],
            "profile":"go-component-activation-v2", "mode":4, "result":42,
            "originalMemoryBytes":original_memory, "originalOwnerCapacity":observed.owner.capacity,
            "oneOriginalTask":true, "sameOriginalBudget":true,
            "peakMemoryBytes":receipt.consumption.peak_memory_bytes,
            "userSpaceStoreRetired":true, "kernelFinalFreeQualified":false
        })
    );
}
