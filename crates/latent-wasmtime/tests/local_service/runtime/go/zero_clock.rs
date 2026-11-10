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
