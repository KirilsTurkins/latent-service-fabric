use super::super::errors::WallClock;
use super::super::{FixedCellPool, FixedCellPoolConfig};
use crate::{CellClass, CellPool, CellPoolSnapshot};
use latent_core::{ActivationId, NodeId, ResourceBudget, TenantId};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;

#[derive(Debug, Clone)]
pub(super) struct TestWallClock {
    now_unix_millis: Arc<AtomicU64>,
}

impl TestWallClock {
    fn new(now_unix_millis: u64) -> Self {
        Self {
            now_unix_millis: Arc::new(AtomicU64::new(now_unix_millis)),
        }
    }

    pub(super) fn now(&self) -> u64 {
        self.now_unix_millis.load(Ordering::SeqCst)
    }

    pub(super) fn advance(&self, delta_millis: u64) -> u64 {
        let previous = self
            .now_unix_millis
            .fetch_update(Ordering::SeqCst, Ordering::SeqCst, |current| {
                current.checked_add(delta_millis)
            })
            .expect("test wall clock overflow");
        previous + delta_millis
    }
}

impl WallClock for TestWallClock {
    fn now_unix_millis(&self) -> u64 {
        self.now()
    }
}

fn config(capacity: u32, queue_capacity: u32) -> FixedCellPoolConfig {
    FixedCellPoolConfig::new(
        NodeId("node-test".to_owned()),
        CellClass::Standard,
        capacity,
        queue_capacity,
    )
}

pub(super) fn pool(capacity: u32, queue_capacity: u32) -> FixedCellPool {
    FixedCellPool::new(config(capacity, queue_capacity)).expect("valid fixed pool")
}

pub(super) fn pool_with_clock(
    capacity: u32,
    queue_capacity: u32,
    now_unix_millis: u64,
) -> (FixedCellPool, TestWallClock) {
    let clock = TestWallClock::new(now_unix_millis);
    let pool = FixedCellPool::new_with_clock(
        config(capacity, queue_capacity),
        Arc::new(clock.clone()),
    )
    .expect("valid fixed pool");
    (pool, clock)
}

pub(super) fn budget(deadline: Option<u64>) -> ResourceBudget {
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

pub(super) async fn acquire(
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

pub(super) async fn wait_for_queue_depth(pool: &FixedCellPool, expected: u32) {
    for _ in 0..1_024 {
        if pool.observations().queue_depth == expected {
            return;
        }
        tokio::task::yield_now().await;
    }
    panic!("queue depth did not become {expected}");
}

pub(super) async fn wait_for_settled(pool: &FixedCellPool) {
    for _ in 0..1_024 {
        let observations = pool.observations();
        if observations.queue_depth == 0 && observations.active_leases == 0 {
            return;
        }
        tokio::task::yield_now().await;
    }
    panic!("pool did not settle");
}

pub(super) fn assert_exact_accounting(observations: CellPoolSnapshot) {
    assert_eq!(
        observations.available + observations.active_leases + observations.quarantined,
        observations.capacity
    );
}
