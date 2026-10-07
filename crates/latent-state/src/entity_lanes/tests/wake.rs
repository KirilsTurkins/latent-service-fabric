use super::*;
use std::sync::{
    atomic::{AtomicUsize, Ordering},
    Arc, Mutex, Weak,
};

#[derive(Default)]
struct WakeProbe {
    table: Mutex<Option<Weak<Inner<Command>>>>,
    wakes: AtomicUsize,
}

impl EntityLaneWake for WakeProbe {
    fn changed(&self) {
        if let Some(table) = self.table.lock().unwrap().as_ref().and_then(Weak::upgrade) {
            assert!(
                table.state.try_lock().is_ok(),
                "wake must run outside the lane lock"
            );
        }
        self.wakes.fetch_add(1, Ordering::SeqCst);
    }
}

#[test]
fn shared_wake_follows_queue_removal_and_actual_last_physical_retirement() {
    let now = Instant::now();
    let wake = Arc::new(WakeProbe::default());
    let lanes = EntityLanes::new_with_wake(limits(), Some(wake.clone())).unwrap();
    *wake.table.lock().unwrap() = Some(Arc::downgrade(&lanes.inner));
    let first = enqueue(&lanes, "tenant-A", "same", 1, now);
    let active = start(&lanes, now);
    let physical = active.retain_physical_owner();
    drop(active);
    let before = wake.wakes.load(Ordering::SeqCst);
    let second = enqueue(&lanes, "tenant-A", "same", 2, now);
    assert_eq!(wake.wakes.load(Ordering::SeqCst), before + 1);
    assert_eq!(lanes.snapshot().unwrap().active, 1);
    drop(physical);
    assert_eq!(wake.wakes.load(Ordering::SeqCst), before + 2);
    let active = start(&lanes, now);
    drop(active);
    drop(first);
    drop(second);
    assert_empty(&lanes);
    let queued = enqueue(&lanes, "tenant-A", "cancel", 3, now);
    let before = wake.wakes.load(Ordering::SeqCst);
    drop(queued);
    assert_eq!(wake.wakes.load(Ordering::SeqCst), before + 1);
    assert_empty(&lanes);
}

#[test]
fn final_short_fence_rejects_revoked_and_retired_generations_without_refunding_physical_work() {
    let now = Instant::now();
    let lanes = EntityLanes::new(limits()).unwrap();
    let waiter = enqueue(&lanes, "tenant-A", "same", 1, now);
    let execution = start(&lanes, now);
    let fence = execution.fence();
    assert_eq!(lanes.with_fence(&fence, || 7), Ok(7));
    lanes
        .revoke_namespace(
            &TenantId("tenant-A".into()),
            &StateNamespaceId("orders".into()),
            1,
        )
        .unwrap();
    assert_eq!(
        lanes.with_fence(&fence, || panic!("revoked callback must not run")),
        Err(EntityLaneError::StaleFence)
    );
    assert_eq!(lanes.snapshot().unwrap().active, 1);
    drop(execution);
    drop(waiter);
    assert_empty(&lanes);
    assert_eq!(
        lanes.with_fence(&fence, || panic!("retired callback must not run")),
        Err(EntityLaneError::StaleFence)
    );
}
