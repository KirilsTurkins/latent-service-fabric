use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::task::Waker;

use latent_core::ActivationId;

use super::{observe, Context, Future, Pin, Poll, RawInvocationInput};
use crate::invocation_input_observer::{
    InvocationInputDropReason, InvocationInputObserver, InvocationInputPhase,
};

fn session() -> (
    InvocationInputObserver,
    crate::invocation_input_observer::InvocationObservation,
) {
    let observer = InvocationInputObserver::new();
    let id = ActivationId("input-owner".to_owned());
    observer.enable(std::slice::from_ref(&id)).unwrap();
    let observation = observer.begin(&id).unwrap();
    (observer, observation)
}

struct Payload {
    bytes: Vec<u8>,
    observer: InvocationInputObserver,
    dropped: Arc<AtomicBool>,
}

impl Drop for Payload {
    fn drop(&mut self) {
        let snapshot = self.observer.snapshot();
        assert_eq!(snapshot.live_raw_owners, 1);
        assert_eq!(
            snapshot.live_raw_capacity_bytes,
            u64::try_from(self.bytes.capacity()).unwrap()
        );
        assert!(!snapshot
            .records
            .iter()
            .any(|record| record.phase == InvocationInputPhase::RawOwnerDropped));
        self.dropped.store(true, Ordering::Release);
    }
}

#[test]
fn actual_owned_field_is_destroyed_before_its_raw_guard_refunds() {
    for reason in [
        InvocationInputDropReason::OwnerScopeExit,
        InvocationInputDropReason::BeforeGuestCall,
    ] {
        let (observer, observation) = session();
        let bytes = vec![1_u8, 2, 3];
        let guard = observation.trace().raw_owner(bytes.len(), bytes.capacity());
        let dropped = Arc::new(AtomicBool::new(false));
        let raw = RawInvocationInput {
            bytes: Payload {
                bytes,
                observer: observer.clone(),
                dropped: dropped.clone(),
            },
            observation: guard,
        };
        raw.release(reason);
        assert!(dropped.load(Ordering::Acquire));
        let snapshot = observer.snapshot();
        assert_eq!(snapshot.live_raw_owners, 0);
        assert_eq!(
            snapshot.records[1].phase,
            InvocationInputPhase::RawOwnerDropped
        );
        assert_eq!(snapshot.records[1].drop_reason, Some(reason));
        drop(observation);
        assert!(!observer.snapshot().overflowed);
    }
}

struct OwnedFuture {
    raw: RawInvocationInput,
    observer: InvocationInputObserver,
    completed: bool,
    panic: bool,
    destroyed: Arc<AtomicBool>,
}

impl Future for OwnedFuture {
    type Output = ();

    fn poll(self: Pin<&mut Self>, _: &mut Context<'_>) -> Poll<()> {
        assert!(!self.panic, "test invocation poll panic");
        if self.completed {
            Poll::Ready(())
        } else {
            Poll::Pending
        }
    }
}

impl Drop for OwnedFuture {
    fn drop(&mut self) {
        let snapshot = self.observer.snapshot();
        assert_eq!(
            snapshot.live_invocations, 1,
            "the actual future still owns its input"
        );
        assert_eq!(snapshot.live_raw_owners, 1);
        assert_eq!(self.raw.bytes(), &[4, 5, 6]);
        self.destroyed.store(true, Ordering::Release);
    }
}

#[test]
fn completion_abandonment_and_poll_unwind_retire_after_actual_future_destruction() {
    for (completed, panic) in [(true, false), (false, false), (false, true)] {
        let (observer, observation) = session();
        let trace = observation.trace();
        let bytes = vec![4, 5, 6];
        let pointer = bytes.as_ptr();
        let raw = RawInvocationInput::new(bytes, Some(&trace));
        assert_eq!(
            raw.bytes().as_ptr(),
            pointer,
            "instrumentation moves the actual vector"
        );
        let destroyed = Arc::new(AtomicBool::new(false));
        let future = OwnedFuture {
            raw,
            observer: observer.clone(),
            completed,
            panic,
            destroyed: destroyed.clone(),
        };
        let mut future = Box::pin(observe(future, observation));
        let polled = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            future
                .as_mut()
                .poll(&mut Context::from_waker(Waker::noop()))
        }));
        if panic {
            assert!(polled.is_err());
        } else {
            assert_eq!(polled.unwrap().is_ready(), completed);
        }
        drop(future);
        assert!(destroyed.load(Ordering::Acquire));
        let snapshot = observer.snapshot();
        assert!(!snapshot.overflowed);
        assert_eq!(
            (snapshot.live_invocations, snapshot.live_raw_owners),
            (0, 0)
        );
        assert_eq!(snapshot.records.len(), 3);
        assert_eq!(
            snapshot.records[1].phase,
            InvocationInputPhase::RawOwnerDropped
        );
        assert_eq!(
            snapshot.records[2].phase,
            if completed {
                InvocationInputPhase::InvocationFinished
            } else {
                InvocationInputPhase::InvocationDropped
            }
        );
    }
}

#[test]
fn error_before_guest_dispatch_releases_input_without_inventing_guest_start() {
    let (observer, observation) = session();
    let trace = observation.trace();
    let raw = RawInvocationInput::new(vec![0xff], Some(&trace));
    let mut future = Box::pin(observe(
        async move {
            let result = std::str::from_utf8(raw.bytes()).map(|_| ());
            assert!(result.is_err());
            drop(raw);
            Err::<(), _>("decode failed")
        },
        observation,
    ));
    assert!(future
        .as_mut()
        .poll(&mut Context::from_waker(Waker::noop()))
        .is_ready());
    drop(future);
    let snapshot = observer.snapshot();
    assert!(!snapshot.overflowed);
    assert_eq!(snapshot.finished_invocations, 1);
    assert_eq!(snapshot.live_raw_owners, 0);
    assert!(!snapshot
        .records
        .iter()
        .any(|record| record.phase == InvocationInputPhase::GuestCallStart));
}
