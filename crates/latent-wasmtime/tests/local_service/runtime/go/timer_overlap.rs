//! Separate signed Go overlap fixture with the original timer provider.
use super::*;

async fn retired(f: &Fixture, case: &str, mode: u32, outcome: &str, created: u64) {
    f.idle().await;
    assert_eq!(f.read_wait.active.load(Ordering::Acquire), 0);
    let state = f.backend.resource_snapshot();
    assert_eq!(state.stores_created, created);
    assert_eq!(state.live_stores, 0);
    assert_eq!(state.live_component_instances, 0);
    assert_eq!(f.backend.active_instance_reservations(), 0);
    let quota = f.quotas.usage().unwrap();
    assert_eq!(quota.active_activations, 0);
    assert_eq!(quota.reserved_cpu_fuel, 0);
    assert_eq!(quota.reserved_memory_bytes, 0);
    println!(
        "GO_TIMER_OVERLAP_CASE {}",
        serde_json::json!({
            "case":case,"mode":mode,"outcome":outcome,"storesCreated":created,
            "liveStores":0,"liveInstances":0,"reservations":0,"reservedFuel":0,
            "reservedMemory":0,"pendingProviderWaits":0
        })
    );
}

#[tokio::test]
#[ignore = "requires captured ordinary v5 Go source and the bounded development timer witness"]
async fn signed_overlapping_public_timer_operations_retire_the_original_wait() {
    run_overlap("LSF_GO_TIMER_OVERLAP_FIXTURE", "go-component-activation-v5").await;
}

#[tokio::test]
#[ignore = "requires captured ordinary v7 Go source and the bounded development timer witness"]
async fn signed_v7_overlapping_public_timer_operations_retire_the_original_wait() {
    run_overlap(
        "LSF_GO_V7_TIMER_OVERLAP_FIXTURE",
        "go-component-activation-v7",
    )
    .await;
}

async fn run_overlap(variable: &str, profile: &str) {
    assert!(cfg!(feature = "development-go-timer-overlap"));
    assert_eq!(std::env::var("LSF_GUEST_SDK_LANGUAGE").as_deref(), Ok("go"));
    let root = tempfile::tempdir().unwrap();
    // The existing Task16 / Wait4 / Timer2 profile and request budget are not
    // enlarged for this independently selected witness.
    let f = prepare_owned_fixture(root.path(), variable, profile, 16).await;
    let mut publication = None;
    for (case, id, mode, created) in [
        ("reset-reset", "go-timer-overlap-reset-reset", 0, 1),
        ("reset-stop", "go-timer-overlap-reset-stop", 1, 2),
        ("gc-reset-reset", "go-timer-overlap-gc-reset-reset", 2, 3),
        ("gc-reset-stop", "go-timer-overlap-gc-reset-stop", 3, 4),
    ] {
        let result = f.manager.start(f.request(id, mode)).unwrap().await;
        let selected = result
            .resolved_revision
            .as_ref()
            .expect("signed publication");
        let identity = (
            selected.release.clone(),
            selected.publication.clone().expect("original publication"),
        );
        if let Some(original) = &publication {
            assert_eq!(*original, identity);
        } else {
            publication = Some(identity);
        }
        let receipt = success(result);
        assert_eq!(
            serde_json::from_slice::<Vec<u32>>(&receipt.output).unwrap(),
            [42]
        );
        assert!(receipt.consumption.cpu_fuel > 0);
        assert!(receipt.consumption.peak_memory_bytes <= packages::budget().memory_bytes);
        retired(&f, case, mode, "success", created).await;
    }

    let id = ActivationId("go-timer-overlap-cancel-reset-reset".into());
    let mut request = f.request(&id.0, 0);
    request.budget.wall_time_limit_millis = Some(4_000);
    let mut invocation = Box::pin(f.manager.start(request).unwrap());
    tokio::select! {
        result = &mut invocation => panic!("root completed before cancellation: {:?}", result.outcome),
        () = tokio::time::sleep(Duration::from_millis(800)) => {}
    }
    f.manager
        .cancel_for(&TenantId("tenant-a".into()), &id, "go-timer-overlap-cancel")
        .unwrap();
    assert_eq!(failure(invocation.await).code, PlatformErrorCode::Cancelled);
    retired(&f, "cancel-reset-reset", 0, "cancelled", 5).await;

    let mut deadline = f.request("go-timer-overlap-deadline-reset-stop", 1);
    deadline.budget.wall_time_limit_millis = Some(1_800);
    assert_eq!(
        failure(f.manager.start(deadline).unwrap().await).code,
        PlatformErrorCode::DeadlineExceeded
    );
    retired(&f, "deadline-reset-stop", 1, "deadline-exceeded", 6).await;

    let result = f
        .manager
        .start(f.request("go-timer-overlap-fresh", 0))
        .unwrap()
        .await;
    let selected = result
        .resolved_revision
        .as_ref()
        .expect("signed publication");
    assert_eq!(
        publication,
        Some((
            selected.release.clone(),
            selected.publication.clone().unwrap()
        ))
    );
    assert_eq!(
        serde_json::from_slice::<Vec<u32>>(&success(result).output).unwrap(),
        [42]
    );
    retired(&f, "fresh", 0, "success", 7).await;
    // Each selected Store emits its own fixed-width causal record on drop.
    // The owner independently requires six complete, ordered records and six
    // original physical-wait drops, including both root-stop cases;
    // this test's success alone does not establish the overlap.
}
