use std::sync::Arc;
use std::time::Duration;

use latent_core::{ActivationId, PlatformErrorCode};
use latent_scheduler::{ActivationScheduler, CellClass, SchedulingCancellation};

use super::support::{complete, failure, register, Cancellation, Fixture};

#[tokio::test(start_paused = true)]
async fn queued_cancellation_releases_quota_without_dispositioning_the_active_cell() {
    let fixture = Fixture::new(1, 4, Duration::from_secs(1));
    let scheduler = &fixture.scheduler;
    let held = complete(scheduler.enqueue(fixture.request("held", "a"))).await;
    let (request, token) = fixture.custom_request("cancelled", "b", 10, 5_000, 65_536);
    let mut queued = scheduler.enqueue(request);
    register(&mut queued);
    assert!(token.request_cancellation());
    assert!(!token.request_cancellation());
    assert_eq!(failure(queued).await, PlatformErrorCode::Cancelled);
    assert_eq!(scheduler.observations(CellClass::Tiny).queue_depth, 0);
    assert_eq!(scheduler.observations(CellClass::Tiny).active_leases, 1);
    assert_eq!(scheduler.observations(CellClass::Tiny).quarantined, 0);
    assert!(scheduler.observations(CellClass::Tiny).cancellations >= 1);
    assert_eq!(fixture.quotas.usage().unwrap().active_activations, 1);
    held.release().await.unwrap();
    fixture.assert_no_quota();
}

#[tokio::test(start_paused = true)]
async fn queued_request_expires_at_its_original_monotonic_deadline() {
    let fixture = Fixture::new(1, 4, Duration::from_secs(1));
    let scheduler = &fixture.scheduler;
    let held = complete(scheduler.enqueue(fixture.request("held", "a"))).await;
    let mut queued = scheduler.enqueue(fixture.custom_request("expired", "b", 10, 100, 65_536).0);
    register(&mut queued);
    tokio::time::advance(Duration::from_millis(100)).await;
    assert_eq!(failure(queued).await, PlatformErrorCode::DeadlineExceeded);
    assert_eq!(scheduler.observations(CellClass::Tiny).queue_depth, 0);
    assert!(scheduler.observations(CellClass::Tiny).expired >= 1);
    assert_eq!(fixture.quotas.usage().unwrap().queued_activations, 0);
    held.release().await.unwrap();
    fixture.assert_no_quota();
}

#[tokio::test(start_paused = true)]
async fn dropping_a_waiter_reclaims_its_queue_slot_without_quarantining_a_cell() {
    let fixture = Fixture::new(1, 1, Duration::from_secs(1));
    let scheduler = &fixture.scheduler;
    let held = complete(scheduler.enqueue(fixture.request("held", "a"))).await;
    let mut abandoned = scheduler.enqueue(fixture.request("abandoned", "b"));
    register(&mut abandoned);
    drop(abandoned);
    assert_eq!(scheduler.observations(CellClass::Tiny).queue_depth, 0);
    assert_eq!(scheduler.observations(CellClass::Tiny).quarantined, 0);
    assert_eq!(fixture.quotas.usage().unwrap().active_activations, 1);
    let mut replacement = scheduler.enqueue(fixture.request("replacement", "c"));
    register(&mut replacement);
    held.release().await.unwrap();
    complete(replacement).await.release().await.unwrap();
    fixture.assert_no_quota();
}

#[tokio::test(start_paused = true)]
async fn dropping_an_unaccepted_handoff_returns_a_reusable_cell() {
    let fixture = Fixture::new(1, 2, Duration::from_secs(1));
    let scheduler = &fixture.scheduler;
    let held = complete(scheduler.enqueue(fixture.request("held", "a"))).await;
    let mut abandoned = scheduler.enqueue(fixture.request("handoff-abandoned", "b"));
    register(&mut abandoned);
    let mut follower = scheduler.enqueue(fixture.request("follower", "c"));
    register(&mut follower);
    held.release().await.unwrap();
    // Polling the follower drives the shared pump, but the earlier tenant's
    // assignment remains inside its unpolled receiving future.
    register(&mut follower);
    assert_eq!(scheduler.observations(CellClass::Tiny).active_leases, 1);
    assert_eq!(scheduler.observations(CellClass::Tiny).queue_depth, 1);
    assert_eq!(fixture.quotas.usage().unwrap().queued_activations, 2);
    drop(abandoned);
    assert_eq!(scheduler.observations(CellClass::Tiny).quarantined, 0);
    assert_eq!(fixture.quotas.usage().unwrap().queued_activations, 1);
    let recovered = complete(follower).await;
    recovered.release().await.unwrap();
    assert_eq!(scheduler.observations(CellClass::Tiny).available, 1);
    fixture.assert_no_quota();
}

#[tokio::test(start_paused = true)]
async fn cancellation_and_deadline_win_before_a_ready_handoff_is_accepted() {
    for expire in [false, true] {
        let fixture = Fixture::new(1, 2, Duration::from_secs(1));
        let scheduler = &fixture.scheduler;
        let held = complete(scheduler.enqueue(fixture.request("held", "a"))).await;
        let (request, token) = fixture.custom_request("handoff", "b", 10, 100, 65_536);
        let mut queued = scheduler.enqueue(request);
        register(&mut queued);
        let mut follower = scheduler.enqueue(fixture.request("follower", "c"));
        register(&mut follower);
        held.release().await.unwrap();
        register(&mut follower);
        assert_eq!(scheduler.observations(CellClass::Tiny).active_leases, 1);
        assert_eq!(scheduler.observations(CellClass::Tiny).queue_depth, 1);
        assert_eq!(fixture.quotas.usage().unwrap().queued_activations, 2);
        if expire {
            tokio::time::advance(Duration::from_millis(100)).await;
        } else {
            token.request_cancellation();
        }
        assert_eq!(
            failure(queued).await,
            if expire {
                PlatformErrorCode::DeadlineExceeded
            } else {
                PlatformErrorCode::Cancelled
            }
        );
        assert_eq!(scheduler.observations(CellClass::Tiny).quarantined, 0);
        assert_eq!(
            scheduler.observations(CellClass::Tiny).cancellations,
            u64::from(!expire)
        );
        assert_eq!(
            scheduler.observations(CellClass::Tiny).expired,
            u64::from(expire)
        );
        complete(follower).await.release().await.unwrap();
        fixture.assert_no_quota();
    }
}

#[tokio::test(start_paused = true)]
async fn active_scheduler_cancellation_delegates_without_refunding_execution_early() {
    let fixture = Fixture::new(1, 2, Duration::from_secs(1));
    let scheduler = &fixture.scheduler;
    let (request, token) = fixture.custom_request("active", "a", 10, 5_000, 65_536);
    let activation = complete(scheduler.enqueue(request)).await;
    let id = ActivationId("active".to_owned());
    scheduler.cancel(&id).await.unwrap();
    scheduler.cancel(&id).await.unwrap();
    assert!(token.is_cancelled());
    assert!(activation.cancellation().is_cancelled());
    assert_eq!(scheduler.observations(CellClass::Tiny).cancellations, 1);
    assert_eq!(scheduler.observations(CellClass::Tiny).active_leases, 1);
    assert_eq!(fixture.quotas.usage().unwrap().active_activations, 1);
    assert_eq!(fixture.quotas.usage().unwrap().queued_activations, 0);
    activation.release().await.unwrap();
    assert_eq!(
        scheduler.cancel(&id).await.unwrap_err().code,
        PlatformErrorCode::NotFound
    );
    assert_eq!(scheduler.observations(CellClass::Tiny).available, 1);
    fixture.assert_no_quota();
}

#[tokio::test(start_paused = true)]
async fn quarantining_the_last_cell_settles_waiters_and_preserves_other_classes() {
    let fixture = Fixture::new(1, 2, Duration::from_secs(1));
    let scheduler = &fixture.scheduler;
    let active = complete(scheduler.enqueue(fixture.request("active", "a"))).await;
    let mut first = scheduler.enqueue(fixture.request("first", "b"));
    let mut second = scheduler.enqueue(fixture.request("second", "c"));
    register(&mut first);
    register(&mut second);
    active
        .quarantine("unrecoverable cell".to_owned())
        .await
        .unwrap();
    assert_eq!(failure(first).await, PlatformErrorCode::Unavailable);
    assert_eq!(failure(second).await, PlatformErrorCode::Unavailable);
    let snapshot = scheduler.observations(CellClass::Tiny);
    assert_eq!(snapshot.quarantined, 1);
    assert_eq!(snapshot.queue_depth, 0);
    assert_eq!(snapshot.queued_tenants, 0);
    let small = complete(
        scheduler.enqueue(
            fixture
                .custom_request("small-still-works", "a", 10, 5_000, 65_537)
                .0,
        ),
    )
    .await;
    assert_eq!(small.lease().class, CellClass::Small);
    small.release().await.unwrap();
    fixture.assert_no_quota();
}

#[tokio::test(start_paused = true)]
async fn shutdown_reclaims_a_ready_but_unaccepted_handoff_and_its_queued_follower() {
    let fixture = Fixture::new(1, 2, Duration::from_secs(1));
    let scheduler = &fixture.scheduler;
    let active = complete(scheduler.enqueue(fixture.request("active", "a"))).await;
    let mut handoff = scheduler.enqueue(fixture.request("handoff", "b"));
    let mut follower = scheduler.enqueue(fixture.request("follower", "c"));
    register(&mut handoff);
    register(&mut follower);
    active.release().await.unwrap();
    register(&mut follower);
    assert_eq!(scheduler.observations(CellClass::Tiny).active_leases, 1);
    assert_eq!(fixture.quotas.usage().unwrap().queued_activations, 2);
    scheduler.shutdown();
    assert_eq!(failure(handoff).await, PlatformErrorCode::Unavailable);
    assert_eq!(failure(follower).await, PlatformErrorCode::Unavailable);
    assert_eq!(scheduler.observations(CellClass::Tiny).available, 1);
    assert_eq!(scheduler.observations(CellClass::Tiny).quarantined, 0);
    fixture.assert_no_quota();
}

#[tokio::test(start_paused = true)]
async fn dropping_an_accepted_activation_quarantines_until_capacity_is_replaced() {
    let fixture = Fixture::new(1, 1, Duration::from_secs(1));
    let scheduler = &fixture.scheduler;
    let activation = complete(scheduler.enqueue(fixture.request("accepted", "a"))).await;
    drop(activation);
    assert_eq!(scheduler.observations(CellClass::Tiny).quarantined, 1);
    assert_eq!(scheduler.observations(CellClass::Tiny).available, 0);
    assert_eq!(scheduler.observations(CellClass::Tiny).active_leases, 0);
    fixture.assert_no_quota();
}

#[tokio::test(start_paused = true)]
async fn explicit_quarantine_disposes_the_cell_before_returning_the_execution_quota() {
    let fixture = Fixture::new(1, 1, Duration::from_secs(1));
    let activation = complete(
        fixture
            .scheduler
            .enqueue(fixture.request("quarantine", "a")),
    )
    .await;
    activation
        .quarantine("guest reset uncertain".to_owned())
        .await
        .unwrap();
    assert_eq!(
        fixture.scheduler.observations(CellClass::Tiny).quarantined,
        1
    );
    assert_eq!(
        fixture
            .scheduler
            .observations(CellClass::Tiny)
            .active_leases,
        0
    );
    fixture.assert_no_quota();
}

#[tokio::test(start_paused = true)]
async fn cancelled_mismatched_and_foreign_permits_fail_before_cell_assignment() {
    let fixture = Fixture::new(1, 2, Duration::from_secs(1));
    let scheduler = &fixture.scheduler;
    let (request, token) = fixture.custom_request("already-cancelled", "a", 10, 5_000, 65_536);
    token.request_cancellation();
    assert_eq!(
        failure(scheduler.enqueue(request)).await,
        PlatformErrorCode::Cancelled
    );
    let mut mismatched = fixture.request("expected-id", "a");
    mismatched.cancellation = Cancellation::new("different-id");
    let _ = failure(scheduler.enqueue(mismatched)).await;
    let foreign = Fixture::new(1, 2, Duration::from_secs(1));
    let _ = failure(scheduler.enqueue(foreign.request("foreign-ledger", "a"))).await;
    assert_eq!(scheduler.observations(CellClass::Tiny).available, 1);
    assert_eq!(scheduler.observations(CellClass::Tiny).granted, 0);
    fixture.assert_no_quota();
    foreign.assert_no_quota();
}

#[tokio::test(start_paused = true)]
async fn shutdown_drains_waiters_and_retains_the_active_execution_reservation() {
    let fixture = Fixture::new(1, 2, Duration::from_secs(1));
    let scheduler = &fixture.scheduler;
    let active = complete(scheduler.enqueue(fixture.request("active", "a"))).await;
    let mut queued = scheduler.enqueue(fixture.request("queued", "b"));
    register(&mut queued);
    scheduler.shutdown();
    assert_eq!(failure(queued).await, PlatformErrorCode::Unavailable);
    assert_eq!(scheduler.observations(CellClass::Tiny).queue_depth, 0);
    assert_eq!(scheduler.observations(CellClass::Tiny).active_leases, 1);
    assert_eq!(fixture.quotas.usage().unwrap().active_activations, 1);
    assert_eq!(
        failure(scheduler.enqueue(fixture.request("after-shutdown", "c"))).await,
        PlatformErrorCode::Unavailable
    );
    active.release().await.unwrap();
    fixture.assert_no_quota();
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn short_concurrent_churn_preserves_capacity_and_reclaims_all_tenants() {
    let fixture = Arc::new(Fixture::new(2, 32, Duration::from_millis(20)));
    tokio::time::timeout(Duration::from_secs(5), async {
        // Eight producers repeatedly enqueue after cleanup. Four small waves
        // exercise 128 total activations with at most eight live requests.
        for wave in 0..4_usize {
            let mut tasks = tokio::task::JoinSet::new();
            for worker in 0..8 {
                let fixture = fixture.clone();
                tasks.spawn(async move {
                    for cycle in 0..4 {
                        let index = wave * 32 + worker * 4 + cycle;
                        let tenant = ["a", "b", "c"][index % 3];
                        let request = fixture.request(&format!("churn-{index}"), tenant);
                        let activation = complete(fixture.scheduler.enqueue(request)).await;
                        assert_eq!(
                            activation.lease().activation_id,
                            *activation.permit().admission().activation_id()
                        );
                        assert!(
                            fixture
                                .scheduler
                                .observations(CellClass::Tiny)
                                .active_leases
                                <= 2
                        );
                        assert!(fixture.quotas.usage().unwrap().active_activations <= 8);
                        tokio::task::yield_now().await;
                        activation.release().await.unwrap();
                    }
                });
            }
            while let Some(result) = tasks.join_next().await {
                result.expect("churn task must complete");
            }
            let snapshot = fixture.scheduler.observations(CellClass::Tiny);
            assert_eq!(snapshot.capacity, 2);
            assert_eq!(snapshot.available, 2);
            assert_eq!(snapshot.active_leases, 0);
            assert_eq!(snapshot.quarantined, 0);
            assert_eq!(snapshot.queue_depth, 0);
            assert_eq!(snapshot.queued_tenants, 0);
            assert_eq!(snapshot.granted, u64::try_from((wave + 1) * 32).unwrap());
            assert_eq!(fixture.scheduler.observations(CellClass::Small).capacity, 1);
            assert_eq!(
                fixture.scheduler.observations(CellClass::Small).available,
                1
            );
            fixture.assert_no_quota();
        }
    })
    .await
    .expect("bounded churn must not hang");
}
