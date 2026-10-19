//! Source-pinned runtime maintenance capacity in the original finite ledger.
use super::*;

const VARIABLE: &str = "LSF_GO_MANAGED_IDLE_FIXTURE";
const PROFILE: &str = "go-component-activation-v5";

#[tokio::test]
#[ignore = "requires pinned Go managed-idle fixture and explicit go profile"]
async fn signed_gc_workers_reserve_original_capacity_and_retire_only_after_application_drain() {
    assert_eq!(std::env::var("LSF_GUEST_SDK_LANGUAGE").as_deref(), Ok("go"));
    let root = tempfile::tempdir().unwrap();
    // Eight maintenance reservations plus bounded application work. This is
    // this opt-in test profile's ceiling, not a changed operator default.
    let f = prepare_owned_fixture(root.path(), VARIABLE, PROFILE, 16).await;
    for iteration in 0..3 {
        for mode in [0, 1, 2] {
            let began = std::time::Instant::now();
            let receipt = success(
                f.manager
                    .start(f.request(&format!("go-managed-{iteration}-{mode}"), mode))
                    .unwrap()
                    .await,
            );
            assert_eq!(
                serde_json::from_slice::<Vec<u32>>(&receipt.output).unwrap(),
                [42]
            );
            assert!(receipt.consumption.cpu_fuel > 0);
            assert!(receipt.consumption.peak_memory_bytes <= packages::budget().memory_bytes);
            if mode == 2 {
                assert!(
                    began.elapsed() >= Duration::from_millis(30),
                    "application sibling was falsely retired as runtime maintenance"
                );
            }
            eprintln!(
                "go-component-activation-v5 iteration={iteration} mode={mode} consumption={:?}",
                receipt.consumption
            );
            // Finalization also refuses a nonzero original runtime ledger.
            // idle() separately observes physical Store and backend retirement.
            f.idle().await;
        }
    }
    for mode in [4, 5, 6] {
        assert_eq!(
            failure(
                f.manager
                    .start(f.request(&format!("go-managed-reject-{mode}"), mode))
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
                    .start(f.request(&format!("go-managed-fresh-{mode}"), 0))
                    .unwrap()
                    .await
            ),
            42
        );
        f.idle().await;
    }
    let limited_root = tempfile::tempdir().unwrap();
    let limited = prepare_owned_fixture(limited_root.path(), VARIABLE, PROFILE, 7).await;
    assert_eq!(
        failure(
            limited
                .manager
                .start(limited.request("go-maintenance-preallocation-denied", 0))
                .unwrap()
                .await
        )
        .code,
        PlatformErrorCode::GuestTrap
    );
    limited.idle().await;

    let id = ActivationId("go-managed-cancel-original-root".into());
    let mut invocation = Box::pin(f.manager.start(f.request(&id.0, 3)).unwrap());
    pending_timer(invocation.as_mut(), &f).await;
    f.manager
        .cancel_for(&TenantId("tenant-a".into()), &id, "go-managed-cancel")
        .unwrap();
    assert_eq!(failure(invocation.await).code, PlatformErrorCode::Cancelled);
    f.idle().await;
    let mut request = f.request("go-managed-original-deadline", 3);
    request.budget.wall_time_limit_millis = Some(100);
    assert_eq!(
        failure(f.manager.start(request).unwrap().await).code,
        PlatformErrorCode::DeadlineExceeded
    );
    f.idle().await;
    assert_eq!(
        value(
            f.manager
                .start(f.request("go-managed-fresh-after-cancel-deadline", 0))
                .unwrap()
                .await
        ),
        42
    );
    f.idle().await;
}
