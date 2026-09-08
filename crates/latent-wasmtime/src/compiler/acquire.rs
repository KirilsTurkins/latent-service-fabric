use std::sync::atomic::AtomicBool;
use std::sync::{Arc, Mutex};

use latent_core::PlatformError;

use super::state::{Job, Phase, Waiter, WaiterState};
use super::{capacity_error, Acquisition, Admission, CompilerPool, PreparationWait, ReadyPin};
use crate::cache::PrepareAccess;

impl<T: Send + Sync + 'static> CompilerPool<T> {
    pub(crate) fn acquire(&self, input: Admission) -> Result<Acquisition<T>, PlatformError> {
        let permit = self.core.ready.reserve()?;
        let mut state = self.core.lock();
        let limits = self.core.metrics.snapshot();
        if !state.accepting {
            return Err(capacity_error("compiler-stopping"));
        }
        let existing = input.identity.as_ref().and_then(|identity| {
            state.jobs.iter().position(|job| {
                job.identity.as_ref() == Some(identity) && !matches!(job.phase, Phase::Finishing(_))
            })
        });
        if let Some(index) = existing {
            if state.waiters >= limits.maximum_waiters
                || state.jobs[index].waiters.len() >= limits.maximum_waiters_per_job
            {
                self.core
                    .metrics
                    .update(|s| s.waiter_rejected = s.waiter_rejected.saturating_add(1));
                return Err(capacity_error("compiler-waiter-capacity"));
            }
            if state.jobs[index].abandoned {
                return Err(capacity_error("compiler-generation-abandoned"));
            }
            let next = state
                .next_waiter
                .checked_add(1)
                .ok_or_else(|| capacity_error("compiler-waiter-generation-exhausted"))?;
            let waiter = new_waiter(state.next_waiter, permit);
            state.next_waiter = next;
            let job_id = state.jobs[index].id;
            state.jobs[index].waiters.push(Arc::clone(&waiter));
            state.waiters += 1;
            self.core
                .metrics
                .update(|s| s.coalesced_waiters = s.coalesced_waiters.saturating_add(1));
            self.core.record(&state);
            drop(state);
            self.core.metrics.notify();
            return Ok(Acquisition::Waiting {
                future: PreparationWait::new(Arc::clone(&self.core), job_id, waiter),
                owner: false,
            });
        }
        let reservation =
            match self
                .core
                .cache
                .begin(input.handle, input.source_bytes, input.metadata_bytes)?
            {
                PrepareAccess::Hit(runtime) => {
                    drop(state);
                    let (metadata, image) = (self.core.costs)(&runtime);
                    return Ok(Acquisition::Ready(ReadyPin {
                        runtime,
                        permit: permit.charge(metadata, image)?,
                    }));
                }
                PrepareAccess::Compile(reservation) => reservation,
            };
        if state.jobs.len() >= limits.maximum_jobs
            || state.waiters >= limits.maximum_waiters
            || input.document_bytes
                > limits
                    .maximum_document_bytes
                    .saturating_sub(state.documents)
        {
            self.core
                .metrics
                .update(|s| s.queue_rejected = s.queue_rejected.saturating_add(1));
            drop(state);
            drop(reservation);
            return Err(capacity_error("compiler-job-capacity"));
        }
        let phase = state
            .free_worker(limits.maximum_workers)
            .map_or(Phase::Queued, Phase::Assigned);
        if phase == Phase::Queued
            && state
                .jobs
                .iter()
                .filter(|job| job.phase == Phase::Queued)
                .count()
                >= limits.maximum_queued_jobs
        {
            drop(state);
            drop(reservation);
            return Err(capacity_error("compiler-queue-capacity"));
        }
        let job_id = state.next_job;
        let Some(next_job) = state.next_job.checked_add(1) else {
            drop(state);
            drop(reservation);
            return Err(capacity_error("compiler-job-generation-exhausted"));
        };
        let Some(next_waiter) = state.next_waiter.checked_add(1) else {
            drop(state);
            drop(reservation);
            return Err(capacity_error("compiler-waiter-generation-exhausted"));
        };
        let waiter = new_waiter(state.next_waiter, permit);
        state.next_waiter = next_waiter;
        state.next_job = next_job;
        state.documents += input.document_bytes;
        state.waiters += 1;
        state.jobs.push(Job {
            id: job_id,
            creator: waiter.id,
            identity: input.identity,
            phase,
            waiters: vec![Arc::clone(&waiter)],
            reservation: Some(reservation),
            task: None,
            documents: input.document_bytes,
            abandoned: false,
        });
        self.core.record(&state);
        drop(state);
        self.core.metrics.notify();
        Ok(Acquisition::Waiting {
            future: PreparationWait::new(Arc::clone(&self.core), job_id, waiter),
            owner: true,
        })
    }
}

fn new_waiter<T>(id: u64, permit: super::ReadyPermit) -> Arc<Waiter<T>> {
    Arc::new(Waiter {
        id,
        alive: AtomicBool::new(true),
        state: Mutex::new(WaiterState {
            permit: Some(permit),
            result: None,
            waker: None,
        }),
    })
}
