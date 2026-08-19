use super::errors::now_unix_millis;
use super::types::LeaseDisposition;
use super::{FixedCellPool, FixedCellPoolConfig};
use crate::{CellClass, CellPool};
use latent_core::{
    ActivationId, CellId, NodeId, PlatformErrorCode, ResourceBudget, TenantId,
};
use std::time::Duration;

fn pool(capacity: u32, queue_capacity: u32) -> FixedCellPool {
    FixedCellPool::new(FixedCellPoolConfig::new(
        NodeId("node-test".to_owned()),
        CellClass::Standard,
        capacity,
        queue_capacity,
    ))
    .expect("valid fixed pool")
}

fn budget(deadline: Option<u64>) -> ResourceBudget {
    ResourceBudget {
        cpu_fuel: 10_000,
        memory_bytes: 1_048_576,
        wall_deadline_unix_millis: deadline,
        child_calls: 0,
        outbound_requests: 0,
        state_read_bytes: 0,
        state_write_bytes: 0,
        blob_read_bytes: 0,
        blob_write_bytes: 0,
        log_bytes: 1_024,
        effect_count: 0,
    }
}

async fn acquire(
    pool: &FixedCellPool,
    activation: &str,
    deadline: Option<u64>,
) -> Result<crate::CellLease, latent_core::PlatformError> {
    let activation_id = ActivationId(activation.to_owned());
    let tenant = TenantId("tenant-test".to_owned());
    let budget = budget(deadline);
    pool.acquire(
        &activation_id,
        &tenant,
        CellClass::Standard,
        &budget,
    )
    .await
}

async fn wait_for_queue_depth(pool: &FixedCellPool, expected: u32) {
    for _ in 0..128 {
        if pool.observations().queue_depth == expected {
            return;
        }
        tokio::task::yield_now().await;
    }
    panic!("queue depth did not become {expected}");
}

async fn wait_for_settled(pool: &FixedCellPool) {
    for _ in 0..128 {
        let observations = pool.observations();
        if observations.queue_depth == 0 && observations.active_leases == 0 {
            return;
        }
        tokio::task::yield_now().await;
    }
    panic!("pool did not settle");
}

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
    let pool = pool(1, 1);
    let lease = acquire(&pool, "activation-owner", None)
        .await
        .expect("owner lease");
    let deadline = now_unix_millis().saturating_add(1_000);
    let waiter_pool = pool.clone();
    let waiter = tokio::spawn(async move {
        acquire(&waiter_pool, "activation-expired", Some(deadline)).await
    });
    wait_for_queue_depth(&pool, 1).await;

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
    let identity = lease
        .control
        .as_ref()
        .expect("managed lease")
        .identity
        .clone();

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
async fn cancelling_after_handoff_reclaims_an_unaccepted_grant() {
    let pool = pool(1, 1);
    let owner = acquire(&pool, "activation-owner", None)
        .await
        .expect("owner lease");
    let waiter_pool = pool.clone();
    let waiter = tokio::spawn(async move {
        acquire(&waiter_pool, "activation-unaccepted", None).await
    });
    wait_for_queue_depth(&pool, 1).await;

    pool.release(owner).await.expect("release owner");
    waiter.abort();
    let join_error = waiter.await.expect_err("waiter must be aborted");
    assert!(join_error.is_cancelled());
    wait_for_settled(&pool).await;

    let observations = pool.observations();
    assert_eq!(observations.capacity, 1);
    assert_eq!(observations.available, 1);
    assert_eq!(observations.active_leases, 0);
    assert_eq!(observations.quarantined, 0);
}

#[tokio::test(flavor = "current_thread")]
async fn task_cancellation_race_preserves_exact_capacity_accounting() {
    for iteration in 0..32 {
        let pool = pool(1, 1);
        let owner = acquire(&pool, &format!("owner-{iteration}"), None)
            .await
            .expect("owner lease");
        let waiter_pool = pool.clone();
        let waiter = tokio::spawn(async move {
            acquire(&waiter_pool, &format!("waiter-{iteration}"), None).await
        });
        wait_for_queue_depth(&pool, 1).await;

        pool.release(owner).await.expect("release owner");
        if iteration % 2 == 0 {
            tokio::task::yield_now().await;
        }
        waiter.abort();
        match waiter.await {
            Ok(Ok(lease)) => drop(lease),
            Ok(Err(error)) => assert_eq!(error.code, PlatformErrorCode::Cancelled),
            Err(join_error) => assert!(join_error.is_cancelled()),
        }
        wait_for_settled(&pool).await;

        let observations = pool.observations();
        assert_eq!(observations.capacity, 1);
        assert_eq!(observations.queue_depth, 0);
        assert_eq!(observations.active_leases, 0);
        assert_eq!(
            observations.available + observations.quarantined,
            observations.capacity
        );
    }
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
