//! One source-bound signed Go timer in a coherent diagnostic clock domain.
use super::*;
use latent_core::ActivationClock;
use std::{io::Write, sync::Arc};

#[tokio::test]
#[ignore = "requires the pinned zero-clock Go component and finite manual-clock fixture"]
async fn signed_zero_origin_five_nanosecond_timer_retires_original_wait() {
    assert_eq!(std::env::var("LSF_GUEST_SDK_LANGUAGE").as_deref(), Ok("go"));
    assert_eq!(
        std::env::var("LSF_GO_NODE_STOP_TIMER_OBSERVER").as_deref(),
        Ok("1")
    );
    let root = tempfile::tempdir().unwrap();
    let clock = Arc::new(super::super::super::fixture::zero_clock::ZeroClock::new());
    let f = prepare_owned_fixture_with_clock(
        root.path(),
        "LSF_GO_V7_ZERO_CLOCK_FIXTURE",
        "go-component-activation-v7",
        16,
        Some(clock.clone()),
    )
    .await;
    assert_eq!(clock.monotonic_now(), clock.origin());
    assert_eq!(clock.pending_waiters(), 0);
    let mut invocation = Box::pin(f.manager.start(f.request("node-stop-pending", 0)).unwrap());
    tokio::time::timeout(Duration::from_secs(15), async {
        tokio::select! {
            result = &mut invocation => panic!("activation exited before the real timer wait: {:?}", result.outcome),
            () = clock.target_pending() => {}
        }
    }).await.expect("real timer wait was not observed");
    assert_eq!(clock.monotonic_now(), clock.origin());
    assert_eq!(clock.pending_waiters(), 1);
    assert!(clock.target_live());
    assert_eq!(f.read_wait.active.load(Ordering::Acquire), 1);
    f.assert_single_cell_occupied_without_queue();
    writeln!(std::io::stderr().lock(), "LSF-GO-ZERO-CLOCK-V1|advance|0|5")
        .expect("write zero-clock advance witness");
    clock.advance(Duration::from_nanos(5));
    assert_eq!(
        clock.monotonic_now(),
        clock.origin() + Duration::from_nanos(5)
    );
    let result = tokio::time::timeout(Duration::from_secs(15), &mut invocation)
        .await
        .expect("timer did not complete after the shared clock advanced");
    let receipt = success(result);
    assert_eq!(
        serde_json::from_slice::<Vec<u32>>(&receipt.output).unwrap(),
        [42]
    );
    assert!(receipt.consumption.cpu_fuel > 0);
    assert!(receipt.consumption.peak_memory_bytes <= packages::budget().memory_bytes);
    f.idle().await;
    assert_eq!(clock.pending_waiters(), 0);
    assert!(!clock.target_live());
    assert_eq!(f.read_wait.active.load(Ordering::Acquire), 0);
    let state = f.backend.resource_snapshot();
    assert_eq!(state.stores_created, 1);
    assert_eq!(state.live_stores, 0);
    assert_eq!(state.live_component_instances, 0);
    assert_eq!(f.backend.active_instance_reservations(), 0);
    let quota = f.quotas.usage().unwrap();
    assert_eq!(quota.active_activations, 0);
    assert_eq!(quota.reserved_cpu_fuel, 0);
    assert_eq!(quota.reserved_memory_bytes, 0);
    println!(
        "GO_ZERO_CLOCK_CASE {}",
        serde_json::json!({
            "case":"zero-to-five-nanoseconds", "outcome":"success",
            "rawBefore":0, "rawAfter":5, "pendingOriginalWait":true,
            "liveStores":0, "liveInstances":0, "reservations":0,
            "reservedFuel":0, "reservedMemory":0, "pendingProviderWaits":0
        })
    );
}

#[tokio::test]
#[ignore = "requires the pinned zero-clock Go ticker and finite manual-clock fixture"]
async fn signed_zero_clock_ticker_coalesces_missed_periods() {
    assert_eq!(std::env::var("LSF_GUEST_SDK_LANGUAGE").as_deref(), Ok("go"));
    assert_eq!(
        std::env::var("LSF_GO_NODE_STOP_TIMER_OBSERVER").as_deref(),
        Ok("1")
    );
    let root = tempfile::tempdir().unwrap();
    let clock = Arc::new(super::super::super::fixture::zero_clock::ZeroClock::for_ticker());
    let f = prepare_owned_fixture_with_clock(
        root.path(),
        "LSF_GO_V7_ZERO_CLOCK_FIXTURE",
        "go-component-activation-v7",
        16,
        Some(clock.clone()),
    )
    .await;
    assert_eq!(clock.monotonic_now(), clock.origin());
    assert_eq!(clock.pending_waiters(), 0);
    let mut invocation = Box::pin(f.manager.start(f.request("node-stop-pending", 1)).unwrap());
    for (stage, before, after) in [(1, 0, 5), (2, 5, 29), (3, 29, 30)] {
        tokio::time::timeout(Duration::from_secs(15), async {
            tokio::select! {
                result = &mut invocation => panic!("activation exited before ticker wait: {:?}", result.outcome),
                () = clock.ticker_pending(stage) => {}
            }
        }).await.expect("real ticker wait was not observed");
        assert_eq!(
            clock.monotonic_now(),
            clock.origin() + Duration::from_nanos(before)
        );
        assert_eq!(clock.pending_waiters(), 1);
        assert!(clock.target_live());
        assert_eq!(f.read_wait.active.load(Ordering::Acquire), 1);
        f.assert_single_cell_occupied_without_queue();
        writeln!(
            std::io::stderr().lock(),
            "LSF-GO-TICKER-CLOCK-V1|advance|{before}|{after}"
        )
        .expect("write ticker advance witness");
        clock.advance(Duration::from_nanos(after - before));
    }
    let result = tokio::time::timeout(Duration::from_secs(15), &mut invocation)
        .await
        .expect("ticker did not complete after the next period");
    let receipt = success(result);
    assert_eq!(
        serde_json::from_slice::<Vec<u32>>(&receipt.output).unwrap(),
        [42]
    );
    assert!(receipt.consumption.cpu_fuel > 0);
    assert!(receipt.consumption.peak_memory_bytes <= packages::budget().memory_bytes);
    f.idle().await;
    assert_eq!(clock.pending_waiters(), 0);
    assert!(!clock.target_live());
    assert_eq!(f.read_wait.active.load(Ordering::Acquire), 0);
    let state = f.backend.resource_snapshot();
    assert_eq!(state.stores_created, 1);
    assert_eq!(state.live_stores, 0);
    assert_eq!(state.live_component_instances, 0);
    assert_eq!(f.backend.active_instance_reservations(), 0);
    let quota = f.quotas.usage().unwrap();
    assert_eq!(quota.active_activations, 0);
    assert_eq!(quota.reserved_cpu_fuel, 0);
    assert_eq!(quota.reserved_memory_bytes, 0);
    println!(
        "GO_TICKER_CATCHUP_CASE {}",
        serde_json::json!({
            "case":"zero-clock-ticker-coalescing", "outcome":"success",
            "pendingDeadlines":[5,10,30], "advances":[5,29,30], "nominalMissedPeriods":3,
            "liveStores":0, "liveInstances":0, "reservations":0, "reservedFuel":0,
            "reservedMemory":0, "pendingProviderWaits":0
        })
    );
}

#[tokio::test]
#[ignore = "requires the pinned zero-clock Go component and finite manual-clock fixture"]
async fn signed_zero_clock_timer_survives_wall_jumps() {
    assert_eq!(std::env::var("LSF_GUEST_SDK_LANGUAGE").as_deref(), Ok("go"));
    assert_eq!(
        std::env::var("LSF_GO_NODE_STOP_TIMER_OBSERVER").as_deref(),
        Ok("1")
    );
    let root = tempfile::tempdir().unwrap();
    let clock = Arc::new(super::super::super::fixture::zero_clock::ZeroClock::for_wall_jump());
    let f = prepare_owned_fixture_with_clock(
        root.path(),
        "LSF_GO_V7_ZERO_CLOCK_FIXTURE",
        "go-component-activation-v7",
        16,
        Some(clock.clone()),
    )
    .await;
    assert_eq!(clock.monotonic_now(), clock.origin());
    assert_eq!(clock.pending_waiters(), 0);
    let mut invocation = Box::pin(f.manager.start(f.request("node-stop-pending", 0)).unwrap());
    tokio::time::timeout(Duration::from_secs(15), async {
        tokio::select! {
            result = &mut invocation => panic!("activation exited before the real timer wait: {:?}", result.outcome),
            () = clock.target_pending() => {}
        }
    }).await.expect("real timer wait was not observed");
    for stage in 1..=2 {
        assert_eq!(clock.monotonic_now(), clock.origin());
        assert_eq!(clock.pending_waiters(), 1);
        assert!(clock.target_live());
        assert_eq!(f.read_wait.active.load(Ordering::Acquire), 1);
        f.assert_single_cell_occupied_without_queue();
        clock.jump_wall_and_wake(stage);
        tokio::time::timeout(Duration::from_secs(15), async {
            tokio::select! {
                result = &mut invocation => panic!("activation exited while the original wait was re-polled: {:?}", result.outcome),
                () = clock.wall_repolled(stage) => {}
            }
        }).await.expect("original wait was not re-polled after the wall jump");
        std::future::poll_fn(
            |cx| match std::future::Future::poll(invocation.as_mut(), cx) {
                std::task::Poll::Ready(result) => panic!(
                    "timer completed before monotonic advance: {:?}",
                    result.outcome
                ),
                std::task::Poll::Pending => std::task::Poll::Ready(()),
            },
        )
        .await;
        assert_eq!(clock.monotonic_now(), clock.origin());
        assert_eq!(clock.pending_waiters(), 1);
        assert!(clock.target_live());
        assert_eq!(f.read_wait.active.load(Ordering::Acquire), 1);
    }
    clock.restore_wall();
    writeln!(std::io::stderr().lock(), "LSF-GO-WALL-CLOCK-V1|advance|0|5")
        .expect("write wall-clock monotonic advance witness");
    clock.advance(Duration::from_nanos(5));
    assert_eq!(
        clock.monotonic_now(),
        clock.origin() + Duration::from_nanos(5)
    );
    let result = tokio::time::timeout(Duration::from_secs(15), &mut invocation)
        .await
        .expect("timer did not complete after the monotonic clock advanced");
    let receipt = success(result);
    assert_eq!(
        serde_json::from_slice::<Vec<u32>>(&receipt.output).unwrap(),
        [42]
    );
    assert!(receipt.consumption.cpu_fuel > 0);
    assert!(receipt.consumption.peak_memory_bytes <= packages::budget().memory_bytes);
    f.idle().await;
    assert_eq!(clock.pending_waiters(), 0);
    assert!(!clock.target_live());
    assert_eq!(f.read_wait.active.load(Ordering::Acquire), 0);
    let state = f.backend.resource_snapshot();
    assert_eq!(state.stores_created, 1);
    assert_eq!(state.live_stores, 0);
    assert_eq!(state.live_component_instances, 0);
    assert_eq!(f.backend.active_instance_reservations(), 0);
    let quota = f.quotas.usage().unwrap();
    assert_eq!(quota.active_activations, 0);
    assert_eq!(quota.reserved_cpu_fuel, 0);
    assert_eq!(quota.reserved_memory_bytes, 0);
    println!(
        "GO_WALL_CLOCK_CASE {}",
        serde_json::json!({
            "case":"pending-timer-wall-jumps", "outcome":"success",
            "wallOffsetsMillis":[60000,-60000], "monotonicBefore":0, "monotonicAfter":5,
            "sameWaitRepolls":2, "liveStores":0, "liveInstances":0, "reservations":0,
            "reservedFuel":0, "reservedMemory":0, "pendingProviderWaits":0
        })
    );
}

#[tokio::test]
#[ignore = "requires the pinned zero-clock Go component and finite manual-clock fixture"]
async fn signed_sleep_cancellation_precedes_elapsed_edge() {
    assert_eq!(std::env::var("LSF_GUEST_SDK_LANGUAGE").as_deref(), Ok("go"));
    assert_eq!(
        std::env::var("LSF_GO_NODE_STOP_TIMER_OBSERVER").as_deref(),
        Ok("1")
    );
    let root = tempfile::tempdir().unwrap();
    let clock = Arc::new(super::super::super::fixture::zero_clock::ZeroClock::new());
    let f = prepare_owned_fixture_with_clock(
        root.path(),
        "LSF_GO_V7_ZERO_CLOCK_FIXTURE",
        "go-component-activation-v7",
        16,
        Some(clock.clone()),
    )
    .await;
    let id = ActivationId("node-stop-pending".into());
    let mut invocation = Box::pin(f.manager.start(f.request(&id.0, 2)).unwrap());
    tokio::time::timeout(Duration::from_secs(15), async {
        tokio::select! {
            result = &mut invocation => panic!("activation exited before the original sleep wait: {:?}", result.outcome),
            () = clock.target_pending() => {}
        }
    }).await.expect("sleep wait was not observed pending");
    assert_eq!(clock.monotonic_now(), clock.origin());
    assert!(clock.target_live());
    assert_eq!(clock.pending_waiters(), 1);
    assert_eq!(f.read_wait.active.load(Ordering::Acquire), 1);
    f.assert_single_cell_occupied_without_queue();
    writeln!(
        std::io::stderr().lock(),
        "LSF-GO-SLEEP-CANCEL-V1|pending|0|5"
    )
    .expect("write pending sleep witness");
    assert_eq!(
        f.manager
            .cancel_for(&TenantId("tenant-a".into()), &id, "go-sleep-cancel")
            .unwrap(),
        latent_core::CancelDisposition::Accepted
    );
    // Cancellation can retire the original wait immediately. Do not require it
    // to remain live while this test advances the controlled clock.
    assert_eq!(clock.monotonic_now(), clock.origin());
    writeln!(
        std::io::stderr().lock(),
        "LSF-GO-SLEEP-CANCEL-V1|accepted|0|5"
    )
    .expect("write accepted cancellation witness");
    writeln!(
        std::io::stderr().lock(),
        "LSF-GO-SLEEP-CANCEL-V1|advance|0|5"
    )
    .expect("write monotonic advance witness");
    clock.advance(Duration::from_nanos(5));
    let receipt = tokio::time::timeout(Duration::from_secs(15), &mut invocation)
        .await
        .expect("cancelled sleep did not settle");
    assert_eq!(failure(receipt).code, PlatformErrorCode::Cancelled);
    f.idle().await;
    assert_eq!(clock.pending_waiters(), 0);
    assert!(!clock.target_live());
    assert_eq!(f.read_wait.active.load(Ordering::Acquire), 0);
    let state = f.backend.resource_snapshot();
    assert_eq!(state.stores_created, 1);
    assert_eq!(state.live_stores, 0);
    assert_eq!(state.live_component_instances, 0);
    assert_eq!(f.backend.active_instance_reservations(), 0);
    let quota = f.quotas.usage().unwrap();
    assert_eq!(quota.active_activations, 0);
    assert_eq!(quota.reserved_cpu_fuel, 0);
    assert_eq!(quota.reserved_memory_bytes, 0);
    writeln!(
        std::io::stderr().lock(),
        "LSF-GO-SLEEP-CANCEL-V1|retired|5|0"
    )
    .expect("write original retirement witness");
    let fresh = tokio::time::timeout(
        Duration::from_secs(15),
        f.manager
            .start(f.request("go-sleep-cancel-fresh", 3))
            .unwrap(),
    )
    .await
    .expect("fresh activation did not finish");
    assert_eq!(value(fresh), 42);
    f.idle().await;
    assert_eq!(f.read_wait.active.load(Ordering::Acquire), 0);
    let state = f.backend.resource_snapshot();
    assert_eq!(state.stores_created, 2);
    assert_eq!(state.live_stores, 0);
    assert_eq!(state.live_component_instances, 0);
    assert_eq!(f.backend.active_instance_reservations(), 0);
    let quota = f.quotas.usage().unwrap();
    assert_eq!(quota.active_activations, 0);
    assert_eq!(quota.reserved_cpu_fuel, 0);
    assert_eq!(quota.reserved_memory_bytes, 0);
    writeln!(std::io::stderr().lock(), "LSF-GO-SLEEP-CANCEL-V1|fresh|5|0")
        .expect("write fresh activation witness");
    println!(
        "GO_SLEEP_CANCEL_CASE {}",
        serde_json::json!({
            "case":"accepted-before-sleep-edge", "outcome":"cancelled", "fresh":"success",
            "monotonicAtCancel":0, "monotonicAfter":5, "pendingOriginalWait":true,
            "liveStores":0, "liveInstances":0, "reservations":0,
            "reservedFuel":0, "reservedMemory":0, "pendingProviderWaits":0
        })
    );
}
