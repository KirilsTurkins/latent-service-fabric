use latent_core::{
    ActivationId, BoxFuture, CellId, NodeId, PlatformError, PlatformErrorCode, ResourceBudget,
    TenantId,
};
use latent_scheduler::{CellClass, CellLease, CellLeaseLifecycle, CellPool, CellPoolSnapshot};
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::Arc;

const CELL_ID: &str = "external-pool:standard:00000000";
const NODE_ID: &str = "external-node";

#[derive(Debug)]
struct ExternalState {
    available: AtomicBool,
    abandoned: AtomicUsize,
}

#[derive(Debug)]
struct ExternalLifecycle {
    state: Arc<ExternalState>,
}

impl CellLeaseLifecycle for ExternalLifecycle {
    fn on_abandoned(&self) {
        self.state.abandoned.fetch_add(1, Ordering::SeqCst);
        self.state.available.store(true, Ordering::SeqCst);
    }
}

struct ExternalPool {
    state: Arc<ExternalState>,
    lifecycle: Arc<dyn CellLeaseLifecycle>,
}

impl ExternalPool {
    fn new() -> Self {
        let state = Arc::new(ExternalState {
            available: AtomicBool::new(true),
            abandoned: AtomicUsize::new(0),
        });
        let lifecycle: Arc<dyn CellLeaseLifecycle> = Arc::new(ExternalLifecycle {
            state: state.clone(),
        });
        Self { state, lifecycle }
    }
}

impl CellPool for ExternalPool {
    fn acquire<'a>(
        &'a self,
        activation_id: &'a ActivationId,
        _tenant: &'a TenantId,
        class: CellClass,
        budget: &'a ResourceBudget,
    ) -> BoxFuture<'a, Result<CellLease, PlatformError>> {
        let result = if class != CellClass::Standard {
            Err(error(
                PlatformErrorCode::InvalidArgument,
                "external test pool supports only the standard class",
            ))
        } else if self
            .state
            .available
            .compare_exchange(true, false, Ordering::SeqCst, Ordering::SeqCst)
            .is_err()
        {
            Err(error(
                PlatformErrorCode::ResourceExhausted,
                "external test pool is busy",
            ))
        } else {
            Ok(CellLease::new(
                CellId(CELL_ID.to_owned()),
                activation_id.clone(),
                NodeId(NODE_ID.to_owned()),
                class,
                budget.clone(),
                u64::MAX,
                self.lifecycle.clone(),
            ))
        };
        Box::pin(async move { result })
    }

    fn release<'a>(&'a self, mut lease: CellLease) -> BoxFuture<'a, Result<(), PlatformError>> {
        Box::pin(async move {
            if lease.id.0 != CELL_ID
                || lease.node.0 != NODE_ID
                || lease.class != CellClass::Standard
            {
                return Err(error(
                    PlatformErrorCode::InvalidArgument,
                    "lease does not belong to the external test pool",
                ));
            }
            if !lease.disarm_lifecycle(&self.lifecycle) {
                return Err(error(
                    PlatformErrorCode::InvalidArgument,
                    "lease lifecycle capability does not match the external test pool",
                ));
            }
            self.state.available.store(true, Ordering::SeqCst);
            Ok(())
        })
    }

    fn capacity(&self, class: CellClass) -> u32 {
        if class == CellClass::Standard {
            1
        } else {
            0
        }
    }

    fn available(&self, class: CellClass) -> u32 {
        if class == CellClass::Standard && self.state.available.load(Ordering::SeqCst) {
            1
        } else {
            0
        }
    }
}

fn error(code: PlatformErrorCode, message: &str) -> PlatformError {
    PlatformError {
        code,
        message: message.to_owned(),
        retryable: false,
        details: Vec::new(),
    }
}

fn budget() -> ResourceBudget {
    ResourceBudget {
        cpu_fuel: 1,
        memory_bytes: 1,
        wall_time_limit_millis: None,
        child_calls: 0,
        outbound_requests: 0,
        state_read_bytes: 0,
        state_write_bytes: 0,
        blob_read_bytes: 0,
        blob_write_bytes: 0,
        log_bytes: 0,
        effect_count: 0,
    }
}

#[tokio::test(flavor = "current_thread")]
async fn external_pool_can_mint_release_and_reclaim_affine_leases() {
    let pool = ExternalPool::new();
    let tenant = TenantId("tenant-external".to_owned());
    let resource_budget = budget();

    let released = pool
        .acquire(
            &ActivationId("activation-released".to_owned()),
            &tenant,
            CellClass::Standard,
            &resource_budget,
        )
        .await
        .expect("external pool must mint a lease");
    assert_eq!(pool.available(CellClass::Standard), 0);
    pool.release(released)
        .await
        .expect("external pool must disposition its lease");
    assert_eq!(pool.available(CellClass::Standard), 1);
    assert_eq!(pool.state.abandoned.load(Ordering::SeqCst), 0);

    let abandoned = pool
        .acquire(
            &ActivationId("activation-abandoned".to_owned()),
            &tenant,
            CellClass::Standard,
            &resource_budget,
        )
        .await
        .expect("external pool must mint a second lease");
    drop(abandoned);
    assert_eq!(pool.available(CellClass::Standard), 1);
    assert_eq!(pool.state.abandoned.load(Ordering::SeqCst), 1);

    let snapshot = pool.observations(CellClass::Standard);
    assert_eq!(
        snapshot,
        CellPoolSnapshot {
            class: CellClass::Standard,
            capacity: 1,
            available: 1,
            queue_depth: 0,
            active_leases: 0,
            quarantined: 0,
        }
    );

    let cancellation = pool
        .cancel_waiting(&ActivationId("not-waiting".to_owned()))
        .await
        .expect_err("the compatibility default must reject unsupported cancellation");
    assert_eq!(cancellation.code, PlatformErrorCode::Unavailable);
}
