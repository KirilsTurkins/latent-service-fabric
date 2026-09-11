use std::collections::VecDeque;
use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;
use std::task::{Context, Poll};

use tokio::time::{sleep_until, Instant, Sleep};

use super::state::{destroy, Disposition, Phase, Shared, Work};

struct Running {
    generation: u64,
    work: Work,
    timer: Pin<Box<Sleep>>,
}

pub(super) struct Driver {
    shared: Arc<Shared>,
    batch: VecDeque<usize>,
    running: Vec<Option<Running>>,
    graceful: bool,
}

impl Driver {
    pub fn new(shared: Arc<Shared>, capacity: usize) -> Self {
        Self {
            shared,
            batch: VecDeque::with_capacity(capacity),
            running: (0..capacity).map(|_| None).collect(),
            graceful: false,
        }
    }

    fn accept_batch(&mut self, context: &Context<'_>) {
        // Cloning/dropping a Waker can call arbitrary code. Neither happens
        // under the table lock; registration and queue inspection are atomic.
        let Ok(new_waker) = super::unwind::catch(|| context.waker().clone()) else {
            self.shared.callback_failed();
            return;
        };
        let old_waker = {
            let mut state = self.shared.lock();
            std::mem::swap(&mut state.queue, &mut self.batch);
            state.waker.replace(new_waker)
        };
        if super::unwind::catch(|| drop(old_waker)).is_err() {
            self.shared.callback_failed();
        }
        // Exactly this initial finite batch: concurrent refill waits for the
        // next poll, even when every completion is immediately ready.
        while let Some(index) = self.batch.front().copied() {
            let (generation, work) = {
                let mut state = self.shared.lock();
                let slot = &mut state.slots[index];
                assert_eq!(slot.phase, Phase::Queued);
                let work = slot.work.take().expect("queued lifecycle owner");
                slot.phase = Phase::Running;
                let generation = slot.generation;
                state.snapshot.queued -= 1;
                state.snapshot.running += 1;
                (generation, work)
            };
            let timer = Box::pin(sleep_until(work.deadline));
            self.running[index] = Some(Running {
                generation,
                work,
                timer,
            });
            self.batch.pop_front();
        }
    }

    fn finish(&mut self, index: usize, disposition: Disposition) {
        let running = self.running[index].take().expect("one running owner");
        let key = (index, running.generation);
        let deadline = running.work.deadline;
        // The slot stays charged through arbitrary native/response destruction.
        let mut disposition = destroy(running, disposition);
        if matches!(disposition, Disposition::Completed) && Instant::now() >= deadline {
            disposition = Disposition::TimedOut;
        }
        self.shared.release(key, Phase::Running, Some(disposition));
    }
}

impl Future for Driver {
    type Output = ();

    fn poll(self: Pin<&mut Self>, context: &mut Context<'_>) -> Poll<()> {
        let this = self.get_mut();
        this.accept_batch(context);
        for index in 0..this.running.len() {
            let Some(running) = &mut this.running[index] else {
                continue;
            };
            let result = if Instant::now() >= running.work.deadline {
                Some(Disposition::TimedOut)
            } else {
                match super::unwind::catch(|| running.work.future.as_mut().poll(context)) {
                    Ok(Poll::Ready(())) => Some(Disposition::Completed),
                    Err(()) => Some(Disposition::Panicked),
                    Ok(Poll::Pending) => running
                        .timer
                        .as_mut()
                        .poll(context)
                        .is_ready()
                        .then_some(Disposition::TimedOut),
                }
            };
            if let Some(disposition) = result {
                this.finish(index, disposition);
            }
        }
        let (finished, queued) = {
            let state = this.shared.lock();
            (
                !state.snapshot.accepting
                    && state.snapshot.reserved + state.snapshot.queued + state.snapshot.running
                        == 0,
                !state.queue.is_empty(),
            )
        };
        if finished {
            this.graceful = true;
            Poll::Ready(())
        } else {
            if queued && super::unwind::catch(|| context.waker().wake_by_ref()).is_err() {
                this.shared.callback_failed();
            }
            Poll::Pending
        }
    }
}

impl Drop for Driver {
    fn drop(&mut self) {
        // Seal before extracting any work. Late reserved transfers fall back
        // synchronously, and can never enter an orphaned shared queue.
        let (queued, waker) = {
            let mut state = self.shared.lock();
            state.snapshot.driver_alive = false;
            state.snapshot.accepting = false;
            state.snapshot.failed |= !self.graceful;
            (std::mem::take(&mut state.queue), state.waker.take())
        };
        if super::unwind::catch(|| drop(waker)).is_err() {
            self.shared.callback_failed();
        }
        for index in queued.into_iter().chain(self.batch.drain(..)) {
            let (key, phase, work) = {
                let mut state = self.shared.lock();
                let slot = &mut state.slots[index];
                ((index, slot.generation), slot.phase, slot.work.take())
            };
            let disposition = destroy(work, Disposition::Fallback);
            self.shared.release(key, phase, Some(disposition));
        }
        for index in 0..self.running.len() {
            if self.running[index].is_some() {
                self.finish(index, Disposition::Fallback);
            }
        }
    }
}
