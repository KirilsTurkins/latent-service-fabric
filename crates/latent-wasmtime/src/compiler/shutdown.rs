use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;
use std::task::{Context, Poll};

use latent_core::{BoxFuture, PlatformError};

use super::state::{Core, Phase};
use super::{capacity_error, CompilerPool};

impl<T> Core<T> {
    pub(super) fn fail_worker(&self, worker: usize) {
        self.metrics.update(|snapshot| snapshot.failed = true);
        self.stop();
        let mut state = self.lock();
        let removed = state
            .jobs
            .iter()
            .position(|job| {
                matches!(job.phase,
            Phase::Running(id) | Phase::Finishing(id) if id == worker)
            })
            .map(|index| state.jobs.remove(index));
        if let Some(job) = &removed {
            state.documents -= job.documents;
            state.waiters -= job.waiters.len();
        }
        self.record(&state);
        drop(state);
        let completed_work = removed.is_some();
        drop(removed);
        if completed_work {
            self.metrics
                .record_work_completed_at(std::time::Instant::now());
        }
        self.metrics.notify();
    }

    pub(super) fn stop(&self) {
        let mut state = self.lock();
        state.accepting = false;
        let mut removed = Vec::new();
        let mut waiters = Vec::new();
        let mut index = 0;
        while index < state.jobs.len() {
            let job = &mut state.jobs[index];
            job.abandoned = true;
            if let Some(control) = &job.native_control {
                control.cancel();
            }
            let pending = std::mem::take(&mut job.waiters);
            state.waiters -= pending.len();
            waiters.extend(pending);
            if matches!(state.jobs[index].phase, Phase::Assigned(_) | Phase::Queued) {
                let job = state.jobs.remove(index);
                state.documents -= job.documents;
                removed.push(job);
                self.metrics
                    .update(|s| s.jobs_abandoned = s.jobs_abandoned.saturating_add(1));
            } else {
                index += 1;
            }
        }
        self.record(&state);
        drop(state);
        drop(removed);
        let mut wakers = Vec::new();
        for waiter in waiters {
            let mut data = waiter
                .state
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            let permit = data.permit.take();
            let previous = data
                .result
                .replace(Err(capacity_error("compiler-stopping")));
            if let Some(waker) = data.waker.take() {
                wakers.push(waker);
            }
            drop(data);
            drop(previous);
            drop(permit);
        }
        super::wake(wakers);
        self.metrics.notify();
        self.wake.notify_all();
    }
}

impl<T: Send + Sync + 'static> CompilerPool<T> {
    pub(crate) fn quiesce(&self) -> BoxFuture<'_, Result<(), PlatformError>> {
        self.core.stop();
        Box::pin(Quiesce {
            core: Arc::clone(&self.core),
            registration: None,
        })
    }

    pub(crate) fn stop_and_join(&mut self) -> Result<(), PlatformError> {
        // Arbitrary trusted host callbacks can release their final runtime
        // owner on this worker. Synchronous Drop cannot join its own thread.
        // Fail before callbacks, moving handles or peer joins; never detach or
        // pretend this unsupported embedding lifecycle shut down cleanly.
        let current = std::thread::current().id();
        if self
            .workers
            .iter()
            .any(|worker| worker.thread().id() == current)
        {
            std::process::abort();
        }
        self.core.stop();
        let mut failed = self.core.metrics.snapshot().failed;
        for worker in self.workers.drain(..) {
            if worker.join().is_err() {
                failed = true;
            }
            self.core
                .metrics
                .update(|s| s.workers_joined = s.workers_joined.saturating_add(1));
        }
        self.core.metrics.notify();
        failed |= self.core.metrics.snapshot().failed;
        if failed {
            self.core.metrics.update(|s| s.failed = true);
            return Err(capacity_error("compiler-thread-panicked"));
        }
        Ok(())
    }
}

impl<T: Send + Sync + 'static> Drop for CompilerPool<T> {
    fn drop(&mut self) {
        let _ = self.stop_and_join();
    }
}

struct Quiesce<T> {
    core: Arc<Core<T>>,
    registration: Option<u64>,
}

impl<T> Future for Quiesce<T> {
    type Output = Result<(), PlatformError>;

    fn poll(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Self::Output> {
        let this = self.get_mut();
        let incoming = cx.waker().clone();
        let mut state = this.core.lock();
        if state.quiescent == this.core.metrics.snapshot().maximum_workers {
            return Poll::Ready(Ok(()));
        }
        if state
            .shutdown_waiter
            .as_ref()
            .is_some_and(|(id, _)| Some(*id) != this.registration)
        {
            return Poll::Ready(Err(capacity_error("compiler-shutdown-waiter-capacity")));
        }
        let id = if let Some(id) = this.registration {
            id
        } else {
            let Some(next) = state.next_shutdown_waiter.checked_add(1) else {
                return Poll::Ready(Err(capacity_error(
                    "compiler-shutdown-generation-exhausted",
                )));
            };
            state.next_shutdown_waiter = next;
            this.registration = Some(next);
            next
        };
        let previous = state.shutdown_waiter.replace((id, incoming));
        drop(state);
        drop(previous);
        Poll::Pending
    }
}

impl<T> Drop for Quiesce<T> {
    fn drop(&mut self) {
        let mut state = self.core.lock();
        let previous = if state
            .shutdown_waiter
            .as_ref()
            .is_some_and(|(id, _)| Some(*id) == self.registration)
        {
            state.shutdown_waiter.take()
        } else {
            None
        };
        drop(state);
        drop(previous);
    }
}
