//! Ordinary synchronization with original v5 owners, never an application pump.
use super::*;

const VARIABLE: &str = "LSF_GO_SYNCHRONIZATION_FIXTURE";
const NEGATIVE: &str = "LSF_GO_SYNCHRONIZATION_NO_CHECKPOINT_FIXTURE";
const PROFILE: &str = "go-component-activation-v5";

fn observed(case: &str, iteration: u32, mode: u32, outcome: &str) {
    println!(
        "GO_SYNCHRONIZATION_CASE {}",
        serde_json::json!({"case": case, "iteration": iteration, "mode": mode, "outcome": outcome})
    );
}

#[tokio::test]
#[ignore = "requires pinned synchronization and no-checkpoint components and explicit go profile"]
async fn signed_condition_once_rwmutex_and_channel_ordering_retire_original_v5_owners() {
    assert_eq!(std::env::var("LSF_GUEST_SDK_LANGUAGE").as_deref(), Ok("go"));
    let root = tempfile::tempdir().unwrap();
    // Same finite ceiling as the existing v5 maintenance campaign: eight
    // prepaid maintenance slots plus original admitted application work.
    let f = prepare_owned_fixture(root.path(), VARIABLE, PROFILE, 16).await;
    for iteration in 0..3 {
        for mode in [0, 1, 2, 3, 4, 5, 6, 9] {
            let began = std::time::Instant::now();
            let receipt = success(
                f.manager
                    .start(f.request(&format!("go-sync-{iteration}-{mode}"), mode))
                    .unwrap()
                    .await,
            );
            assert_eq!(
                serde_json::from_slice::<Vec<u32>>(&receipt.output).unwrap(),
                [42]
            );
            assert!(receipt.consumption.cpu_fuel > 0);
            assert!(receipt.consumption.peak_memory_bytes <= packages::budget().memory_bytes);
            if mode == 6 {
                assert!(
                    began.elapsed() >= Duration::from_millis(30),
                    "accepted condition waiter was discarded before its real broadcast"
                );
            }
            eprintln!(
                "go-synchronization iteration={iteration} mode={mode} consumption={:?}",
                receipt.consumption
            );
            f.idle().await;
            assert_eq!(f.read_wait.active.load(Ordering::Acquire), 0);
            observed("ordinary", iteration, mode, "success");
        }
    }
    assert_eq!(
        failure(
            f.manager
                .start(f.request("go-sync-custom-condition-not-maintenance", 7))
                .unwrap()
                .await
        )
        .code,
        PlatformErrorCode::GuestTrap
    );
    f.idle().await;
    observed("blocked-condition", 0, 7, "guest-trap");
    assert_eq!(
        value(
            f.manager
                .start(f.request("go-sync-fresh-after-blocked-condition", 4))
                .unwrap()
                .await
        ),
        42
    );
    f.idle().await;
    observed("fresh-after-blocked", 0, 4, "success");

    let limited_root = tempfile::tempdir().unwrap();
    let limited = prepare_owned_fixture(limited_root.path(), VARIABLE, PROFILE, 10).await;
    assert_eq!(
        failure(
            limited
                .manager
                .start(limited.request("go-sync-original-task-capacity", 0))
                .unwrap()
                .await
        )
        .code,
        PlatformErrorCode::GuestTrap
    );
    limited.idle().await;
    observed("task-exhaustion", 0, 0, "guest-trap");

    let id = ActivationId("go-sync-cancel-original-condition-root".into());
    let mut invocation = Box::pin(f.manager.start(f.request(&id.0, 8)).unwrap());
    pending_timer(invocation.as_mut(), &f).await;
    f.manager
        .cancel_for(&TenantId("tenant-a".into()), &id, "go-sync-cancel")
        .unwrap();
    assert_eq!(failure(invocation.await).code, PlatformErrorCode::Cancelled);
    f.idle().await;
    observed("cancel-original-root", 0, 8, "cancelled");
    let mut deadline = f.request("go-sync-original-condition-deadline", 8);
    deadline.budget.wall_time_limit_millis = Some(100);
    assert_eq!(
        failure(f.manager.start(deadline).unwrap().await).code,
        PlatformErrorCode::DeadlineExceeded
    );
    f.idle().await;
    observed("deadline-original-root", 0, 8, "deadline-exceeded");
    assert_eq!(
        value(
            f.manager
                .start(f.request("go-sync-fresh-after-cancel-deadline", 4))
                .unwrap()
                .await
        ),
        42
    );
    f.idle().await;
    observed("fresh-after-cancel-deadline", 0, 4, "success");

    // The same source without compiler checkpoints must reach a real sibling
    // starvation boundary. A same-budget successful control excludes startup
    // failure; finite fuel contains the negative and is not progress evidence.
    let negative_root = tempfile::tempdir().unwrap();
    let negative = prepare_owned_fixture(
        negative_root.path(),
        NEGATIVE,
        "go-component-activation-v1",
        16,
    )
    .await;
    let mut baseline = negative.request("go-sync-negative-startup-control", 4);
    baseline.budget.cpu_fuel = 5_000_000;
    assert_eq!(value(negative.manager.start(baseline).unwrap().await), 42);
    negative.idle().await;
    observed("no-checkpoint-startup", 0, 4, "success");
    let mut blocked = negative.request("go-sync-no-checkpoint-cannot-progress", 9);
    blocked.budget.cpu_fuel = 5_000_000;
    assert_eq!(
        failure(negative.manager.start(blocked).unwrap().await).code,
        PlatformErrorCode::ResourceExhausted
    );
    negative.idle().await;
    observed("no-checkpoint-spin", 0, 9, "resource-exhausted");
    assert_eq!(
        value(
            negative
                .manager
                .start(negative.request("go-sync-negative-fresh-after-fuel", 4))
                .unwrap()
                .await
        ),
        42
    );
    negative.idle().await;
    observed("no-checkpoint-fresh", 0, 4, "success");
}
