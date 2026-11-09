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

#[tokio::test]
#[ignore = "requires the selected v7 diagnostic overlay and original pending timer witness"]
async fn signed_fired_one_shot_public_stop_and_reset_wait_for_original_next() {
    assert!(cfg!(feature = "development-go-timer-overlap"));
    assert_eq!(std::env::var("LSF_GUEST_SDK_LANGUAGE").as_deref(), Ok("go"));
    let root = tempfile::tempdir().unwrap();
    // Keep the existing Task16 / Queue16 / Wait4 / Timer2 envelope.
    let f = prepare_owned_fixture(
        root.path(),
        "LSF_GO_V7_TIMER_FIRED_FIXTURE",
        "go-component-activation-v7",
        16,
    )
    .await;
    let mut publication = None;
    for (case, id, mode, created) in [
        ("stop", "go-timer-fired-stop", 0, 1),
        ("reset", "go-timer-fired-reset", 1, 2),
        ("returned-stop", "go-timer-returned-stop", 2, 3),
        ("returned-reset", "go-timer-returned-reset", 3, 4),
        ("returned-cancel", "go-timer-returned-cancel", 4, 5),
        ("fresh", "go-timer-fired-fresh", 0, 6),
    ] {
        // The future is owned by this test, with no detached invocation. Once
        // the exact witness gate is ready, do not poll it again until the real
        // tenant-authorized cancellation has been synchronously accepted.
        let gate = (mode == 4).then(|| {
            latent_wasmtime::ReturnedCancellationGate::arm().expect("exclusive cancellation gate")
        });
        let mut invocation = Box::pin(f.manager.start(f.request(id, mode)).unwrap());
        if let Some(gate) = &gate {
            // Inspect the gate immediately after each invocation poll. A
            // ready event must not be lost to select's randomized re-polling.
            let boundary = std::future::poll_fn(|cx| {
                assert!(!gate.failed(), "returned-event cancellation gate failed");
                if gate.ready() {
                    return std::task::Poll::Ready(());
                }
                match std::future::Future::poll(invocation.as_mut(), cx) {
                    std::task::Poll::Ready(result) => {
                        panic!("root ended before cancellation: {:?}", result.outcome)
                    }
                    std::task::Poll::Pending => {
                        assert!(!gate.failed(), "returned-event cancellation gate failed");
                        if gate.ready() {
                            std::task::Poll::Ready(())
                        } else {
                            std::task::Poll::Pending
                        }
                    }
                }
            });
            tokio::time::timeout(Duration::from_secs(5), boundary)
                .await
                .expect("bounded returned-event cancellation gate");
            assert!(gate.claim(), "claim the still-held event");
            assert_eq!(
                f.manager
                    .cancel_for(
                        &TenantId("tenant-a".into()),
                        &ActivationId(id.into()),
                        "returned-timer-cancel"
                    )
                    .unwrap(),
                latent_core::CancelDisposition::Accepted
            );
            assert!(
                gate.accepted(),
                "the held event must survive until cancellation is accepted"
            );
        }
        let result = invocation.await;
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
        let outcome = if mode == 4 {
            assert_eq!(failure(result).code, PlatformErrorCode::Cancelled);
            "cancelled"
        } else {
            let receipt = success(result);
            assert_eq!(
                serde_json::from_slice::<Vec<u32>>(&receipt.output).unwrap(),
                [42]
            );
            assert!(receipt.consumption.cpu_fuel > 0);
            assert!(receipt.consumption.peak_memory_bytes <= packages::budget().memory_bytes);
            "success"
        };
        f.idle().await;
        if let Some(gate) = &gate {
            assert!(
                gate.completed(),
                "cancelled returned-event witness must finish"
            );
        }
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
            "GO_TIMER_FIRED_CASE {}",
            serde_json::json!({"case":case,"mode":mode,"outcome":outcome,
            "storesCreated":created,"liveStores":0,"liveInstances":0,"reservations":0,"reservedFuel":0,
            "reservedMemory":0,"pendingProviderWaits":0})
        );
    }
    // The owner separately requires exact pre-drop probe and physical-drop
    // records. Successful output alone cannot establish the interleaving.
}
