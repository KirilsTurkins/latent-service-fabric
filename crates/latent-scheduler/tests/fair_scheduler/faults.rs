//! Injected pool failures retain the real fixed-pool lease ownership behavior.

use std::collections::BTreeMap;
use std::future::Future;
use std::sync::Arc;
use std::task::{Context, Waker};
use std::time::Duration;

use latent_core::{
    ActivationId, BoxFuture, NodeId, PlatformError, PlatformErrorCode, ResourceBudget, TenantId,
};
use latent_scheduler::{
    ActivationScheduler, CellClass, CellLease, CellPool, CellPoolSnapshot, FixedCellPool,
    FixedCellPoolConfig, LocalScheduler, LocalSchedulerConfig,
};
use tokio::sync::watch;

use super::support::{complete, failure, Fixture};

#[derive(Clone, Copy)]
enum Fault {
    ForeignActivation,
    ForeignNode,
    WrongClass,
    WidenedBudget,
    Release,
    Quarantine,
    PendingRelease,
}

struct FaultPool {
    pool: FixedCellPool,
    fault: Fault,
}

fn injected_failure() -> PlatformError {
    PlatformError {
        code: PlatformErrorCode::Unavailable,
        message: "injected pool disposition failure".to_owned(),
        retryable: false,
        details: vec![],
    }
}

impl CellPool for FaultPool {
    fn try_acquire_now(
        &self,
        id: &ActivationId,
        tenant: &TenantId,
        class: CellClass,
        budget: &ResourceBudget,
        deadline: Option<u64>,
    ) -> Result<Option<CellLease>, PlatformError> {
        let mut lease = self
            .pool
            .try_acquire_now(id, tenant, class, budget, deadline)?;
        if let Some(lease) = lease.as_mut() {
            match self.fault {
                Fault::ForeignActivation => {
                    lease.activation_id = ActivationId("foreign".to_owned());
                }
                Fault::ForeignNode => lease.node = NodeId("foreign".to_owned()),
                Fault::WrongClass => lease.class = CellClass::Small,
                Fault::WidenedBudget => lease.granted_budget.cpu_fuel += 1,
                _ => {}
            }
        }
        Ok(lease)
    }

    fn subscribe_changes(&self) -> Option<watch::Receiver<u64>> {
        Some(self.pool.subscribe_changes())
    }

    fn acquire<'a>(
        &'a self,
        id: &'a ActivationId,
        tenant: &'a TenantId,
        class: CellClass,
        budget: &'a ResourceBudget,
    ) -> BoxFuture<'a, Result<CellLease, PlatformError>> {
        self.pool.acquire(id, tenant, class, budget)
    }

    fn release(&self, lease: CellLease) -> BoxFuture<'_, Result<(), PlatformError>> {
        Box::pin(async move {
            if matches!(self.fault, Fault::PendingRelease) {
                std::future::pending::<()>().await;
            }
            if matches!(self.fault, Fault::Release) {
                drop(lease);
                return Err(injected_failure());
            }
            self.pool.release(lease).await
        })
    }

    fn quarantine(
        &self,
        lease: CellLease,
        reason: String,
    ) -> BoxFuture<'_, Result<(), PlatformError>> {
        Box::pin(async move {
            if matches!(self.fault, Fault::Quarantine) {
                drop(lease);
                return Err(injected_failure());
            }
            self.pool.quarantine(lease, reason).await
        })
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

fn scheduler(fixture: &Fixture, fault: Fault) -> LocalScheduler {
    let node = NodeId("fair-test-node".to_owned());
    let tiny = Arc::new(FaultPool {
        pool: FixedCellPool::new(FixedCellPoolConfig::new(
            node.clone(),
            CellClass::Tiny,
            1,
            0,
        ))
        .unwrap(),
        fault,
    }) as Arc<dyn CellPool>;
    let small = Arc::new(
        FixedCellPool::new(FixedCellPoolConfig::new(
            node.clone(),
            CellClass::Small,
            1,
            0,
        ))
        .unwrap(),
    ) as Arc<dyn CellPool>;
    LocalScheduler::with_pools(
        LocalSchedulerConfig {
            node,
            queue_capacity_per_class: BTreeMap::from([(CellClass::Tiny, 2), (CellClass::Small, 2)]),
            starvation_after: Duration::from_secs(1),
        },
        fixture.quotas.clone(),
        BTreeMap::from([(CellClass::Tiny, tiny), (CellClass::Small, small)]),
    )
    .unwrap()
}

#[tokio::test(start_paused = true)]
async fn startup_rejects_incompatible_configuration_and_actual_pool_counts() {
    let fixture = Fixture::new(1, 2, Duration::from_secs(1));
    for variant in 0..4 {
        let mut configuration = fixture.configuration.clone();
        match variant {
            0 => {
                configuration
                    .queue_capacity_per_class
                    .remove(&CellClass::Small);
            }
            1 => {
                configuration
                    .queue_capacity_per_class
                    .remove(&CellClass::Small);
                configuration
                    .queue_capacity_per_class
                    .insert(CellClass::Large, 2);
            }
            2 => configuration.node = NodeId(String::new()),
            _ => configuration.starvation_after = Duration::ZERO,
        }
        match LocalScheduler::new(configuration, fixture.quotas.clone()) {
            Err(error) => assert_eq!(error.code, PlatformErrorCode::InvalidArgument),
            Ok(_) => panic!("invalid startup configuration must be rejected"),
        }
    }
    let node = fixture.configuration.node.clone();
    let pools: BTreeMap<CellClass, Arc<dyn CellPool>> = BTreeMap::from([
        (
            CellClass::Tiny,
            Arc::new(
                FixedCellPool::new(FixedCellPoolConfig::new(
                    node.clone(),
                    CellClass::Tiny,
                    2,
                    0,
                ))
                .unwrap(),
            ) as Arc<dyn CellPool>,
        ),
        (
            CellClass::Small,
            Arc::new(
                FixedCellPool::new(FixedCellPoolConfig::new(node, CellClass::Small, 1, 0)).unwrap(),
            ) as Arc<dyn CellPool>,
        ),
    ]);
    match LocalScheduler::with_pools(fixture.configuration.clone(), fixture.quotas.clone(), pools) {
        Err(error) => assert_eq!(error.code, PlatformErrorCode::InvalidArgument),
        Ok(_) => panic!("pool capacity must match admission parallelism"),
    }
    fixture.assert_no_quota();
}

#[tokio::test(start_paused = true)]
async fn pool_cannot_substitute_activation_node_class_or_budget_at_handoff() {
    for fault in [
        Fault::ForeignActivation,
        Fault::ForeignNode,
        Fault::WrongClass,
        Fault::WidenedBudget,
    ] {
        let fixture = Fixture::new(1, 2, Duration::from_secs(1));
        let scheduler = scheduler(&fixture, fault);
        let _ = failure(scheduler.enqueue(fixture.request("expected", "a"))).await;
        assert_eq!(scheduler.observations(CellClass::Tiny).active_leases, 0);
        assert_eq!(scheduler.observations(CellClass::Tiny).quarantined, 1);
        fixture.assert_no_quota();
    }
}

#[tokio::test(start_paused = true)]
async fn disposition_errors_quarantine_the_cell_and_return_the_execution_reservation() {
    for fault in [Fault::Release, Fault::Quarantine] {
        let fixture = Fixture::new(1, 2, Duration::from_secs(1));
        let scheduler = scheduler(&fixture, fault);
        let activation = complete(scheduler.enqueue(fixture.request("dispose", "a"))).await;
        let result = if matches!(fault, Fault::Release) {
            activation.release().await
        } else {
            activation.quarantine("uncertain reset".to_owned()).await
        };
        assert_eq!(result.unwrap_err().code, PlatformErrorCode::Unavailable);
        assert_eq!(scheduler.observations(CellClass::Tiny).active_leases, 0);
        assert_eq!(scheduler.observations(CellClass::Tiny).quarantined, 1);
        fixture.assert_no_quota();
    }
}

#[tokio::test(start_paused = true)]
async fn dropping_a_pending_disposition_keeps_quota_until_the_cell_is_abandoned() {
    let fixture = Fixture::new(1, 2, Duration::from_secs(1));
    let scheduler = scheduler(&fixture, Fault::PendingRelease);
    let activation = complete(scheduler.enqueue(fixture.request("pending-release", "a"))).await;
    let mut disposition = Box::pin(activation.release());
    assert!(disposition
        .as_mut()
        .poll(&mut Context::from_waker(Waker::noop()))
        .is_pending());
    assert_eq!(fixture.quotas.usage().unwrap().active_activations, 1);
    assert_eq!(scheduler.observations(CellClass::Tiny).active_leases, 1);
    drop(disposition);
    assert_eq!(scheduler.observations(CellClass::Tiny).quarantined, 1);
    assert_eq!(scheduler.observations(CellClass::Tiny).active_leases, 0);
    fixture.assert_no_quota();
}
