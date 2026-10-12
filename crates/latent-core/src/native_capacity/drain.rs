use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;
use std::task::{Context, Poll};
use std::time::Instant;

use super::{NativeCapacityError, NativeCapacityShutdown, Owner};

/// Single bounded node waiter; detachment cannot refresh the original cutoff or
/// retire any request, accepted worker, native buffer or response frame.
pub struct NativeCapacityDrain<F> {
    owner: Arc<Owner>,
    generation: u64,
    deadline: Instant,
    deadline_wait: Pin<Box<F>>,
    delivered: bool,
}

impl<F: Future<Output = ()>> NativeCapacityDrain<F> {
    pub(super) fn new(
        owner: Arc<Owner>,
        original: Instant,
        deadline_wait: F,
    ) -> Result<Self, NativeCapacityError> {
        let (generation, deadline) = {
            let mut state = owner
                .state
                .lock()
                .map_err(|_| NativeCapacityError::Poisoned)?;
            if state.waiter.is_some() {
                return Err(NativeCapacityError::DrainWaiterBusy);
            }
            let generation = state
                .next_waiter
                .checked_add(1)
                .ok_or(NativeCapacityError::Exhausted)?;
            state.next_waiter = generation;
            state.closed = true;
            let deadline = state
                .shutdown_deadline
                .map_or(original, |old| old.min(original));
            state.shutdown_deadline = Some(deadline);
            state.waiter = Some((generation, None));
            (generation, deadline)
        };
        Ok(Self {
            owner,
            generation,
            deadline,
            deadline_wait: Box::pin(deadline_wait),
            delivered: false,
        })
    }

    fn finish(&mut self, timeout: bool) -> NativeCapacityShutdown {
        let mut state = self.owner.lock_physical();
        let report = state.report(timeout);
        if state
            .waiter
            .as_ref()
            .is_some_and(|(generation, _)| *generation == self.generation)
        {
            state.waiter = None;
        }
        self.delivered = true;
        report
    }
}

impl<F: Future<Output = ()>> Future for NativeCapacityDrain<F> {
    type Output = NativeCapacityShutdown;

    fn poll(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Self::Output> {
        let this = self.get_mut();
        {
            let mut state = this.owner.lock_physical();
            if state.snapshot().physically_retired() {
                drop(state);
                return Poll::Ready(this.finish(false));
            }
            if let Some((generation, waiter)) = state.waiter.as_mut() {
                if *generation == this.generation {
                    *waiter = Some(cx.waker().clone());
                }
            }
        }
        if this.owner.clock.monotonic_now() >= this.deadline
            || this.deadline_wait.as_mut().poll(cx).is_ready()
        {
            Poll::Ready(this.finish(true))
        } else {
            Poll::Pending
        }
    }
}

impl<F> Drop for NativeCapacityDrain<F> {
    fn drop(&mut self) {
        if !self.delivered {
            let mut state = self.owner.lock_physical();
            if state
                .waiter
                .as_ref()
                .is_some_and(|(generation, _)| *generation == self.generation)
            {
                state.waiter = None;
            }
        }
    }
}
