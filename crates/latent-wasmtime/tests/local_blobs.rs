//! Actual async guest calls into a bounded durable Linux blob provider.
#![cfg(target_os = "linux")]
#[path = "local_blobs/component.rs"]
mod component;
#[path = "local_blobs/fixture.rs"]
mod fixture;
#[path = "local_blobs/packages.rs"]
mod packages;
#[path = "generic_backend/support.rs"]
#[allow(dead_code)]
mod support;
use fixture::*;

#[tokio::test]
async fn guest_writes_seals_and_reads_exact_bounded_chunks() {
    let f = Fixture::new().await;
    for mode in [0, 9, 0] {
        let (request, control) = f.request("blob-guest", mode, 0);
        let report = f.backend.invoke_contained(request, &control).await;
        let outcome = report.outcome.unwrap();
        let GuestOutcome::Returned {
            output,
            consumption,
            ..
        } = outcome
        else {
            panic!("unexpected blob outcome: {outcome:?}")
        };
        assert_eq!(
            serde_json::from_slice::<serde_json::Value>(&output).unwrap(),
            serde_json::json!([if mode == 9 { "0" } else { "4101" }])
        );
        let final_budget = control
            .budget
            .finalize_at(Some(&consumption), Instant::now());
        assert!(final_budget.violation().is_none());
        assert_eq!(
            final_budget.consumption().blob_write_bytes,
            if mode == 9 { 0 } else { 8 }
        );
        assert_eq!(
            final_budget.consumption().blob_read_bytes,
            if mode == 9 { 0 } else { 4 }
        );
        assert_eq!(report.cleanup, ExecutionCleanup::Reusable);
        f.idle();
        assert_eq!(
            f.io.snapshot(),
            latent_capabilities::broker::io::IoSnapshot::default()
        );
        assert_eq!(f.provider.store().snapshot().unwrap().handles, 0);
        f.provider.store().reclaim(64, &|| Ok(())).unwrap();
    }
    assert!(f
        .pools
        .shutdown(Instant::now() + Duration::from_secs(2))
        .await
        .unwrap()
        .is_clean());
}

#[tokio::test]
async fn guest_handle_abandonment_wrong_kind_and_trap_reclaim_actual_owners() {
    let f = Fixture::new().await;
    for mode in [1, 2, 5, 7, 8] {
        let (request, control) = f.request("blob-errors", mode, 0);
        let report = f.backend.invoke_contained(request, &control).await;
        match report.outcome.unwrap() {
            GuestOutcome::Returned { output, .. } => assert_eq!(
                serde_json::from_slice::<serde_json::Value>(&output).unwrap(),
                serde_json::json!([if mode == 5 { "5555" } else { "0" }])
            ),
            GuestOutcome::Trapped { .. } => assert!([2, 7, 8].contains(&mode)),
            other => panic!("unexpected outcome {other:?}"),
        }
        assert_eq!(report.cleanup, ExecutionCleanup::Reusable);
        f.idle();
        assert_eq!(f.provider.store().snapshot().unwrap().handles, 0);
        f.provider.store().reclaim(64, &|| Ok(())).unwrap();
    }
    assert!(f
        .pools
        .shutdown(Instant::now() + Duration::from_secs(2))
        .await
        .unwrap()
        .is_clean());
}

#[tokio::test]
async fn a_previous_activation_numeric_handle_cannot_be_reused() {
    let f = Fixture::new().await;
    let (request, control) = f.request("identical-public-activation-id", 3, 0);
    let report = f.backend.invoke_contained(request, &control).await;
    let GuestOutcome::Returned { output, .. } = report.outcome.unwrap() else {
        panic!("create handle")
    };
    let handle = serde_json::from_slice::<Vec<String>>(&output).unwrap()[0]
        .parse::<u64>()
        .unwrap();
    assert_ne!(handle, 0);
    f.idle();
    let (request, control) = f.request("identical-public-activation-id", 4, handle);
    let report = f.backend.invoke_contained(request, &control).await;
    let GuestOutcome::Returned { output, .. } = report.outcome.unwrap() else {
        panic!("foreign handle rejection")
    };
    assert_eq!(
        serde_json::from_slice::<Vec<String>>(&output).unwrap(),
        ["4444"]
    );
    f.idle();
    assert_eq!(
        f.provider.store().reclaim(64, &|| Ok(())).unwrap().stages,
        1
    );
    assert!(f
        .pools
        .shutdown(Instant::now() + Duration::from_secs(2))
        .await
        .unwrap()
        .is_clean());
}

#[tokio::test]
async fn dormant_blob_deployments_allocate_no_store_provider_work_or_file_handles() {
    let f = Fixture::new().await;
    let before = f.provider.store().snapshot().unwrap();
    f.dormant_deployments().await;
    assert_eq!(f.provider.store().snapshot().unwrap(), before);
    assert!(f
        .pools
        .shutdown(Instant::now() + Duration::from_secs(2))
        .await
        .unwrap()
        .is_clean());
}

#[path = "local_blobs/provider.rs"]
mod provider;
