use std::future::{poll_fn, Future};
use std::pin::Pin;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::Arc;
use std::task::Poll;
use std::time::Duration;

use latent_core::{
    ActivationId, BoxFuture, NodeId, PlatformError, PlatformErrorCode, ResourceBudget, TenantId,
};
use latent_node::ActivationTransportInterruption as Cause;
use latent_scheduler::{
    CellClass, CellLease, CellPool, CellPoolSnapshot, FixedCellPool, FixedCellPoolConfig,
};

use super::model::request;
use super::support::{error, finish, pending, tenant, Gate, Harness};
use super::transport_cleanup::Observations;

/// Holds a real issuer-owned lease at pool disposition; no synthetic reclaim
/// proof or reconstructed lease bypasses the fixed pool's quarantine behavior.
struct HeldRelease {
    pool: FixedCellPool,
    gate: Gate,
    entered: AtomicUsize,
    fail: AtomicBool,
}

impl HeldRelease {
    fn new() -> Self {
        Self {
            pool: FixedCellPool::new(FixedCellPoolConfig::new(
                NodeId("lifecycle-node".into()),
                CellClass::Tiny,
                1,
                0,
            ))
            .unwrap(),
            gate: Gate::new(false),
            entered: AtomicUsize::new(0),
            fail: AtomicBool::new(false),
        }
    }
}

impl CellPool for HeldRelease {
    fn try_acquire_now(
        &self,
        activation: &ActivationId,
        tenant: &TenantId,
        class: CellClass,
        budget: &ResourceBudget,
        deadline: Option<u64>,
    ) -> Result<Option<CellLease>, PlatformError> {
        self.pool
            .try_acquire_now(activation, tenant, class, budget, deadline)
    }
    fn subscribe_changes(&self) -> Option<tokio::sync::watch::Receiver<u64>> {
        Some(self.pool.subscribe_changes())
    }
    fn acquire<'a>(
        &'a self,
        activation: &'a ActivationId,
        tenant: &'a TenantId,
        class: CellClass,
        budget: &'a ResourceBudget,
    ) -> BoxFuture<'a, Result<CellLease, PlatformError>> {
        self.pool.acquire(activation, tenant, class, budget)
    }
    fn release(&self, lease: CellLease) -> BoxFuture<'_, Result<(), PlatformError>> {
        Box::pin(async move {
            self.entered.fetch_add(1, Ordering::Relaxed);
            self.gate.wait().await;
            if self.fail.load(Ordering::Acquire) {
                drop(lease);
                return Err(error(
                    PlatformErrorCode::Internal,
                    "controlled release failure",
                ));
            }
            self.pool.release(lease).await
        })
    }
    fn quarantine(
        &self,
        lease: CellLease,
        reason: String,
    ) -> BoxFuture<'_, Result<(), PlatformError>> {
        self.pool.quarantine(lease, reason)
    }
    fn capacity(&self, class: CellClass) -> u32 {
        self.pool.capacity(class)
    }
    fn available(&self, class: CellClass) -> u32 {
        self.pool.available(class)
    }
    fn observations(&self, class: CellClass) -> CellPoolSnapshot {
        CellPool::observations(&self.pool, class)
    }
}

#[tokio::test(start_paused = true)]
async fn transport_handoff_during_pool_disposition_keeps_its_original_owner_and_timer() {
    for mode in 0..3 {
        let observations = Arc::new(Observations::default());
        let pool = Arc::new(HeldRelease::new());
        let harness = Harness::with_pool(1, 8, Some(observations.clone()), Some(pool.clone()));
        let mut owner = harness.manager.start(request("in-release")).unwrap();
        pending(Pin::new(&mut owner)).await;
        assert_eq!(pool.entered.load(Ordering::Relaxed), 1);
        assert_eq!(harness.backend.live_calls.load(Ordering::Relaxed), 0);
        assert_eq!(harness.backend.live_prepared.load(Ordering::Relaxed), 0);
        assert_eq!(
            harness
                .quotas
                .snapshot_now(&tenant())
                .unwrap()
                .active_activations,
            1
        );
        assert_eq!(pool.observations(CellClass::Tiny).active_leases, 1);
        assert_eq!(harness.manager.journal().snapshot().active, 1);
        tokio::time::advance(Duration::from_millis(60)).await;
        let mut owner = owner.interrupt_for_cleanup(Cause::Disconnected);
        pending(Pin::new(&mut owner)).await;
        let receipt = if mode == 2 {
            // This is 101 ms from the original pool wait, only 41 ms from
            // handoff: rebuilding/resetting disposition would leave it pending.
            tokio::time::advance(Duration::from_millis(41)).await;
            let result = poll_fn(|cx| Poll::Ready(Pin::new(&mut owner).poll(cx))).await;
            let Poll::Ready(receipt) = result else {
                panic!("pool grace must not restart");
            };
            drop(owner);
            receipt
        } else {
            pool.fail.store(mode == 1, Ordering::Release);
            pool.gate.open();
            finish(owner).await
        };
        assert_eq!(receipt.activation_id, ActivationId("in-release".into()));
        assert_eq!(
            harness
                .status("in-release")
                .final_consumption
                .unwrap()
                .cpu_fuel,
            3
        );
        let snapshot = pool.observations(CellClass::Tiny);
        assert_eq!(
            (snapshot.available, snapshot.quarantined),
            if mode == 0 { (1, 0) } else { (0, 1) }
        );
        assert_eq!(
            observations.released.load(Ordering::Relaxed),
            usize::from(mode == 0)
        );
        assert_eq!(
            observations.failed.load(Ordering::Relaxed),
            usize::from(mode != 0)
        );
        assert_eq!(observations.accepted_cancel.load(Ordering::Relaxed), 0);
        assert_eq!(observations.terminal.load(Ordering::Relaxed), 1);
        harness.assert_idle();
    }
}
