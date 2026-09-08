use std::sync::atomic::Ordering;
use std::sync::Arc;

use latent_core::PlatformError;

use super::state::{Core, Phase, Waiter};
use super::{capacity_error, CompilationResult, ReadyPin};
use crate::PreparationStage;

pub(super) fn run<T: Send + Sync + 'static>(core: Arc<Core<T>>, worker: usize) {
    core.metrics
        .update(|s| s.workers_live = s.workers_live.saturating_add(1));
    let _exit = Exit {
        core: Arc::clone(&core),
    };
    let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| run_loop(&core, worker)));
    if result.is_err() {
        core.fail_worker(worker);
    }
}

fn run_loop<T: Send + Sync + 'static>(core: &Arc<Core<T>>, worker: usize) {
    loop {
        let work = {
            let mut state = core.lock();
            loop {
                if !state.accepting {
                    break None;
                }
                if let Some(job) = state
                    .jobs
                    .iter_mut()
                    .find(|job| job.phase == Phase::Assigned(worker) && job.task.is_some())
                {
                    job.phase = Phase::Running(worker);
                    let id = job.id;
                    let task = job.task.take().expect("assigned task exists");
                    core.metrics
                        .update(|s| s.jobs_started = s.jobs_started.saturating_add(1));
                    core.record(&state);
                    break Some((id, task));
                }
                state = core
                    .wake
                    .wait(state)
                    .unwrap_or_else(std::sync::PoisonError::into_inner);
            }
        };
        let Some((id, task)) = work else {
            return;
        };
        core.metrics.notify();
        let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(task))
            .unwrap_or_else(|_| Err(capacity_error("compiler-job-panicked")));
        finish(&core, worker, id, result);
    }
}

fn finish<T: Send + Sync + 'static>(
    core: &Core<T>,
    worker: usize,
    id: u64,
    result: Result<CompilationResult<T>, PlatformError>,
) {
    // The guard probes and wakes consumers only outside the pool lock.
    let adoption = result
        .as_ref()
        .ok()
        .map(|compiled| compiled.observation.stage(PreparationStage::CacheAdoption));
    let mut state = core.lock();
    let index = state
        .jobs
        .iter()
        .position(|job| job.id == id)
        .expect("worker owns its registered job");
    let abandoned = state.jobs[index].abandoned || !state.accepting;
    let waiters = state.jobs[index].waiters.clone();
    state.jobs[index].phase = Phase::Finishing(worker);
    let mut evicted = Vec::new();
    let mut observation = None;
    let mut discarded = None;
    let output = match result {
        Ok(mut compiled) => {
            if abandoned {
                discarded = Some(compiled);
                Err(capacity_error("compiler-job-abandoned"))
            } else {
                let published = if let Some(reservation) = compiled.reservation.take() {
                    let (metadata, image) = (core.costs)(&compiled.runtime);
                    reservation.publish_deferred(Arc::clone(&compiled.runtime), image, metadata)
                } else {
                    Ok(Vec::new())
                };
                match published {
                    Ok(removed) => {
                        evicted = removed;
                        observation = Some(compiled.observation);
                        Ok(compiled.runtime)
                    }
                    Err(error) => {
                        discarded = Some(compiled);
                        Err(error)
                    }
                }
            }
        }
        Err(error) => Err(error),
    };
    core.record(&state);
    drop(state);
    drop(evicted);
    if let Some(adoption) = adoption {
        if output.is_ok() {
            adoption.complete();
        } else {
            drop(adoption);
        }
    }
    drop(discarded);
    let mut wakers = Vec::new();
    for waiter in waiters {
        deliver(core, waiter, &output, &mut wakers);
    }
    if let Some(observation) = observation {
        observation.complete();
    }
    let failed = output.is_err();
    drop(output);
    let mut state = core.lock();
    let index = state
        .jobs
        .iter()
        .position(|job| job.id == id)
        .expect("finishing job remains registered");
    let removed = state.jobs.remove(index);
    state.waiters -= removed.waiters.len();
    state.documents -= removed.documents;
    state.promote(worker);
    core.metrics.update(|s| {
        if abandoned {
            s.jobs_abandoned = s.jobs_abandoned.saturating_add(1);
            s.discarded_results = s.discarded_results.saturating_add(1);
        } else if failed {
            s.jobs_failed = s.jobs_failed.saturating_add(1);
        } else {
            s.jobs_completed = s.jobs_completed.saturating_add(1);
        }
    });
    core.record(&state);
    drop(state);
    drop(removed);
    core.metrics.notify();
    super::wake(wakers);
    core.wake.notify_all();
}

fn deliver<T>(
    core: &Core<T>,
    waiter: Arc<Waiter<T>>,
    output: &Result<Arc<T>, PlatformError>,
    wakers: &mut Vec<std::task::Waker>,
) {
    let permit = {
        let mut state = waiter
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if state.result.is_some() {
            return;
        }
        state.permit.take()
    };
    if !waiter.alive.load(Ordering::Acquire) {
        drop(permit);
        return;
    }
    let Some(permit) = permit else {
        return;
    };
    let result = match output {
        Ok(runtime) => {
            let (metadata, image) = (core.costs)(runtime);
            permit.charge(metadata, image).map(|permit| ReadyPin {
                runtime: Arc::clone(runtime),
                permit,
            })
        }
        Err(error) => {
            drop(permit);
            Err(error.clone())
        }
    };
    let mut state = waiter
        .state
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner);
    if state.result.is_some() || !waiter.alive.load(Ordering::Acquire) {
        drop(state);
        drop(result);
        return;
    }
    state.result = Some(result);
    if let Some(waker) = state.waker.take() {
        wakers.push(waker);
    }
}

struct Exit<T> {
    core: Arc<Core<T>>,
}

impl<T> Drop for Exit<T> {
    fn drop(&mut self) {
        let mut state = self.core.lock();
        state.quiescent += 1;
        self.core.metrics.update(|s| {
            s.workers_live = s.workers_live.saturating_sub(1);
            s.workers_quiescent = s.workers_quiescent.saturating_add(1);
            if std::thread::panicking() {
                s.failed = true;
            }
        });
        let waker = state.shutdown_waiter.take();
        drop(state);
        self.core.metrics.notify();
        super::wake(waker.map(|(_, waker)| waker).into_iter().collect());
    }
}
