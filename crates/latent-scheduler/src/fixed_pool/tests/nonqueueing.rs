use std::future::Future;
use std::sync::{Arc, Barrier};
use std::task::{Context, Poll, Waker};
use std::time::Duration;

use latent_core::{ActivationId, PlatformError, PlatformErrorCode, TenantId};

use super::super::types::PendingGrant;
use super::super::FixedCellPool;
use super::support::{acquire, assert_exact_accounting, budget, pool, pool_with_clock};
use crate::{CellClass, CellLease, CellPool};

fn try_acquire(pool: &FixedCellPool, activation: &str) -> Result<Option<CellLease>, PlatformError> {
    pool.try_acquire_now(
        &ActivationId(activation.to_owned()),
        &TenantId("tenant-test".to_owned()),
        CellClass::Standard,
        &budget(None),
        None,
    )
}

#[tokio::test]
async fn nonqueueing_acquisition_never_registers_or_allocates_a_waiter() {
    let pool = pool(1, 0);
    let owner = try_acquire(&pool, "owner").unwrap().unwrap();
    assert_eq!(
        try_acquire(&pool, "owner").unwrap_err().code,
        PlatformErrorCode::AlreadyExists
    );
    for index in 0..32 {
        assert!(try_acquire(&pool, &format!("busy-{index}"))
            .unwrap()
            .is_none());
    }
    {
        let state = pool.inner.state.lock().unwrap();
        assert!(state.waiters.is_empty());
        assert_eq!(state.waiters.capacity(), 0);
        assert!(state.waiting_by_activation.is_empty());
        assert_eq!(state.next_waiter_id, 1);
    }
    pool.release(owner).await.unwrap();
    let next = try_acquire(&pool, "after-release").unwrap().unwrap();
    pool.release(next).await.unwrap();
    assert_eq!(pool.observations().available, 1);
    assert_exact_accounting(pool.observations());
}

#[tokio::test]
async fn nonqueueing_acquisition_preserves_legacy_fifo_handoff() {
    let pool = pool(1, 1);
    let owner = try_acquire(&pool, "owner").unwrap().unwrap();
    let mut queued = Box::pin(acquire(&pool, "legacy-waiter", None));
    let mut context = Context::from_waker(Waker::noop());
    assert!(matches!(queued.as_mut().poll(&mut context), Poll::Pending));
    assert_eq!(pool.observations().queue_depth, 1);
    assert!(try_acquire(&pool, "new-arrival").unwrap().is_none());
    assert_eq!(
        try_acquire(&pool, "legacy-waiter").unwrap_err().code,
        PlatformErrorCode::AlreadyExists
    );
    pool.release(owner).await.unwrap();
    // The granted-but-unpolled FIFO receiver still owns the assignment.
    assert!(try_acquire(&pool, "new-arrival").unwrap().is_none());
    let legacy = queued.await.unwrap();
    pool.release(legacy).await.unwrap();
    let next = try_acquire(&pool, "new-arrival").unwrap().unwrap();
    pool.release(next).await.unwrap();
    assert_exact_accounting(pool.observations());
}

#[tokio::test]
async fn change_subscription_catches_release_between_failed_probe_and_wait() {
    let pool = pool(1, 0);
    let pool_port: &dyn CellPool = &pool;
    let mut changes = pool_port.subscribe_changes().unwrap();
    let owner = pool_port
        .try_acquire_now(
            &ActivationId("owner".to_owned()),
            &TenantId("tenant-test".to_owned()),
            CellClass::Standard,
            &budget(None),
            None,
        )
        .unwrap()
        .unwrap();
    assert!(try_acquire(&pool, "waiting").unwrap().is_none());
    pool.release(owner).await.unwrap();
    tokio::time::timeout(Duration::from_secs(1), changes.changed())
        .await
        .expect("release before waiting must remain observable")
        .unwrap();
    let next = try_acquire(&pool, "waiting").unwrap().unwrap();
    pool.release(next).await.unwrap();
}

#[tokio::test]
async fn change_notifications_coalesce_without_losing_the_latest_capacity() {
    let pool = pool(1, 0);
    let mut changes = pool.subscribe_changes();
    for _ in 0..32 {
        let lease = try_acquire(&pool, "reuse").unwrap().unwrap();
        pool.release(lease).await.unwrap();
    }
    assert!(changes.has_changed().unwrap());
    assert_eq!(*changes.borrow_and_update(), 32);
    assert!(!changes.has_changed().unwrap());
    assert_eq!(pool.observations().available, 1);
    assert_eq!(pool.observations().queue_depth, 0);
    assert_exact_accounting(pool.observations());
}

#[test]
fn unaccepted_abandoned_and_quarantined_leases_notify_production_observers() {
    let pool = pool(2, 0);
    let mut changes = pool.subscribe_changes();
    let unaccepted = try_acquire(&pool, "unaccepted").unwrap().unwrap();
    drop(PendingGrant::new(unaccepted));
    assert!(changes.has_changed().unwrap());
    assert_eq!(pool.observations().available, 2);
    changes.borrow_and_update();

    let abandoned = try_acquire(&pool, "abandoned").unwrap().unwrap();
    drop(abandoned);
    assert!(changes.has_changed().unwrap());
    assert_eq!(pool.observations().quarantined, 1);
    changes.borrow_and_update();

    let unsafe_lease = try_acquire(&pool, "unsafe").unwrap().unwrap();
    pool.quarantine_lease(unsafe_lease, "cleanup not proven")
        .unwrap();
    assert!(changes.has_changed().unwrap());
    assert_eq!(pool.observations().quarantined, 2);
    let error = try_acquire(&pool, "cannot-wait-forever").unwrap_err();
    assert_eq!(error.code, PlatformErrorCode::Unavailable);
    assert_eq!(error.details[0].kind, "cell-pool.all-quarantined");
    assert_exact_accounting(pool.observations());
}

#[tokio::test]
async fn token_exhaustion_notifies_for_nonqueueing_and_legacy_acquisition() {
    for legacy in [false, true] {
        let pool = pool(1, 0);
        let mut changes = pool.subscribe_changes();
        pool.inner.state.lock().unwrap().next_lease_token = u64::MAX;
        let error = if legacy {
            acquire(&pool, "exhausted", None).await.unwrap_err()
        } else {
            try_acquire(&pool, "exhausted").unwrap_err()
        };
        assert_eq!(error.code, PlatformErrorCode::Internal);
        assert!(changes.has_changed().unwrap());
        assert_eq!(*changes.borrow_and_update(), 1);
        assert_eq!(pool.observations().available, 0);
        assert_eq!(pool.observations().quarantined, 1);
        assert_exact_accounting(pool.observations());
    }
}

#[tokio::test]
async fn cell_generation_exhaustion_publishes_the_unusable_capacity_transition() {
    let pool = pool(1, 0);
    let mut changes = pool.subscribe_changes();
    pool.inner
        .state
        .lock()
        .unwrap()
        .idle
        .front_mut()
        .unwrap()
        .generation = u64::MAX;
    let lease = try_acquire(&pool, "last-generation").unwrap().unwrap();
    pool.release(lease).await.unwrap();
    assert!(changes.has_changed().unwrap());
    assert_eq!(*changes.borrow_and_update(), 1);
    assert_eq!(pool.observations().available, 0);
    assert_eq!(pool.observations().quarantined, 1);
    assert_eq!(
        try_acquire(&pool, "after-generation-exhaustion")
            .unwrap_err()
            .details[0]
            .kind,
        "cell-pool.all-quarantined"
    );
    assert_exact_accounting(pool.observations());
}

#[tokio::test]
async fn nonqueueing_capacity_is_atomic_under_concurrent_acquisition() {
    let pool = pool(3, 0);
    let start = Arc::new(Barrier::new(9));
    let reserved = Arc::new(Barrier::new(9));
    let workers: Vec<_> = (0..8)
        .map(|index| {
            let pool = pool.clone();
            let start = Arc::clone(&start);
            let reserved = Arc::clone(&reserved);
            std::thread::spawn(move || {
                start.wait();
                let result = try_acquire(&pool, &format!("racer-{index}"));
                reserved.wait();
                result
            })
        })
        .collect();
    start.wait();
    reserved.wait();
    let leases: Vec<_> = workers
        .into_iter()
        .filter_map(|worker| worker.join().unwrap().unwrap())
        .collect();
    assert_eq!(leases.len(), 3);
    assert_eq!(pool.observations().queue_depth, 0);
    assert_eq!(pool.observations().active_leases, 3);
    for lease in leases {
        pool.release(lease).await.unwrap();
    }
    assert_eq!(pool.observations().available, 3);
    assert_exact_accounting(pool.observations());
}

#[test]
fn nonqueueing_rejects_expired_deadlines_and_wrong_classes_with_bounded_errors() {
    let (pool, clock) = pool_with_clock(1, 0, 1000);
    let activation = ActivationId("sensitive-id".repeat(1024));
    let tenant = TenantId("tenant-test".to_owned());
    for (class, deadline, expected) in [
        (
            CellClass::Standard,
            Some(clock.now()),
            PlatformErrorCode::DeadlineExceeded,
        ),
        (CellClass::Tiny, None, PlatformErrorCode::InvalidArgument),
    ] {
        let error = pool
            .try_acquire_now(&activation, &tenant, class, &budget(None), deadline)
            .unwrap_err();
        assert_eq!(error.code, expected);
        assert!(!format!("{error:?}").contains("sensitive-id"));
        assert!(format!("{error:?}").len() < 512);
    }
    assert_eq!(pool.observations().available, 1);
    assert_eq!(pool.observations().queue_depth, 0);
}
