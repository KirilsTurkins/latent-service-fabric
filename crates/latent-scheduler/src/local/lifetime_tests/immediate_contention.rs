//! An idle dispatch observer owns no cell and cannot manufacture exhaustion.
use std::collections::BTreeMap;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{mpsc, Arc, Mutex};
use std::time::Duration;

use latent_core::{ActivationId, BoxFuture, PlatformError, ResourceBudget, TenantId};

use super::{AdmittedSchedulingRequest, Cancellation, Fixture};
use crate::{
    ActivationScheduler, CellClass, CellLease, CellPool, CellPoolSnapshot, LocalScheduler,
};

struct ObservedPool {
    real: Arc<dyn CellPool>,
    armed: AtomicBool,
    entered: mpsc::SyncSender<bool>,
    released: Mutex<mpsc::Receiver<()>>,
}

impl CellPool for ObservedPool {
    fn try_acquire_now(
        &self,
        id: &ActivationId,
        tenant: &TenantId,
        class: CellClass,
        budget: &ResourceBudget,
        deadline: Option<u64>,
    ) -> Result<Option<CellLease>, PlatformError> {
        self.real
            .try_acquire_now(id, tenant, class, budget, deadline)
    }

    fn subscribe_changes(&self) -> Option<tokio::sync::watch::Receiver<u64>> {
        self.real.subscribe_changes()
    }

    fn acquire<'a>(
        &'a self,
        id: &'a ActivationId,
        tenant: &'a TenantId,
        class: CellClass,
        budget: &'a ResourceBudget,
    ) -> BoxFuture<'a, Result<CellLease, PlatformError>> {
        self.real.acquire(id, tenant, class, budget)
    }

    fn release(&self, lease: CellLease) -> BoxFuture<'_, Result<(), PlatformError>> {
        self.real.release(lease)
    }

    fn capacity(&self, class: CellClass) -> u32 {
        self.real.capacity(class)
    }

    fn available(&self, class: CellClass) -> u32 {
        self.real.available(class)
    }

    fn quarantine(
        &self,
        lease: CellLease,
        reason: String,
    ) -> BoxFuture<'_, Result<(), PlatformError>> {
        self.real.quarantine(lease, reason)
    }

    fn observations(&self, class: CellClass) -> CellPoolSnapshot {
        if self.armed.swap(false, Ordering::SeqCst) {
            self.entered.send(true).unwrap();
            self.released
                .lock()
                .unwrap()
                .recv_timeout(Duration::from_secs(5))
                .expect("actual pool observer must be released inside the watchdog");
        }
        self.real.observations(class)
    }
}

#[tokio::test]
async fn an_empty_dispatch_pass_is_not_immediate_cell_exhaustion() {
    let mut fixture = Fixture::new(1, 4).unwrap();
    let real = Arc::clone(&fixture.scheduler.inner.pools[&CellClass::Standard]);
    let (entered, ready) = mpsc::sync_channel(2);
    let completed = entered.clone();
    let (release, released) = mpsc::sync_channel(1);
    let observed = Arc::new(ObservedPool {
        real,
        armed: AtomicBool::new(false),
        entered,
        released: Mutex::new(released),
    });
    fixture.scheduler = Arc::new(
        LocalScheduler::with_pools(
            fixture.scheduler.inner.config.clone(),
            fixture.quotas.clone(),
            BTreeMap::from([(
                CellClass::Standard,
                Arc::clone(&observed) as Arc<dyn CellPool>,
            )]),
        )
        .unwrap(),
    );
    observed.armed.store(true, Ordering::SeqCst);
    let scheduler = Arc::clone(&fixture.scheduler);
    let pump = std::thread::spawn(move || {
        let result = scheduler.inner.pump(CellClass::Standard);
        completed.send(false).unwrap();
        result
    });
    let observer_blocked = ready
        .recv_timeout(Duration::from_secs(5))
        .expect("real pool observation establishes the competing dispatch owner");
    if !observer_blocked {
        // A truly empty pass completed without opening the pool seam.
        assert!(observed.armed.swap(false, Ordering::SeqCst));
    }
    assert_eq!(observed.real.available(CellClass::Standard), 4);
    let result = fixture.scheduler.try_enqueue(AdmittedSchedulingRequest {
        permit: fixture.admit(0, 0).unwrap(),
        cancellation: Cancellation::new(0),
    });
    if observer_blocked {
        release.send(()).unwrap();
    }
    assert!(pump.join().unwrap());
    let assignment = result.expect("an empty observer is not unavailable execution capacity");
    assert_eq!(assignment.lease().activation_id.0, "scheduler-00000");
    assert_eq!(
        fixture
            .scheduler
            .observations(CellClass::Standard)
            .active_leases,
        1
    );
    assignment.release().await.unwrap();
    fixture.idle().unwrap();
    assert!(fixture.scheduler.inner.lock().live.is_empty());
}

#[tokio::test]
async fn an_immediate_registration_retains_its_own_fair_turn_before_publication() {
    let fixture = Fixture::new(1, 4).unwrap();
    let request = AdmittedSchedulingRequest {
        permit: fixture.admit(0, 0).unwrap(),
        cancellation: Cancellation::new(0),
    };
    fixture.scheduler.validate_request(&request).unwrap();
    let (sender, mut receiver) = tokio::sync::oneshot::channel();
    let (_, turn) = fixture
        .scheduler
        .register_owned_request(CellClass::Standard, request, sender, true)
        .unwrap();
    // This is the real registered request and admission owner, before its
    // caller has run the fair pass. A competing pump cannot steal its handoff.
    assert!(!fixture.scheduler.inner.pump(CellClass::Standard));
    assert!(matches!(
        receiver.try_recv(),
        Err(tokio::sync::oneshot::error::TryRecvError::Empty)
    ));
    let pending = fixture.scheduler.observations(CellClass::Standard);
    assert_eq!(pending.queue_depth, 1);
    assert_eq!(pending.active_leases, 0);
    assert_eq!(pending.available, 4);
    assert_eq!(fixture.quotas.usage().unwrap().queued_activations, 1);
    let mut publications = Vec::new();
    assert!(fixture.scheduler.inner.pump_owned(
        CellClass::Standard,
        turn.unwrap(),
        &mut publications,
    ));
    assert!(publications.is_empty());
    let assignment = receiver.try_recv().unwrap().unwrap().accept().unwrap();
    assert_eq!(assignment.lease().activation_id.0, "scheduler-00000");
    assert_eq!(fixture.quotas.usage().unwrap().active_activations, 1);
    assignment.release().await.unwrap();
    fixture.idle().unwrap();
    assert!(fixture.scheduler.inner.lock().live.is_empty());
}
