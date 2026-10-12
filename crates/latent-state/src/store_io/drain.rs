use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;
use std::task::{Context, Poll};
use std::time::Instant;

use super::state::Control;
use super::{StoreIoError, StoreIoShutdown};

/// Single node shutdown waiter; physical workers and the engine own themselves.
/// The node supplies a deadline future from its existing absolute clock driver.
pub struct StoreIoDrain<S, F> {
    control: Arc<Control<S>>,
    generation: u64,
    deadline: Instant,
    deadline_wait: Pin<Box<F>>,
    delivered: bool,
}

impl<S, F: Future<Output = ()>> StoreIoDrain<S, F> {
    pub(super) fn new(
        control: Arc<Control<S>>,
        deadline: Instant,
        deadline_wait: F,
    ) -> Result<Self, StoreIoError> {
        let generation = {
            let mut state = control.state.lock().map_err(|_| StoreIoError::Poisoned)?;
            if state.drain_waiter.is_some() {
                return Err(StoreIoError::DrainWaiterBusy);
            }
            let generation = state
                .next_drain
                .checked_add(1)
                .ok_or(StoreIoError::Exhausted)?;
            state.next_drain = generation;
            state.drain_waiter = Some((generation, None));
            state.closed = true;
            state.shutdown_deadline = Some(
                state
                    .shutdown_deadline
                    .map_or(deadline, |original| original.min(deadline)),
            );
            generation
        };
        control.notify();
        Ok(Self {
            control,
            generation,
            deadline,
            deadline_wait: Box::pin(deadline_wait),
            delivered: false,
        })
    }

    fn finish(&mut self, timeout: bool) -> StoreIoShutdown {
        let mut state = self
            .control
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if timeout && !state.snapshot().physically_retired() {
            state.quarantined = true;
        }
        let report = state.shutdown_report(self.deadline);
        if state
            .drain_waiter
            .as_ref()
            .is_some_and(|(generation, _)| *generation == self.generation)
        {
            state.drain_waiter = None;
        }
        self.delivered = true;
        drop(state);
        self.control.notify();
        report
    }
}

impl<S, F: Future<Output = ()>> Future for StoreIoDrain<S, F> {
    type Output = StoreIoShutdown;

    fn poll(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Self::Output> {
        let this = self.get_mut();
        let now = this.control.clock.monotonic_now();
        {
            let mut state = this
                .control
                .state
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            if state.snapshot().physically_retired() {
                drop(state);
                return Poll::Ready(this.finish(false));
            }
            if let Some((generation, waker)) = state.drain_waiter.as_mut() {
                if *generation == this.generation {
                    *waker = Some(cx.waker().clone());
                }
            }
        }
        if now >= this.deadline || this.deadline_wait.as_mut().poll(cx).is_ready() {
            Poll::Ready(this.finish(true))
        } else {
            Poll::Pending
        }
    }
}

impl<S, F> Drop for StoreIoDrain<S, F> {
    fn drop(&mut self) {
        if !self.delivered {
            let mut state = self
                .control
                .state
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            if state
                .drain_waiter
                .as_ref()
                .is_some_and(|(generation, _)| *generation == self.generation)
            {
                state.drain_waiter = None;
            }
        }
    }
}
