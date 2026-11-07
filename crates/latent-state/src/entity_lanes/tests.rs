use std::time::{Duration, Instant};

use latent_core::test_support::TestClock;
use latent_core::{ActivationClock, EntityKey, StateNamespaceId, TenantId};

use super::*;

mod bounds;
mod fairness;
mod lifecycle;

#[test]
fn dispatcher_wakes_only_after_actual_owner_retirement_and_tracks_wait_deadlines() {
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::Arc;
    use std::task::{Wake, Waker};

    struct Signal(AtomicUsize);
    impl Wake for Signal {
        fn wake(self: Arc<Self>) {
            self.0.fetch_add(1, Ordering::SeqCst);
        }
    }

    let signal = Arc::new(Signal(AtomicUsize::new(0)));
    let waker = Waker::from(Arc::clone(&signal));
    let lanes = EntityLanes::new(limits()).unwrap();
    let now = Instant::now();
    let idle = lanes.register_dispatch_waker(now, &waker).unwrap();
    assert!(!idle.ready && idle.next_deadline.is_none());
    assert!(!lanes
        .clear_dispatch_waker(std::task::Waker::noop())
        .unwrap());
    let first = enqueue(&lanes, "tenant-a", "order", 1, now);
    assert_eq!(signal.0.load(Ordering::SeqCst), 1);
    let running = start(&lanes, now);
    let physical = running.retain_physical_owner();
    let second = enqueue(&lanes, "tenant-a", "order", 2, now);
    let waiting = lanes.register_dispatch_waker(now, &waker).unwrap();
    assert!(!waiting.ready);
    assert_eq!(waiting.next_deadline, Some(now + Duration::from_secs(10)));
    drop(running);
    assert_eq!(signal.0.load(Ordering::SeqCst), 1);
    drop(physical);
    assert_eq!(signal.0.load(Ordering::SeqCst), 2);
    assert!(lanes.register_dispatch_waker(now, &waker).unwrap().ready);
    let next = start(&lanes, now);
    drop((first, second, next));
    assert_empty(&lanes);
}

#[test]
fn dispatcher_registration_is_released_only_by_its_matching_driver() {
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::Arc;
    use std::task::{Wake, Waker};

    struct Signal(AtomicUsize);
    impl Wake for Signal {
        fn wake(self: Arc<Self>) {
            self.0.fetch_add(1, Ordering::SeqCst);
        }
    }
    let owner = Arc::new(Signal(AtomicUsize::new(0)));
    let weak = Arc::downgrade(&owner);
    let waker = Waker::from(owner);
    let lanes: EntityLanes<()> = EntityLanes::new(limits()).unwrap();
    assert!(
        !lanes
            .register_dispatch_waker(Instant::now(), &waker)
            .unwrap()
            .ready
    );
    assert!(!lanes.clear_dispatch_waker(Waker::noop()).unwrap());
    assert!(lanes.clear_dispatch_waker(&waker).unwrap());
    drop(waker);
    assert!(weak.upgrade().is_none());
}

#[test]
fn concurrent_registration_and_enqueue_never_lose_the_dispatch_signal() {
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::{Arc, Barrier};
    use std::task::{Wake, Waker};

    struct Signal(AtomicUsize);
    impl Wake for Signal {
        fn wake(self: Arc<Self>) {
            self.0.fetch_add(1, Ordering::SeqCst);
        }
    }
    for iteration in 0..100 {
        let lanes = EntityLanes::new(limits()).unwrap();
        let signal = Arc::new(Signal(AtomicUsize::new(0)));
        let waker = Waker::from(Arc::clone(&signal));
        let barrier = Arc::new(Barrier::new(2));
        let worker_lanes = lanes.clone();
        let worker_barrier = Arc::clone(&barrier);
        let now = Instant::now();
        let worker = std::thread::spawn(move || {
            worker_barrier.wait();
            enqueue(&worker_lanes, "tenant-a", "order", iteration, now)
        });
        barrier.wait();
        let observed = lanes.register_dispatch_waker(now, &waker).unwrap();
        let waiter = worker.join().unwrap();
        assert!(observed.ready || signal.0.load(Ordering::SeqCst) > 0);
        assert!(lanes.register_dispatch_waker(now, &waker).unwrap().ready);
        drop(waiter);
        assert_empty(&lanes);
    }
}

#[test]
fn dispatcher_wake_can_observe_lane_state_without_reentering_its_lock() {
    use std::sync::atomic::{AtomicBool, Ordering};
    use std::sync::{Arc, Weak};
    use std::task::{Wake, Waker};

    struct Probe {
        lanes: Weak<Inner<()>>,
        observed: AtomicBool,
    }
    impl Wake for Probe {
        fn wake(self: Arc<Self>) {
            let lanes = self.lanes.upgrade().unwrap();
            self.observed
                .store(lanes.state.try_lock().is_ok(), Ordering::SeqCst);
        }
    }
    let lanes = EntityLanes::new(limits()).unwrap();
    let probe = Arc::new(Probe {
        lanes: Arc::downgrade(&lanes.inner),
        observed: AtomicBool::new(false),
    });
    let waker = Waker::from(Arc::clone(&probe));
    let now = Instant::now();
    assert!(!lanes.register_dispatch_waker(now, &waker).unwrap().ready);
    let waiter = lanes
        .enqueue(request(scope("tenant-a", "order", 1), 1, (), now), now)
        .unwrap();
    assert!(probe.observed.load(Ordering::SeqCst));
    drop(waiter);
    assert_empty(&lanes);
}

#[test]
fn poisoned_lane_retirement_wakes_the_dispatcher_to_observe_failure() {
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::Arc;
    use std::task::{Wake, Waker};

    struct Signal(AtomicUsize);
    impl Wake for Signal {
        fn wake(self: Arc<Self>) {
            self.0.fetch_add(1, Ordering::SeqCst);
        }
    }
    let lanes = EntityLanes::new(limits()).unwrap();
    let now = Instant::now();
    let first = enqueue(&lanes, "tenant-a", "order", 1, now);
    let active = start(&lanes, now);
    let second = enqueue(&lanes, "tenant-a", "order", 2, now);
    let signal = Arc::new(Signal(AtomicUsize::new(0)));
    let waker = Waker::from(Arc::clone(&signal));
    assert!(!lanes.register_dispatch_waker(now, &waker).unwrap().ready);
    let poisoned = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        let _guard = lanes.inner.state.lock().unwrap();
        panic!("inject lane table poison");
    }));
    assert!(poisoned.is_err());
    drop(active);
    assert_eq!(signal.0.load(Ordering::SeqCst), 1);
    assert_eq!(
        lanes.register_dispatch_waker(now, &waker),
        Err(EntityLaneError::Poisoned)
    );
    drop((first, second));
}

#[test]
fn dispatcher_observes_expiry_even_when_global_execution_capacity_is_full() {
    let mut capacity = limits();
    capacity.global_active = 1;
    let lanes = EntityLanes::new(capacity).unwrap();
    let now = Instant::now();
    let first = enqueue(&lanes, "tenant-a", "first", 1, now);
    let active = start(&lanes, now);
    let second = enqueue(&lanes, "tenant-b", "second", 2, now);
    let waker = std::task::Waker::noop();
    let waiting = lanes.register_dispatch_waker(now, waker).unwrap();
    assert!(!waiting.ready);
    let deadline = waiting.next_deadline.unwrap();
    assert!(
        lanes
            .register_dispatch_waker(deadline, waker)
            .unwrap()
            .ready
    );
    assert!(matches!(
        lanes.try_start_next(deadline, |_, _| true).unwrap(),
        Some(EntityDispatch::Rejected(_))
    ));
    drop((first, second, active));
    assert_empty(&lanes);
}

#[derive(Clone, Debug, PartialEq, Eq)]
struct Command {
    publication: &'static str,
    attempt: u64,
}

fn limits() -> EntityLaneLimits {
    EntityLaneLimits {
        global_queued: 64,
        tenant_queued: 32,
        entity_queued: 16,
        global_keys: 32,
        tenant_keys: 16,
        global_active: 4,
        tenant_active: 2,
        global_bytes: 1_000_000,
        tenant_bytes: 500_000,
        entity_bytes: 100_000,
        scope_bytes: 256,
        command_identity_bytes: 128,
        maximum_wait_age: Duration::from_secs(10),
    }
}

fn scope(tenant: &str, entity: &str, incarnation: u64) -> EntityScope {
    EntityScope::new(
        TenantId(tenant.into()),
        StateNamespaceId("orders".into()),
        incarnation,
        EntityKey(entity.into()),
    )
    .unwrap()
}

fn request<T>(scope: EntityScope, id: u64, payload: T, now: Instant) -> EntityLaneRequest<T> {
    EntityLaneRequest::new(
        scope,
        id.to_be_bytes().to_vec(),
        payload,
        32,
        now + Duration::from_mins(1),
        EntityCallKind::Root,
    )
}

fn enqueue(
    lanes: &EntityLanes<Command>,
    tenant: &str,
    entity: &str,
    id: u64,
    now: Instant,
) -> EntityWaiter<Command> {
    lanes
        .enqueue(
            request(
                scope(tenant, entity, 1),
                id,
                Command {
                    publication: "publication-A",
                    attempt: id,
                },
                now,
            ),
            now,
        )
        .unwrap()
}

fn start<T>(lanes: &EntityLanes<T>, now: Instant) -> EntityExecution<T> {
    match lanes
        .try_start_next(now, |_, _| true)
        .unwrap()
        .expect("ready dispatch")
    {
        EntityDispatch::Ready(execution) => execution,
        EntityDispatch::Rejected(_) => panic!("unexpected queue rejection"),
    }
}

fn assert_empty<T>(lanes: &EntityLanes<T>) {
    assert_eq!(lanes.snapshot().unwrap(), EntityLaneSnapshot::default());
    assert_eq!(lanes.inner.state.lock().unwrap().ready.capacity(), 0);
}

fn clock() -> TestClock {
    TestClock::new(1_000, Instant::now(), 1)
}
