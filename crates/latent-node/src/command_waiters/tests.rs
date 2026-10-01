mod bounds;
mod fixture;
mod recovery;

use std::future::Future;
use std::pin::Pin;
use std::sync::{
    atomic::{AtomicUsize, Ordering},
    Arc, Barrier,
};
use std::task::{Context, Poll, Wake, Waker};

use latent_commit::atomic::{inspect, AdmissionDecision, AtomicError, Outcome, PreparedAdmission};
use latent_state::embedded::Family;

use super::*;
use fixture::*;

pub(super) struct CounterWake(pub AtomicUsize);
impl Wake for CounterWake {
    fn wake(self: Arc<Self>) {
        self.0.fetch_add(1, Ordering::SeqCst);
    }
}
pub(super) fn poll(
    waiter: &mut CommandNotificationWaiter,
    waker: &Waker,
) -> Poll<Result<CommandNotification, CommandWaiterError>> {
    Pin::new(waiter).poll(&mut Context::from_waker(waker))
}
pub(super) fn waiting(decision: CommandWaiterDecision) -> CommandNotificationWaiter {
    match decision {
        CommandWaiterDecision::Wait(waiter) => waiter,
        _ => panic!("expected the original live delivery owner"),
    }
}

#[test]
fn actual_concurrent_engine_claims_and_duplicate_waiters_have_one_effect_set() {
    let fixture = Fixture::new();
    let registry = CommandWaiterRegistry::new(CommandWaiterConfig::default()).unwrap();
    let barrier = Barrier::new(2);
    let claims = std::thread::scope(|scope| {
        let threads: Vec<_> = (0..2)
            .map(|_| {
                scope.spawn(|| {
                    let view = fixture.store.snapshot().unwrap();
                    let AdmissionDecision::New(prepared) = PreparedAdmission::prepare(
                        &view,
                        input("same-command"),
                        time(100),
                        permission,
                    )
                    .unwrap() else {
                        panic!("both preparations precede publication")
                    };
                    barrier.wait();
                    prepared.publish(&fixture.store, || Ok(()))
                })
            })
            .collect();
        threads
            .into_iter()
            .map(|thread| thread.join().unwrap())
            .collect::<Vec<_>>()
    });
    assert_eq!(claims.iter().filter(|claim| claim.is_ok()).count(), 1);
    assert_eq!(
        claims
            .iter()
            .filter(|claim| matches!(claim, Err(AtomicError::Conflict)))
            .count(),
        1
    );
    let claim = claims.into_iter().find_map(Result::ok).unwrap();
    let owner = registry.register(&claim).unwrap();
    let mut waiters = std::thread::scope(|scope| {
        // The real engine admits at most eight concurrent read views. Exercise
        // duplicate delivery within that owner instead of assuming unlimited IO.
        let threads: Vec<_> = (0..8)
            .map(|_| {
                scope.spawn(|| {
                    let view = fixture.store.snapshot().unwrap();
                    let AdmissionDecision::Existing(record) = PreparedAdmission::prepare(
                        &view,
                        input("same-command"),
                        time(100),
                        permission,
                    )
                    .unwrap() else {
                        panic!("duplicate must not obtain an executor claim")
                    };
                    waiting(registry.attach(&record, authorize).unwrap())
                })
            })
            .collect();
        threads
            .into_iter()
            .map(|thread| thread.join().unwrap())
            .collect::<Vec<_>>()
    });
    let wake = Arc::new(CounterWake(AtomicUsize::new(0)));
    let waker = Waker::from(Arc::clone(&wake));
    for waiter in &mut waiters {
        assert!(poll(waiter, &waker).is_pending());
    }
    let result = fixture.commit(claim, true);
    assert_eq!(result.outcome(), Outcome::Committed);
    assert_eq!(result.effect_ids().len(), 1);
    owner.notify_reload();
    assert_eq!(wake.0.load(Ordering::SeqCst), 8);
    for waiter in &mut waiters {
        assert_eq!(
            poll(waiter, &waker),
            Poll::Ready(Ok(CommandNotification::ReloadDurableState))
        );
    }
    let view = fixture.store.snapshot().unwrap();
    assert_eq!(
        view.scan(Family::Outbox, b"", 32, 1024 * 1024)
            .unwrap()
            .len(),
        1
    );
    let (retained, result) =
        inspect(&view, &input("same-command").key, time(102), permission).unwrap();
    assert_eq!(retained.effect_ids(), &[retained.effect_id(0)]);
    assert_eq!(result.unwrap().value().unwrap().bytes, b"original-result");
    assert_eq!(registry.snapshot().unwrap().owners, 0);
    assert_eq!(registry.snapshot().unwrap().waiters, 0);
}

#[test]
fn dropping_duplicate_delivery_never_retires_or_cancels_physical_work() {
    let fixture = Fixture::new();
    let registry = CommandWaiterRegistry::new(CommandWaiterConfig::default()).unwrap();
    let claim = fixture.claim("drop-waiter");
    let retirement = claim.retirement();
    let physical = claim.physical_work().unwrap();
    let owner = registry.register(&claim).unwrap();
    let record = fixture.lookup("drop-waiter").0;
    let first = waiting(registry.attach(&record, authorize).unwrap());
    let mut second = waiting(registry.attach(&record, authorize).unwrap());
    drop(first);
    assert_eq!(registry.snapshot().unwrap().waiters, 1);
    assert_eq!(registry.snapshot().unwrap().owners, 1);
    assert!(matches!(
        retirement.proven_noncommit(),
        Err(AtomicError::RecoveryRequired)
    ));
    let waker = Waker::noop();
    assert!(poll(&mut second, waker).is_pending());
    let result = fixture.commit(claim, true);
    physical.retire();
    owner.notify_reload();
    assert_eq!(
        poll(&mut second, waker),
        Poll::Ready(Ok(CommandNotification::ReloadDurableState))
    );
    assert_eq!(
        fixture.lookup("drop-waiter").0.outcome(),
        Outcome::Committed
    );
    assert_eq!(result.effect_ids().len(), 1);
    assert!(matches!(
        retirement.proven_noncommit(),
        Err(AtomicError::RecoveryRequired)
    ));
}

#[test]
fn owner_drop_and_untracked_pending_only_require_authorized_recovery() {
    let fixture = Fixture::new();
    let registry = CommandWaiterRegistry::new(CommandWaiterConfig::default()).unwrap();
    let claim = fixture.claim("lost-owner");
    let retirement = claim.retirement();
    let physical = claim.physical_work().unwrap();
    let record = fixture.lookup("lost-owner").0;
    assert!(matches!(
        registry.attach(&record, authorize).unwrap(),
        CommandWaiterDecision::RecoveryRequired
    ));
    let owner = registry.register(&claim).unwrap();
    let mut waiter = waiting(registry.attach(&record, authorize).unwrap());
    drop(owner);
    assert_eq!(
        poll(&mut waiter, Waker::noop()),
        Poll::Ready(Ok(CommandNotification::ReloadDurableState))
    );
    assert_eq!(fixture.lookup("lost-owner").0.outcome(), Outcome::Pending);
    assert!(matches!(
        registry.attach(&record, authorize).unwrap(),
        CommandWaiterDecision::RecoveryRequired
    ));
    drop(claim);
    assert!(matches!(
        retirement.proven_noncommit(),
        Err(AtomicError::RecoveryRequired)
    ));
    // The notification has no physical retirement port. Only this actual work
    // item's completion enables the atomic owner's existing private proof.
    physical.retire();
    assert!(retirement.proven_noncommit().is_ok());
}
