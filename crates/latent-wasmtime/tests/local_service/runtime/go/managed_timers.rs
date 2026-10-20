//! Original standard timer/GC semantics under prepaid managed-v5 ownership.
use super::*;

fn observed(case: &str, iteration: u32, mode: u32, outcome: &str) {
    println!(
        "GO_MANAGED_TIMER_CASE {}",
        serde_json::json!({"case":case,"iteration":iteration,"mode":mode,"outcome":outcome})
    );
}

#[tokio::test]
#[ignore = "requires the pinned ordinary Go timer source and explicit managed v5 profile"]
#[expect(
    clippy::too_many_lines,
    reason = "retain the complete original timer oracle and physical barriers in one scenario"
)]
async fn signed_managed_v5_timers_gc_callbacks_and_stop_reset_preserve_original_owners() {
    assert_eq!(std::env::var("LSF_GUEST_SDK_LANGUAGE").as_deref(), Ok("go"));
    let root = tempfile::tempdir().unwrap();
    let f = prepare_owned_fixture(
        root.path(),
        "LSF_GO_MANAGED_TIMER_FIXTURE",
        "go-component-activation-v5",
        16,
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
                    .start(f.request(&format!("go-v5-timers-{iteration}-{mode}"), mode))
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
                "go-component-activation-v5 iteration={iteration} mode={mode} consumption={:?}",
                receipt.consumption
            );
            f.idle().await;
            assert_eq!(f.read_wait.active.load(Ordering::Acquire), 0);
            observed("ordinary", iteration, mode, "success");
        }
        // Consume and reconcile every observation before the next finite batch.
        // The fixture keeps its original 32-entry telemetry bound.
        let expected = modes
            .into_iter()
            .map(|mode| format!("go-v5-timers-{iteration}-{mode}"))
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
        observed(
            if mode == 8 {
                "timer-capacity"
            } else {
                "callback-failure"
            },
            0,
            mode,
            "guest-trap",
        );
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
        observed(
            if mode == 8 {
                "fresh-after-timer-capacity"
            } else {
                "fresh-after-callback-failure"
            },
            0,
            0,
            "success",
        );
    }
    let id = ActivationId("go-cancel-standard-timer".into());
    let mut invocation = Box::pin(f.manager.start(f.request(&id.0, 7)).unwrap());
    pending_timer(invocation.as_mut(), &f).await;
    f.manager
        .cancel_for(&TenantId("tenant-a".into()), &id, "go-timer-cancel")
        .unwrap();
    assert_eq!(failure(invocation.await).code, PlatformErrorCode::Cancelled);
    f.idle().await;
    observed("cancel-original-root", 0, 7, "cancelled");
    let mut deadline = f.request("go-timer-original-root-deadline", 7);
    deadline.budget.wall_time_limit_millis = Some(100);
    assert_eq!(
        failure(f.manager.start(deadline).unwrap().await).code,
        PlatformErrorCode::DeadlineExceeded
    );
    f.idle().await;
    observed("deadline-original-root", 0, 7, "deadline-exceeded");
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
    observed("fresh-after-cancel-deadline", 0, 0, "success");
}
