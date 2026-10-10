use std::sync::{
    atomic::{AtomicUsize, Ordering},
    Arc, Barrier,
};
use std::task::{Poll, Wake, Waker};

use latent_commit::atomic::{AdmissionDecision, AtomicError, PreparedAdmission};

use super::{fixture::*, poll, waiting};
use crate::command_waiters::*;

#[test]
fn capacity_rejects_without_eviction_and_notified_slots_wait_for_delivery_retirement() {
    let fixture = Fixture::new();
    let registry = CommandWaiterRegistry::new(CommandWaiterConfig {
        maximum_owners: 1,
        maximum_waiters: 2,
        maximum_waiters_per_attempt: 2,
        ..CommandWaiterConfig::default()
    })
    .unwrap();
    let resident = registry.snapshot().unwrap().resident_bytes;
    let first = fixture.claim("capacity-first");
    let owner = registry.register(&first).unwrap();
    let mut a = waiting(registry.attach(first.record(), authorize).unwrap());
    let b = waiting(registry.attach(first.record(), authorize).unwrap());
    assert!(matches!(
        registry.attach(first.record(), authorize),
        Err(CommandWaiterError::Capacity)
    ));
    let second = fixture.claim("capacity-second");
    assert!(matches!(
        registry.register(&second),
        Err(CommandWaiterError::Capacity)
    ));
    assert!(matches!(
        registry.attach(second.record(), authorize).unwrap(),
        CommandWaiterDecision::RecoveryRequired
    ));
    assert_eq!(registry.snapshot().unwrap().waiters, 2);
    owner.notify_reload();
    assert_eq!(registry.snapshot().unwrap().waiters, 2);
    let second_owner = registry.register(&second).unwrap();
    assert!(matches!(
        registry.attach(second.record(), authorize),
        Err(CommandWaiterError::Capacity)
    ));
    assert!(poll(&mut a, Waker::noop()).is_ready());
    let c = waiting(registry.attach(second.record(), authorize).unwrap());
    drop(b);
    assert_eq!(registry.snapshot().unwrap().waiters, 1);
    drop(c);
    drop(second_owner);
    assert_eq!(registry.snapshot().unwrap().waiters, 0);
    assert_eq!(registry.snapshot().unwrap().resident_bytes, resident);
    assert_eq!(
        fixture.lookup("capacity-first").0.outcome(),
        latent_commit::atomic::Outcome::Pending
    );
    assert_eq!(
        fixture.lookup("capacity-second").0.outcome(),
        latent_commit::atomic::Outcome::Pending
    );
}

#[test]
fn per_attempt_capacity_and_reused_slots_keep_late_delivery_handles_isolated() {
    let fixture = Fixture::new();
    let registry = CommandWaiterRegistry::new(CommandWaiterConfig {
        maximum_owners: 2,
        maximum_waiters: 4,
        maximum_waiters_per_attempt: 1,
        ..CommandWaiterConfig::default()
    })
    .unwrap();
    let first = fixture.claim("old-slot");
    let owner = registry.register(&first).unwrap();
    assert!(matches!(
        registry.register(&first),
        Err(CommandWaiterError::DuplicateOwner)
    ));
    let mut old_waiter = waiting(registry.attach(first.record(), authorize).unwrap());
    assert!(matches!(
        registry.attach(first.record(), authorize),
        Err(CommandWaiterError::Capacity)
    ));
    owner.notify_reload();
    assert!(poll(&mut old_waiter, Waker::noop()).is_ready());
    let next = fixture.claim("new-slot");
    let next_owner = registry.register(&next).unwrap();
    let mut next_waiter = waiting(registry.attach(next.record(), authorize).unwrap());
    assert_eq!(
        poll(&mut old_waiter, Waker::noop()),
        Poll::Ready(Err(CommandWaiterError::Unavailable))
    );
    drop(old_waiter);
    assert_eq!(registry.snapshot().unwrap().waiters, 1);
    assert!(poll(&mut next_waiter, Waker::noop()).is_pending());
    next_owner.notify_reload();
    assert!(poll(&mut next_waiter, Waker::noop()).is_ready());
}

#[test]
fn configuration_and_full_width_generation_exhaustion_fail_before_slot_mutation() {
    for config in [
        CommandWaiterConfig {
            maximum_owners: 0,
            ..CommandWaiterConfig::default()
        },
        CommandWaiterConfig {
            maximum_waiters: usize::MAX,
            ..CommandWaiterConfig::default()
        },
        CommandWaiterConfig {
            maximum_waiters_per_attempt: 129,
            ..CommandWaiterConfig::default()
        },
        CommandWaiterConfig {
            maximum_resident_bytes: u64::MAX,
            ..CommandWaiterConfig::default()
        },
    ] {
        assert!(matches!(
            CommandWaiterRegistry::new(config),
            Err(CommandWaiterError::InvalidConfiguration)
        ));
    }
    assert!(matches!(
        CommandWaiterRegistry::new(CommandWaiterConfig {
            maximum_resident_bytes: 1,
            ..CommandWaiterConfig::default()
        }),
        Err(CommandWaiterError::Capacity)
    ));
    let fixture = Fixture::new();
    let registry = CommandWaiterRegistry::new(CommandWaiterConfig::default()).unwrap();
    let claim = fixture.claim("overflow");
    for exhausted in [0, u64::MAX] {
        registry.inner.lock().unwrap().next_generation = exhausted;
        assert!(matches!(
            registry.register(&claim),
            Err(CommandWaiterError::Exhausted)
        ));
        assert_eq!(registry.snapshot().unwrap().owners, 0);
    }
    registry.inner.lock().unwrap().next_generation = u64::MAX - 1;
    let owner = registry.register(&claim).unwrap();
    assert!(matches!(
        registry.attach(claim.record(), authorize),
        Err(CommandWaiterError::Exhausted)
    ));
    assert_eq!(registry.snapshot().unwrap().waiters, 0);
    drop(owner);
}

struct ReenterWake {
    registry: CommandWaiterRegistry,
    wakes: AtomicUsize,
    panic: bool,
}
impl Wake for ReenterWake {
    fn wake(self: Arc<Self>) {
        assert!(
            self.registry.inner.state.try_lock().is_ok(),
            "wakers must run outside the table lock"
        );
        self.wakes.fetch_add(1, Ordering::SeqCst);
        assert!(!self.panic, "intentional executor callback panic");
    }
}

#[test]
fn reentrant_or_panicking_wake_callbacks_cannot_hold_locks_or_lose_other_hints() {
    let fixture = Fixture::new();
    let registry = CommandWaiterRegistry::new(CommandWaiterConfig::default()).unwrap();
    let claim = fixture.claim("wake");
    let owner = registry.register(&claim).unwrap();
    let mut a = waiting(registry.attach(claim.record(), authorize).unwrap());
    let mut b = waiting(registry.attach(claim.record(), authorize).unwrap());
    let hostile = Arc::new(ReenterWake {
        registry: registry.clone(),
        wakes: AtomicUsize::new(0),
        panic: true,
    });
    let normal = Arc::new(ReenterWake {
        registry: registry.clone(),
        wakes: AtomicUsize::new(0),
        panic: false,
    });
    assert!(poll(&mut a, &Waker::from(Arc::clone(&hostile))).is_pending());
    assert!(poll(&mut b, &Waker::from(Arc::clone(&normal))).is_pending());
    drop(owner);
    assert_eq!(hostile.wakes.load(Ordering::SeqCst), 1);
    assert_eq!(normal.wakes.load(Ordering::SeqCst), 1);
    assert!(poll(&mut a, Waker::noop()).is_ready());
    assert!(poll(&mut b, Waker::noop()).is_ready());
    assert_eq!(registry.snapshot().unwrap().waiters, 0);
}

#[test]
fn attach_racing_finish_has_no_lost_notification_or_reexecution_permission() {
    let fixture = Fixture::new();
    let registry = CommandWaiterRegistry::new(CommandWaiterConfig::default()).unwrap();
    for index in 0..16 {
        let claim = fixture.claim(&format!("race-{index}"));
        let owner = registry.register(&claim).unwrap();
        let barrier = Barrier::new(2);
        let decision = std::thread::scope(|scope| {
            let thread = scope.spawn(|| {
                barrier.wait();
                registry.attach(claim.record(), authorize).unwrap()
            });
            barrier.wait();
            owner.notify_reload();
            thread.join().unwrap()
        });
        match decision {
            CommandWaiterDecision::Wait(mut waiter) => {
                assert!(poll(&mut waiter, Waker::noop()).is_ready());
            }
            CommandWaiterDecision::RecoveryRequired => {}
            CommandWaiterDecision::ReloadDurableState => {
                panic!("still-pending record remains pending")
            }
        }
        assert_eq!(registry.snapshot().unwrap().waiters, 0);
        assert_eq!(
            claim.record().outcome(),
            latent_commit::atomic::Outcome::Pending
        );
    }
}

#[test]
fn conflicting_durable_fingerprints_cannot_join_or_replace_an_original_delivery() {
    let fixture = Fixture::new();
    let registry = CommandWaiterRegistry::new(CommandWaiterConfig::default()).unwrap();
    let claim = fixture.claim("conflict");
    let owner = registry.register(&claim).unwrap();
    let waiter = waiting(registry.attach(claim.record(), authorize).unwrap());
    let mut changed = input("conflict");
    changed.fingerprint.input = value(b"changed-input");
    assert!(matches!(
        PreparedAdmission::prepare(
            &fixture.store.snapshot().unwrap(),
            changed,
            time(100),
            permission
        ),
        Err(AtomicError::Conflict)
    ));
    let another_engine = Fixture::new();
    let mut incompatible = input("conflict");
    incompatible.fingerprint.input = value(b"changed-input");
    let other_claim = another_engine.claim_input(incompatible);
    assert!(matches!(
        registry.attach(other_claim.record(), authorize),
        Err(CommandWaiterError::Conflict)
    ));
    assert_eq!(registry.snapshot().unwrap().owners, 1);
    assert_eq!(registry.snapshot().unwrap().waiters, 1);
    let AdmissionDecision::Existing(existing) = PreparedAdmission::prepare(
        &fixture.store.snapshot().unwrap(),
        input("conflict"),
        time(100),
        permission,
    )
    .unwrap() else {
        panic!("original command retains its owner")
    };
    assert_eq!(existing.fingerprint(), claim.record().fingerprint());
    drop(waiter);
    drop(owner);
}

#[test]
fn fixed_resident_tables_survive_registry_drop_until_the_last_delivery_owner_retires() {
    let fixture = Fixture::new();
    let registry = CommandWaiterRegistry::new(CommandWaiterConfig::default()).unwrap();
    let claim = fixture.claim("resident");
    let owner = registry.register(&claim).unwrap();
    let waiter = waiting(registry.attach(claim.record(), authorize).unwrap());
    let weak = Arc::downgrade(&registry.inner);
    drop(registry);
    assert!(weak.upgrade().is_some());
    drop(waiter);
    assert!(weak.upgrade().is_some());
    drop(owner);
    assert!(weak.upgrade().is_none());
    assert_eq!(
        claim.record().outcome(),
        latent_commit::atomic::Outcome::Pending
    );
}
