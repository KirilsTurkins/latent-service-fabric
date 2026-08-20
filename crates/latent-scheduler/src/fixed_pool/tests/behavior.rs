use super::super::types::LeaseDisposition;
use super::support::{
    acquire, assert_exact_accounting, budget, pool, pool_with_clock, wait_for_queue_depth,
    wait_for_settled,
};
use crate::{CellClass, CellPool};
use latent_core::{ActivationId, CellId, PlatformErrorCode, TenantId};
use std::future::{poll_fn, Future};
use std::task::Poll;
use std::time::Duration;

#[tokio::test(flavor = "current_thread")]
async fn capacity_is_fixed_and_concurrent_acquisition_is_bounded() {
    let pool = pool(2, 2);
    let first = acquire(&pool, "activation-1", None)
        .await
        .expect("first lease");
    let second = acquire(&pool, "activation-2", None)
        .await
        .expect("second lease");
    let observations = pool.observations();
    assert_eq!(observations.capacity, 2);
    assert_eq!(observations.available, 0);
    assert_eq!(observations.active_leases, 2);

    let waiter_pool = pool.clone();
    let waiter = tokio::spawn(async move { acquire(&waiter_pool, "activation-3", None).await });
    wait_for_queue_depth(&pool, 1).await;
    assert_eq!(pool.observations().active_leases, 2);

    pool.release(first).await.expect("return first lease");
    let third = waiter.await.expect("waiter task").expect("third lease");
    let observations = pool.observations();
    assert_eq!(observations.capacity, 2);
    assert_eq!(observations.active_leases, 2);
    assert_eq!(observations.available, 0);

    pool.release(second).await.expect("return second lease");
    pool.release(third).await.expect("return third lease");
    let observations = pool.observations();
    assert_eq!(observations.capacity, 2);
    assert_eq!(observations.available, 2);
    assert_eq!(observations.active_leases, 0);
    assert_eq!(observations.quarantined, 0);
}

#[tokio::test(flavor = "current_thread")]
async fn bounded_queue_rejects_excess_work_deterministically() {
    let pool = pool(1, 1);
    let lease = acquire(&pool, "activation-owner", None)
        .await
        .expect("owner lease");
    let waiter_pool = pool.clone();
    let waiter = tokio::spawn(async move {
        acquire(&waiter_pool, "activation-waiting", None).await
    });
    wait_for_queue_depth(&pool, 1).await;

    let error = acquire(&pool, "activation-rejected", None)
        .await
        .expect_err("full queue must reject");
    assert_eq!(error.code, PlatformErrorCode::ResourceExhausted);
    assert_eq!(pool.observations().queue_depth, 1);

    pool.cancel_queued(&ActivationId("activation-waiting".to_owned()))
        .expect("cancel waiter");
    let cancellation = waiter
        .await
        .expect("waiter task")
        .expect_err("waiter cancelled");
    assert_eq!(cancellation.code, PlatformErrorCode::Cancelled);
    pool.release(lease).await.expect("return owner lease");
}

#[tokio::test(flavor = "current_thread")]
async fn cancelled_waiter_never_receives_a_later_lease() {
    let pool = pool(1, 1);
    let lease = acquire(&pool, "activation-owner", None)
        .await
        .expect("owner lease");
    let waiter_pool = pool.clone();
    let waiter = tokio::spawn(async move {
        acquire(&waiter_pool, "activation-cancelled", None).await
    });
    wait_for_queue_depth(&pool, 1).await;

    pool.cancel_queued(&ActivationId("activation-cancelled".to_owned()))
        .expect("cancel waiting activation");
    let error = waiter
        .await
        .expect("waiter task")
        .expect_err("cancelled waiter");
    assert_eq!(error.code, PlatformErrorCode::Cancelled);
    pool.release(lease).await.expect("return owner lease");

    let observations = pool.observations();
    assert_eq!(observations.available, 1);
    assert_eq!(observations.active_leases, 0);
    assert_eq!(observations.queue_depth, 0);
}

#[tokio::test(flavor = "current_thread", start_paused = true)]
async fn expired_waiter_never_receives_a_later_lease() {
    let (pool, clock) = pool_with_clock(1, 1, 25_000);
    let lease = acquire(&pool, "activation-owner", None)
        .await
        .expect("owner lease");
    let deadline = clock.now().saturating_add(1_000);
    let waiter_pool = pool.clone();
    let waiter = tokio::spawn(async move {
        acquire(&waiter_pool, "activation-expired", Some(deadline)).await
    });
    wait_for_queue_depth(&pool, 1).await;

    assert_eq!(clock.advance(1_001), deadline + 1);
    tokio::time::advance(Duration::from_millis(1_001)).await;
    let error = waiter
        .await
        .expect("waiter task")
        .expect_err("waiter must expire");
    assert_eq!(error.code, PlatformErrorCode::DeadlineExceeded);

    pool.release(lease).await.expect("return owner lease");
    let observations = pool.observations();
    assert_eq!(observations.available, 1);
    assert_eq!(observations.active_leases, 0);
    assert_eq!(observations.queue_depth, 0);
}

#[tokio::test(flavor = "current_thread")]
async fn dropping_a_live_lease_quarantines_its_cell() {
    let pool = pool(2, 0);
    let lease = acquire(&pool, "activation-dropped", None)
        .await
        .expect("lease");
    drop(lease);

    let observations = pool.observations();
    assert_eq!(observations.capacity, 2);
    assert_eq!(observations.available, 1);
    assert_eq!(observations.active_leases, 0);
    assert_eq!(observations.quarantined, 1);
}

#[tokio::test(flavor = "current_thread")]
async fn explicit_quarantine_removes_unsafe_capacity() {
    let pool = pool(1, 0);
    let lease = acquire(&pool, "activation-unsafe", None)
        .await
        .expect("lease");
    pool.quarantine_lease(lease, "backend reset failed")
        .expect("quarantine cell");

    let observations = pool.observations();
    assert_eq!(observations.capacity, 1);
    assert_eq!(observations.available, 0);
    assert_eq!(observations.active_leases, 0);
    assert_eq!(observations.quarantined, 1);
    let error = acquire(&pool, "activation-next", None)
        .await
        .expect_err("all quarantined pool is unavailable");
    assert_eq!(error.code, PlatformErrorCode::Unavailable);
}

#[tokio::test(flavor = "current_thread")]
async fn duplicate_activation_and_identity_mismatch_cannot_inflate_capacity() {
    let pool = pool(1, 0);
    let mut lease = acquire(&pool, "activation-original", None)
        .await
        .expect("lease");
    let duplicate = acquire(&pool, "activation-original", None)
        .await
        .expect_err("duplicate activation");
    assert_eq!(duplicate.code, PlatformErrorCode::AlreadyExists);

    lease.id = CellId("forged-cell".to_owned());
    let error = pool
        .release(lease)
        .await
        .expect_err("forged identity must fail");
    assert_eq!(error.code, PlatformErrorCode::InvalidArgument);
    let observations = pool.observations();
    assert_eq!(observations.capacity, 1);
    assert_eq!(observations.available, 0);
    assert_eq!(observations.active_leases, 0);
    assert_eq!(observations.quarantined, 1);
}

#[tokio::test(flavor = "current_thread")]
async fn foreign_pool_return_rejects_and_quarantines_the_original_cell() {
    let first = pool(1, 0);
    let second = pool(1, 0);
    let lease = acquire(&first, "activation-foreign", None)
        .await
        .expect("lease");

    let error = second
        .release(lease)
        .await
        .expect_err("foreign pool must reject the lease");
    assert_eq!(error.code, PlatformErrorCode::InvalidArgument);

    let first_observations = first.observations();
    assert_eq!(first_observations.active_leases, 0);
    assert_eq!(first_observations.available, 0);
    assert_eq!(first_observations.quarantined, 1);
    let second_observations = second.observations();
    assert_eq!(second_observations.active_leases, 0);
    assert_eq!(second_observations.available, 1);
    assert_eq!(second_observations.quarantined, 0);
}

#[tokio::test(flavor = "current_thread")]
async fn duplicate_return_cannot_inflate_available_capacity() {
    let pool = pool(1, 0);
    let lease = acquire(&pool, "activation-once", None)
        .await
        .expect("lease");
    let identity = {
        let state = pool
            .inner
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        state
            .active
            .get(&lease.activation_id)
            .expect("managed lease")
            .clone()
    };

    pool.inner
        .finish_lease(identity.clone(), LeaseDisposition::Reusable)
        .expect("first return");
    let error = pool
        .inner
        .finish_lease(identity, LeaseDisposition::Reusable)
        .expect_err("second return must fail");
    assert_eq!(error.code, PlatformErrorCode::NotFound);
    drop(lease);

    let observations = pool.observations();
    assert_eq!(observations.capacity, 1);
    assert_eq!(observations.available, 1);
    assert_eq!(observations.active_leases, 0);
    assert_eq!(observations.quarantined, 0);
}

#[tokio::test(flavor = "current_thread")]
async fn dropping_a_queued_acquisition_removes_it_before_any_release() {
    let pool = pool(1, 1);
    let owner = acquire(&pool, "activation-owner", None)
        .await
        .expect("owner lease");
    let activation_id = ActivationId("activation-dropped-waiter".to_owned());
    let tenant = TenantId("tenant-test".to_owned());
    let budget = budget(None);
    let mut waiter = Box::pin(pool.acquire(
        &activation_id,
        &tenant,
        CellClass::Standard,
        &budget,
    ));
    poll_fn(|context| {
        assert!(matches!(waiter.as_mut().poll(context), Poll::Pending));
        Poll::Ready(())
    })
    .await;
    assert_eq!(pool.observations().queue_depth, 1);

    drop(waiter);
    wait_for_queue_depth(&pool, 0).await;
    let queued_drop = pool.observations();
    assert_eq!(queued_drop.active_leases, 1);
    assert_eq!(queued_drop.available, 0);
    assert_exact_accounting(queued_drop);

    pool.release(owner).await.expect("release owner");
    let settled = pool.observations();
    assert_eq!(settled.queue_depth, 0);
    assert_eq!(settled.active_leases, 0);
    assert_eq!(settled.available, 1);
    assert_exact_accounting(settled);
}

#[tokio::test(flavor = "current_thread")]
async fn dropping_a_ready_waiter_reclaims_an_unaccepted_grant() {
    let pool = pool(1, 1);
    let owner = acquire(&pool, "activation-owner", None)
        .await
        .expect("owner lease");
    let activation_id = ActivationId("activation-unaccepted".to_owned());
    let tenant = TenantId("tenant-test".to_owned());
    let budget = budget(None);
    let mut waiter = Box::pin(pool.acquire(
        &activation_id,
        &tenant,
        CellClass::Standard,
        &budget,
    ));
    poll_fn(|context| {
        assert!(matches!(waiter.as_mut().poll(context), Poll::Pending));
        Poll::Ready(())
    })
    .await;
    assert_eq!(pool.observations().queue_depth, 1);

    pool.release(owner).await.expect("release owner");
    drop(waiter);
    wait_for_settled(&pool).await;

    let observations = pool.observations();
    assert_eq!(observations.capacity, 1);
    assert_eq!(observations.available, 1);
    assert_eq!(observations.active_leases, 0);
    assert_eq!(observations.quarantined, 0);
}

#[tokio::test(flavor = "current_thread")]
async fn quarantining_the_last_cell_fails_waiters_without_hanging() {
    let pool = pool(1, 1);
    let lease = acquire(&pool, "activation-owner", None)
        .await
        .expect("owner lease");
    let waiter_pool = pool.clone();
    let waiter = tokio::spawn(async move {
        acquire(&waiter_pool, "activation-waiting", None).await
    });
    wait_for_queue_depth(&pool, 1).await;

    pool.quarantine_lease(lease, "backend reset failed")
        .expect("quarantine final cell");
    let error = waiter
        .await
        .expect("waiter task")
        .expect_err("unserviceable waiter");
    assert_eq!(error.code, PlatformErrorCode::Unavailable);

    let observations = pool.observations();
    assert_eq!(observations.queue_depth, 0);
    assert_eq!(observations.active_leases, 0);
    assert_eq!(observations.quarantined, 1);
}

#[tokio::test(flavor = "current_thread")]
async fn unsupported_classes_report_zero_observed_capacity() {
    let pool = pool(1, 0);
    let observations = CellPool::observations(&pool, CellClass::Tiny);
    assert_eq!(observations.capacity, 0);
    assert_eq!(observations.available, 0);

    let activation_id = ActivationId("activation-tiny".to_owned());
    let tenant = TenantId("tenant-test".to_owned());
    let budget = budget(None);
    let error = pool
        .acquire(&activation_id, &tenant, CellClass::Tiny, &budget)
        .await
        .expect_err("unsupported class");
    assert_eq!(error.code, PlatformErrorCode::InvalidArgument);
}
