//! Bounded, cancellation-safe coordination at committed test transitions.
//!
//! A stage is recorded *after* the subsystem operation commits. A pause ticket
//! witnesses the current parked future, not a historical arrival. Only the
//! owner wrapper can publish retirement, after dropping its owned value.

mod rendezvous;
mod watchdog;

pub use rendezvous::{
    CoordinationError, PauseTicket, Registration, Rendezvous, Snapshot, Stage, Tracked,
};
pub use watchdog::{with_watchdog, WATCHDOG};

use std::future::Future;
use std::pin::Pin;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use std::task::{Context, Poll, Wake, Waker};

#[derive(Debug, Default)]
struct WakeCount(AtomicUsize);

impl Wake for WakeCount {
    fn wake(self: Arc<Self>) {
        self.0.fetch_add(1, Ordering::SeqCst);
    }
    fn wake_by_ref(self: &Arc<Self>) {
        self.0.fetch_add(1, Ordering::SeqCst);
    }
}

/// One explicit poll establishes readiness without spawning, sleeping or yielding.
/// `Pending` alone is not a queue witness: also assert the subsystem's live state.
#[derive(Debug, Default)]
pub struct PollProbe(Arc<WakeCount>);

impl PollProbe {
    pub fn poll<F: Future + ?Sized>(&self, future: Pin<&mut F>) -> Poll<F::Output> {
        let waker = Waker::from(Arc::clone(&self.0));
        future.poll(&mut Context::from_waker(&waker))
    }

    pub fn pending<F: Future + ?Sized>(&self, future: Pin<&mut F>) {
        assert!(
            self.poll(future).is_pending(),
            "expected a pending, registered future"
        );
    }

    // For unit-output futures the readiness assertion itself is the result.
    #[allow(clippy::must_use_candidate)]
    pub fn ready<F: Future + ?Sized>(&self, future: Pin<&mut F>) -> F::Output {
        match self.poll(future) {
            Poll::Ready(value) => value,
            Poll::Pending => panic!("expected the committed transition to be ready"),
        }
    }

    #[must_use]
    pub fn wakes(&self) -> usize {
        self.0 .0.load(Ordering::SeqCst)
    }
}

#[cfg(test)]
mod identity_tests;
#[cfg(test)]
mod tests;
