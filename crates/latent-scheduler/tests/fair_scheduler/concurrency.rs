//! Bounded barriers expose races across the synchronous pool extension seam.

use std::collections::BTreeMap;
use std::sync::{mpsc, Arc, Mutex};
use std::time::Duration;

use latent_core::{
    ActivationId, BoxFuture, PlatformError, PlatformErrorCode, ResourceBudget, TenantId,
};
use latent_scheduler::{
    ActivationScheduler, CellClass, CellLease, CellPool, CellPoolSnapshot, FixedCellPool,
    FixedCellPoolConfig, LocalScheduler, SchedulingCancellation,
};
use tokio::sync::{oneshot, watch};

use super::support::{complete, failure, register, Fixture};

const BARRIER_TIMEOUT: Duration = Duration::from_secs(2);

struct PausedPool {
    pool: FixedCellPool,
    entered: Mutex<Option<oneshot::Sender<()>>>,
    resume: Mutex<Option<mpsc::Receiver<()>>>,
    changes: watch::Sender<u64>,
    deny_first: bool,
}

impl CellPool for PausedPool {
    fn try_acquire_now(
        &self,
        id: &ActivationId,
        tenant: &TenantId,
        class: CellClass,
        budget: &ResourceBudget,
        deadline: Option<u64>,
    ) -> Result<Option<CellLease>, PlatformError> {
        let resume = self.resume.lock().unwrap().take();
        if let Some(resume) = resume {
            self.entered
                .lock()
                .unwrap()
                .take()
                .unwrap()
                .send(())
                .unwrap();
            // Production pools are nonblocking; this bounded test seam leaves
            // the selected entry outside the scheduler mutex for another task.
            resume.recv_timeout(BARRIER_TIMEOUT).unwrap();
            if self.deny_first {
                // Retain a hint before the failed probe returns, exercising the
                // subscription/probe ordering as well as restoring the slot.
                self.changes.send_modify(|version| *version += 1);
                return Ok(None);
            }
        }
        self.pool
            .try_acquire_now(id, tenant, class, budget, deadline)
    }

    fn subscribe_changes(&self) -> Option<watch::Receiver<u64>> {
        Some(self.changes.subscribe())
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
            let result = self.pool.release(lease).await;
            self.changes.send_modify(|version| *version += 1);
            result
        })
    }

    fn quarantine(
        &self,
        lease: CellLease,
        reason: String,
    ) -> BoxFuture<'_, Result<(), PlatformError>> {
        Box::pin(async move {
            let result = self.pool.quarantine(lease, reason).await;
            self.changes.send_modify(|version| *version += 1);
            result
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

fn paused_scheduler(
    fixture: &Fixture,
    deny_first: bool,
) -> (Arc<LocalScheduler>, oneshot::Receiver<()>, mpsc::Sender<()>) {
    let (scheduler, _, entered, resume) = paused_scheduler_with_backing(fixture, deny_first);
    (scheduler, entered, resume)
}

fn paused_scheduler_with_backing(
    fixture: &Fixture,
    deny_first: bool,
) -> (
    Arc<LocalScheduler>,
    FixedCellPool,
    oneshot::Receiver<()>,
    mpsc::Sender<()>,
) {
    let (entered_sender, entered) = oneshot::channel();
    let (resume, resume_receiver) = mpsc::channel();
    let node = fixture.configuration.node.clone();
    let backing = FixedCellPool::new(FixedCellPoolConfig::new(
        node.clone(),
        CellClass::Tiny,
        1,
        0,
    ))
    .unwrap();
    let tiny: Arc<dyn CellPool> = Arc::new(PausedPool {
        pool: backing.clone(),
        entered: Mutex::new(Some(entered_sender)),
        resume: Mutex::new(Some(resume_receiver)),
        changes: watch::channel(0).0,
        deny_first,
    });
    let small: Arc<dyn CellPool> = Arc::new(
        FixedCellPool::new(FixedCellPoolConfig::new(node, CellClass::Small, 1, 0)).unwrap(),
    );
    let scheduler = LocalScheduler::with_pools(
        fixture.configuration.clone(),
        fixture.quotas.clone(),
        BTreeMap::from([(CellClass::Tiny, tiny), (CellClass::Small, small)]),
    )
    .unwrap();
    (Arc::new(scheduler), backing, entered, resume)
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn selected_cancellation_preserves_reused_slot_and_allows_id_reuse_after_cleanup() {
    for deny_first in [true, false] {
        selected_cancellation_with_slot_and_id_reuse(deny_first).await;
    }
}

async fn selected_cancellation_with_slot_and_id_reuse(deny_first: bool) {
    let fixture = Fixture::new(1, 2, Duration::from_secs(1));
    let (scheduler, backing, entered, resume) = paused_scheduler_with_backing(&fixture, deny_first);
    let id = ActivationId("selected-reused".to_owned());
    let original_request = fixture.request(&id.0, "a");
    // Prime the actual cell without entering the paused wrapper. The first A
    // future registers with a noop waker while no cell is available.
    let held = backing
        .try_acquire_now(
            &ActivationId("raw-held".to_owned()),
            original_request.permit.tenant(),
            CellClass::Tiny,
            original_request.permit.granted_budget(),
            None,
        )
        .unwrap()
        .unwrap();
    let mut original = scheduler.enqueue(original_request);
    register(&mut original);
    assert_eq!(scheduler.observations(CellClass::Tiny).queue_depth, 1);
    backing.release(held).await.unwrap();

    // B's independent poll owns the dispatch guard and selects the older A.
    let owner = Arc::clone(&scheduler);
    let other_request = fixture.request("other", "b");
    let other = tokio::spawn(async move { owner.enqueue(other_request).await });
    tokio::time::timeout(BARRIER_TIMEOUT, entered)
        .await
        .expect("B's pump pauses while acquiring the original A")
        .unwrap();
    assert_eq!(scheduler.observations(CellClass::Tiny).queue_depth, 2);

    scheduler.cancel(&id).await.unwrap();
    assert_eq!(failure(original).await, PlatformErrorCode::Cancelled);
    assert_eq!(scheduler.observations(CellClass::Tiny).queue_depth, 1);
    // The selected entry still owns A's permit, so admission must retain its ID
    // until the old pool call returns. Its physical queue slot is reusable now.
    let duplicate = fixture
        .try_custom_request(&id.0, "a", 10, 60_000, 65_536)
        .err()
        .expect("selected admission ID remains owned across the pool call");
    assert_eq!(duplicate.code, PlatformErrorCode::AlreadyExists);
    let mut slot_reuser = scheduler.enqueue(fixture.request("slot-reuser", "c"));
    register(&mut slot_reuser);
    let queued = scheduler.observations(CellClass::Tiny);
    assert_eq!(queued.queue_depth, 2);
    assert_eq!(queued.queued_tenants, 2);
    assert_eq!(queued.cancellations, 1);
    assert_eq!(queued.rejected, 1);
    resume.send(()).unwrap();

    let other = tokio::time::timeout(BARRIER_TIMEOUT, other)
        .await
        .expect("the stale A acquisition leaves B schedulable")
        .unwrap()
        .unwrap();
    assert_eq!(other.lease().activation_id.0, "other");
    // B's completed poll also completed the stale acquisition and refunded A's
    // original permit. Reuse of the original public ID is now legal.
    let mut replacement = scheduler.enqueue(fixture.request(&id.0, "a"));
    register(&mut replacement);
    other.release().await.unwrap();
    let slot_reuser = complete(slot_reuser).await;
    assert_eq!(slot_reuser.lease().activation_id.0, "slot-reuser");
    assert!(!slot_reuser.cancellation().is_cancelled());
    slot_reuser.release().await.unwrap();
    let replacement = complete(replacement).await;
    assert_eq!(replacement.lease().activation_id, id);
    assert!(!replacement.cancellation().is_cancelled());
    replacement.release().await.unwrap();

    let snapshot = scheduler.observations(CellClass::Tiny);
    assert_eq!(snapshot.cancellations, 1);
    assert_eq!(snapshot.rejected, 1);
    assert_eq!(snapshot.granted, 3);
    assert_eq!(snapshot.queue_depth, 0);
    assert_eq!(snapshot.queued_tenants, 0);
    assert_eq!(snapshot.active_leases, 0);
    assert_eq!(snapshot.available, 1);
    assert_eq!(snapshot.quarantined, 0);
    fixture.assert_no_quota();
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn selected_entry_reserves_its_queue_slot_until_failed_acquisition_is_restored() {
    let fixture = Fixture::new(1, 1, Duration::from_secs(1));
    let (scheduler, entered, resume) = paused_scheduler(&fixture, true);
    let request = fixture.request("selected", "a");
    let owner = Arc::clone(&scheduler);
    let selected = tokio::spawn(async move { owner.enqueue(request).await });
    tokio::time::timeout(BARRIER_TIMEOUT, entered)
        .await
        .expect("selected entry reaches pool seam")
        .unwrap();

    assert_eq!(scheduler.observations(CellClass::Tiny).queue_depth, 1);
    assert_eq!(
        failure(scheduler.enqueue(fixture.request("concurrent", "b"))).await,
        PlatformErrorCode::ResourceExhausted
    );
    assert_eq!(scheduler.observations(CellClass::Tiny).queue_depth, 1);
    resume.send(()).unwrap();

    let activation = tokio::time::timeout(BARRIER_TIMEOUT, selected)
        .await
        .expect("restored entry retries its retained change notification")
        .unwrap()
        .unwrap();
    assert_eq!(activation.lease().activation_id.0, "selected");
    let snapshot = scheduler.observations(CellClass::Tiny);
    assert_eq!(snapshot.queue_depth, 0);
    assert_eq!(snapshot.active_leases, 1);
    assert_eq!(snapshot.granted, 1);
    assert_eq!(snapshot.rejected, 1);
    activation.release().await.unwrap();
    fixture.assert_no_quota();
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn shutdown_during_selected_acquisition_reclaims_the_unaccepted_cell() {
    let fixture = Fixture::new(1, 1, Duration::from_secs(1));
    let (scheduler, entered, resume) = paused_scheduler(&fixture, false);
    let request = fixture.request("shutdown-selected", "a");
    let owner = Arc::clone(&scheduler);
    let selected = tokio::spawn(async move { owner.enqueue(request).await });
    tokio::time::timeout(BARRIER_TIMEOUT, entered)
        .await
        .expect("selected entry reaches pool seam")
        .unwrap();

    scheduler.shutdown();
    assert_eq!(scheduler.observations(CellClass::Tiny).queue_depth, 0);
    resume.send(()).unwrap();
    let failure = tokio::time::timeout(BARRIER_TIMEOUT, selected)
        .await
        .expect("shutdown settles the selected acquisition")
        .unwrap()
        .unwrap_err();
    assert_eq!(failure.code, PlatformErrorCode::Unavailable);

    let snapshot = scheduler.observations(CellClass::Tiny);
    assert_eq!(snapshot.queue_depth, 0);
    assert_eq!(snapshot.active_leases, 0);
    assert_eq!(snapshot.available, 1);
    assert_eq!(snapshot.quarantined, 0);
    assert_eq!(snapshot.granted, 0);
    assert_eq!(snapshot.rejected, 1);
    fixture.assert_no_quota();
}

struct PausedCancellation {
    delegate: Arc<dyn SchedulingCancellation>,
    entered: Mutex<Option<oneshot::Sender<()>>>,
    resume: Mutex<Option<mpsc::Receiver<()>>>,
}

impl SchedulingCancellation for PausedCancellation {
    fn activation_id(&self) -> &ActivationId {
        self.delegate.activation_id()
    }

    fn is_cancelled(&self) -> bool {
        self.delegate.is_cancelled()
    }

    fn request_cancellation(&self) -> bool {
        let resume = self.resume.lock().unwrap().take();
        if let Some(resume) = resume {
            self.entered
                .lock()
                .unwrap()
                .take()
                .unwrap()
                .send(())
                .unwrap();
            resume.recv_timeout(BARRIER_TIMEOUT).unwrap();
        }
        self.delegate.request_cancellation()
    }

    fn cancelled(&self) -> BoxFuture<'_, ()> {
        self.delegate.cancelled()
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn cancellation_of_a_retired_registration_cannot_mark_a_reused_activation_id() {
    let fixture = Fixture::new(1, 2, Duration::from_secs(1));
    let scheduler = &fixture.scheduler;
    let (entered_sender, entered) = oneshot::channel();
    let (resume, resume_receiver) = mpsc::channel();
    let mut original_request = fixture.request("reused", "a");
    original_request.cancellation = Arc::new(PausedCancellation {
        delegate: original_request.cancellation,
        entered: Mutex::new(Some(entered_sender)),
        resume: Mutex::new(Some(resume_receiver)),
    });
    let original = scheduler.enqueue(original_request).await.unwrap();
    let owner = Arc::clone(scheduler);
    let cancellation =
        tokio::spawn(async move { owner.cancel(&ActivationId("reused".to_owned())).await });
    tokio::time::timeout(BARRIER_TIMEOUT, entered)
        .await
        .expect("cancel snapshots the original registration")
        .unwrap();

    original.release().await.unwrap();
    let replacement = scheduler
        .enqueue(fixture.request("reused", "a"))
        .await
        .unwrap();
    resume.send(()).unwrap();
    tokio::time::timeout(BARRIER_TIMEOUT, cancellation)
        .await
        .expect("stale cancellation settles")
        .unwrap()
        .unwrap();
    assert!(!replacement.cancellation().is_cancelled());
    assert_eq!(scheduler.observations(CellClass::Tiny).cancellations, 0);

    scheduler
        .cancel(&ActivationId("reused".to_owned()))
        .await
        .unwrap();
    assert!(replacement.cancellation().is_cancelled());
    assert_eq!(scheduler.observations(CellClass::Tiny).cancellations, 1);
    replacement.release().await.unwrap();
    fixture.assert_no_quota();
}
