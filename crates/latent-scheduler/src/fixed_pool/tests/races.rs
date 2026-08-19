use super::support::{
    acquire, assert_exact_accounting, pool, wait_for_queue_depth, wait_for_settled,
};
use crate::CellPool;
use latent_core::{ActivationId, PlatformErrorCode};
use std::sync::Arc;
use tokio::sync::Barrier;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn release_and_explicit_cancellation_race_is_linearizable() {
    for iteration in 0..64 {
        let pool = pool(1, 1);
        let owner = acquire(&pool, &format!("owner-explicit-{iteration}"), None)
            .await
            .expect("owner lease");
        let waiter_name = format!("waiter-explicit-{iteration}");
        let waiter_activation = ActivationId(waiter_name.clone());
        let waiter_pool = pool.clone();
        let waiter = tokio::spawn(async move { acquire(&waiter_pool, &waiter_name, None).await });
        wait_for_queue_depth(&pool, 1).await;

        let barrier = Arc::new(Barrier::new(3));
        let release_pool = pool.clone();
        let release_barrier = barrier.clone();
        let release = tokio::spawn(async move {
            release_barrier.wait().await;
            release_pool.release(owner).await
        });
        let cancel_pool = pool.clone();
        let cancel_barrier = barrier.clone();
        let cancel = tokio::spawn(async move {
            cancel_barrier.wait().await;
            cancel_pool.cancel_queued(&waiter_activation)
        });

        barrier.wait().await;
        release
            .await
            .expect("release task")
            .expect("release owner");
        let cancel_result = cancel.await.expect("cancel task");
        let waiter_result = waiter.await.expect("waiter task");
        match (cancel_result, waiter_result) {
            (Ok(()), Err(error)) => {
                assert_eq!(error.code, PlatformErrorCode::Cancelled);
            }
            (Err(error), Ok(lease)) => {
                assert_eq!(error.code, PlatformErrorCode::NotFound);
                pool.release(lease).await.expect("release winning grant");
            }
            (cancel_result, waiter_result) => {
                panic!(
                    "non-linearizable cancellation result: {cancel_result:?}, waiter: {waiter_result:?}"
                );
            }
        }

        wait_for_settled(&pool).await;
        let observations = pool.observations();
        assert_eq!(observations.queue_depth, 0);
        assert_exact_accounting(observations);
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn release_and_task_abort_race_preserves_exact_capacity_accounting() {
    for iteration in 0..64 {
        let pool = pool(1, 1);
        let owner = acquire(&pool, &format!("owner-abort-{iteration}"), None)
            .await
            .expect("owner lease");
        let waiter_pool = pool.clone();
        let waiter = tokio::spawn(async move {
            acquire(&waiter_pool, &format!("waiter-abort-{iteration}"), None).await
        });
        wait_for_queue_depth(&pool, 1).await;

        let abort_handle = waiter.abort_handle();
        let barrier = Arc::new(Barrier::new(3));
        let release_pool = pool.clone();
        let release_barrier = barrier.clone();
        let release = tokio::spawn(async move {
            release_barrier.wait().await;
            release_pool.release(owner).await
        });
        let abort_barrier = barrier.clone();
        let abort = tokio::spawn(async move {
            abort_barrier.wait().await;
            abort_handle.abort();
        });

        barrier.wait().await;
        release
            .await
            .expect("release task")
            .expect("release owner");
        abort.await.expect("abort task");
        match waiter.await {
            Ok(Ok(lease)) => pool.release(lease).await.expect("release winning grant"),
            Ok(Err(error)) => assert_eq!(error.code, PlatformErrorCode::Cancelled),
            Err(join_error) => assert!(join_error.is_cancelled()),
        }
        wait_for_settled(&pool).await;

        let observations = pool.observations();
        assert_eq!(observations.queue_depth, 0);
        assert_exact_accounting(observations);
    }
}

#[tokio::test(flavor = "current_thread")]
async fn lease_token_exhaustion_quarantines_the_slot_and_fails_all_waiters() {
    let pool = pool(1, 2);
    let owner = acquire(&pool, "activation-owner", None)
        .await
        .expect("owner lease");
    {
        let mut state = pool
            .inner
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        state.next_lease_token = u64::MAX;
    }

    let first_pool = pool.clone();
    let first = tokio::spawn(async move {
        acquire(&first_pool, "activation-waiting-1", None).await
    });
    let second_pool = pool.clone();
    let second = tokio::spawn(async move {
        acquire(&second_pool, "activation-waiting-2", None).await
    });
    wait_for_queue_depth(&pool, 2).await;

    pool.release(owner).await.expect("release owner");
    for waiter in [first, second] {
        let error = waiter
            .await
            .expect("waiter task")
            .expect_err("token exhaustion must fail every waiter");
        assert_eq!(error.code, PlatformErrorCode::Internal);
    }

    let observations = pool.observations();
    assert_eq!(observations.available, 0);
    assert_eq!(observations.active_leases, 0);
    assert_eq!(observations.quarantined, 1);
    assert_eq!(observations.queue_depth, 0);
    assert_exact_accounting(observations);
}
