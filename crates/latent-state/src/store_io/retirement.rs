use std::future::Future;
use std::pin::Pin;
use std::sync::{Arc, Mutex};
use std::task::{Context, Poll, Waker};

#[derive(Default)]
struct State {
    completed: bool,
    waiter: Option<Waker>,
}

#[derive(Default)]
pub(super) struct RetirementSignal(Mutex<State>);

impl RetirementSignal {
    pub fn complete(&self) {
        let waiter = {
            let mut state = self
                .0
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            state.completed = true;
            state.waiter.take()
        };
        if let Some(waiter) = waiter {
            waiter.wake();
        }
    }
}

/// One pre-reserved status observer, issued before moving an affine resource.
/// It has no waiter or native handle. Only actual destructor and reservation
/// completion can make `has_retired` positive; elapsed time proves nothing.
pub struct StoreIoRetirementWitness {
    signal: Arc<RetirementSignal>,
}

impl StoreIoRetirementWitness {
    pub(super) fn new(signal: Arc<RetirementSignal>) -> Self {
        Self { signal }
    }

    #[must_use]
    pub fn has_retired(&self) -> bool {
        self.signal
            .0
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .completed
    }
}

/// Pre-reserved actual retirement receipt. Readiness proves the physical worker
/// finished the retained value's destructor and released its owner/byte charge.
/// Dropping this waiter only detaches observation and never cancels retirement.
#[must_use = "await actual retirement before claiming prior physical ownership ended"]
pub struct StoreIoRetirement {
    signal: Arc<RetirementSignal>,
}

impl StoreIoRetirement {
    pub(super) fn new(signal: Arc<RetirementSignal>) -> Self {
        Self { signal }
    }
}

impl Future for StoreIoRetirement {
    type Output = ();

    fn poll(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<()> {
        let mut state = self
            .signal
            .0
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if state.completed {
            Poll::Ready(())
        } else {
            if state
                .waiter
                .as_ref()
                .is_none_or(|waiter| !waiter.will_wake(cx.waker()))
            {
                state.waiter = Some(cx.waker().clone());
            }
            Poll::Pending
        }
    }
}

impl Drop for StoreIoRetirement {
    fn drop(&mut self) {
        let waiter = self
            .signal
            .0
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .waiter
            .take();
        drop(waiter);
    }
}
