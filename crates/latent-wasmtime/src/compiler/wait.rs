use std::future::Future;
use std::pin::Pin;
use std::sync::atomic::Ordering;
use std::sync::Arc;
use std::task::{Context, Poll};

use latent_core::PlatformError;

use super::state::{Core, Phase, Waiter};
use super::{capacity_error, ReadyPin, Task};
use crate::cache::PrepareReservation;

pub(crate) struct PreparationWait<T: Send + Sync + 'static> {
    core: Arc<Core<T>>,
    job: u64,
    waiter: Arc<Waiter<T>>,
}

impl<T: Send + Sync + 'static> PreparationWait<T> {
    pub(crate) fn reserve_documents(&self, bytes: usize) -> Result<(), PlatformError> {
        let mut state = self.core.lock();
        if !state.accepting {
            return Err(capacity_error("compiler-stopping"));
        }
        if bytes
            > self
                .core
                .metrics
                .snapshot()
                .maximum_document_bytes
                .saturating_sub(state.documents)
        {
            return Err(capacity_error("compiler-document-capacity"));
        }
        let job = state
            .jobs
            .iter_mut()
            .find(|job| job.id == self.job)
            .ok_or_else(|| capacity_error("compiler-job-no-longer-pending"))?;
        if job.documents != 0 || job.task.is_some() {
            return Err(capacity_error("compiler-document-already-reserved"));
        }
        job.documents = bytes;
        state.documents += bytes;
        self.core.record(&state);
        Ok(())
    }
    pub(super) fn new(core: Arc<Core<T>>, job: u64, waiter: Arc<Waiter<T>>) -> Self {
        Self { core, job, waiter }
    }

    pub(crate) fn start(
        &self,
        build: impl FnOnce(PrepareReservation<T>) -> Task<T>,
    ) -> Result<(), PlatformError> {
        let reservation = {
            let mut state = self.core.lock();
            if !state.accepting {
                return Err(capacity_error("compiler-stopping"));
            }
            state
                .jobs
                .iter_mut()
                .find(|job| job.id == self.job)
                .and_then(|job| job.reservation.take())
                .ok_or_else(|| capacity_error("compiler-job-no-longer-pending"))?
        };
        let task = build(reservation);
        let mut state = self.core.lock();
        if !state.accepting {
            drop(state);
            drop(task);
            return Err(capacity_error("compiler-stopping"));
        }
        let Some(job) = state.jobs.iter_mut().find(|job| job.id == self.job) else {
            drop(state);
            drop(task);
            return Err(capacity_error("compiler-job-no-longer-pending"));
        };
        job.task = Some(task);
        drop(state);
        self.core.wake.notify_all();
        Ok(())
    }
}

impl<T: Send + Sync + 'static> Future for PreparationWait<T> {
    type Output = Result<ReadyPin<T>, PlatformError>;

    fn poll(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Self::Output> {
        let incoming = cx.waker().clone();
        let mut state = self
            .waiter
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if let Some(result) = state.result.take() {
            return Poll::Ready(result);
        }
        let previous = state.waker.replace(incoming);
        drop(state);
        drop(previous);
        Poll::Pending
    }
}

impl<T: Send + Sync + 'static> Drop for PreparationWait<T> {
    fn drop(&mut self) {
        self.waiter.alive.store(false, Ordering::Release);
        let mut state = self.core.lock();
        let Some(index) = state.jobs.iter().position(|job| job.id == self.job) else {
            return;
        };
        if state.jobs[index].creator == self.waiter.id
            && state.jobs[index].task.is_none()
            && matches!(state.jobs[index].phase, Phase::Assigned(_) | Phase::Queued)
        {
            let job = state.jobs.remove(index);
            state.documents -= job.documents;
            state.waiters -= job.waiters.len();
            if let Phase::Assigned(worker) = job.phase {
                state.promote(worker);
            }
            self.core
                .metrics
                .update(|s| s.jobs_abandoned = s.jobs_abandoned.saturating_add(1));
            self.core.record(&state);
            drop(state);
            let mut wakers = Vec::new();
            for waiter in &job.waiters {
                let mut data = waiter
                    .state
                    .lock()
                    .unwrap_or_else(std::sync::PoisonError::into_inner);
                let permit = data.permit.take();
                data.result = Some(Err(capacity_error("compiler-creator-abandoned")));
                if let Some(waker) = data.waker.take() {
                    wakers.push(waker);
                }
                drop(data);
                drop(permit);
            }
            drop(job);
            self.core.metrics.notify();
            super::wake(wakers);
            self.core.wake.notify_all();
            return;
        }
        let job = &mut state.jobs[index];
        let Some(waiter_index) = job
            .waiters
            .iter()
            .position(|waiter| waiter.id == self.waiter.id)
        else {
            return;
        };
        let waiter = job.waiters.swap_remove(waiter_index);
        let empty = job.waiters.is_empty();
        let phase = job.phase;
        if empty {
            job.abandoned = true;
        }
        state.waiters -= 1;
        self.core
            .metrics
            .update(|s| s.cancelled_waiters = s.cancelled_waiters.saturating_add(1));
        let removed = if empty && matches!(phase, Phase::Assigned(_) | Phase::Queued) {
            let job = state.jobs.remove(index);
            state.documents -= job.documents;
            if let Phase::Assigned(worker) = phase {
                state.promote(worker);
            }
            self.core
                .metrics
                .update(|s| s.jobs_abandoned = s.jobs_abandoned.saturating_add(1));
            Some(job)
        } else {
            None
        };
        self.core.record(&state);
        drop(state);
        drop(waiter);
        drop(removed);
        self.core.metrics.notify();
        self.core.wake.notify_all();
    }
}
