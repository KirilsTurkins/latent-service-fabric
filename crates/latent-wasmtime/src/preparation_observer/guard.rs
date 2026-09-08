use std::sync::atomic::Ordering;
use std::sync::Arc;

use super::cpu;
use super::model::{
    PreparationStage, PreparationStageObservation, PreparationThreadCpu, RunningPreparation,
};
use super::state::{wake, Inner, MAXIMUM_STAGE_OBSERVATIONS};

pub(crate) struct PreparationJob {
    inner: Arc<Inner>,
    job_id: u64,
    digest: Option<[u8; 32]>,
    whole: Option<PreparationStageGuard>,
    observed: bool,
}

impl PreparationJob {
    pub(super) fn new(inner: Arc<Inner>, digest: Option<[u8; 32]>) -> Self {
        if !inner.enabled.load(Ordering::Acquire) {
            return Self {
                inner,
                job_id: 0,
                digest,
                whole: None,
                observed: false,
            };
        }
        let before = cpu::sample();
        let started = inner.elapsed_nanos();
        let mut state = inner.lock();
        let job_id = state.next_job;
        state.next_job = state.next_job.saturating_add(1);
        state.active_jobs = state.active_jobs.saturating_add(1);
        if state.running.len() < state.maximum_running {
            state.running.push(RunningPreparation {
                job_id,
                component_digest: digest,
                stage: PreparationStage::WholeJob,
                started_nanos: started,
                thread: before.map(|sample| sample.identity),
            });
        } else {
            state.dropped_running = state.dropped_running.saturating_add(1);
        }
        let waker = state.changed();
        drop(state);
        wake(waker);
        let whole = PreparationStageGuard::start(
            Arc::clone(&inner),
            job_id,
            digest,
            PreparationStage::WholeJob,
            before,
            started,
        );
        Self {
            inner,
            job_id,
            digest,
            whole: Some(whole),
            observed: true,
        }
    }

    pub(crate) fn stage(&self, stage: PreparationStage) -> PreparationStageGuard {
        if !self.observed {
            return PreparationStageGuard {
                inner: Arc::clone(&self.inner),
                job_id: 0,
                digest: self.digest,
                stage,
                before: None,
                started: 0,
                succeeded: false,
                observed: false,
            };
        }
        let before = cpu::sample();
        PreparationStageGuard::start(
            Arc::clone(&self.inner),
            self.job_id,
            self.digest,
            stage,
            before,
            self.inner.elapsed_nanos(),
        )
    }

    pub(crate) fn complete(mut self) {
        if let Some(whole) = self.whole.take() {
            whole.complete();
        }
    }
}

impl Drop for PreparationJob {
    fn drop(&mut self) {
        if !self.observed {
            return;
        }
        // Publish terminal timing before making the job observably idle.
        drop(self.whole.take());
        let mut state = self.inner.lock();
        state.active_jobs = state.active_jobs.saturating_sub(1);
        if let Some(index) = state
            .running
            .iter()
            .position(|entry| entry.job_id == self.job_id)
        {
            state.running.swap_remove(index);
        }
        let waker = state.changed();
        drop(state);
        wake(waker);
    }
}

pub(crate) struct PreparationStageGuard {
    inner: Arc<Inner>,
    job_id: u64,
    digest: Option<[u8; 32]>,
    stage: PreparationStage,
    before: Option<PreparationThreadCpu>,
    started: u64,
    succeeded: bool,
    observed: bool,
}

impl PreparationStageGuard {
    fn start(
        inner: Arc<Inner>,
        job_id: u64,
        digest: Option<[u8; 32]>,
        stage: PreparationStage,
        before: Option<PreparationThreadCpu>,
        started: u64,
    ) -> Self {
        let mut state = inner.lock();
        let totals = &mut state.stages[stage.index()];
        totals.started = totals.started.saturating_add(1);
        if let Some(entry) = state
            .running
            .iter_mut()
            .find(|entry| entry.job_id == job_id)
        {
            entry.stage = stage;
            entry.started_nanos = started;
            entry.thread = before.map(|sample| sample.identity);
        }
        let waker = state.changed();
        drop(state);
        wake(waker);
        // Start the measured interval after publishing/waking observers. The
        // running-entry timestamp records registration, not an earlier compile.
        let before = cpu::sample();
        let started = inner.elapsed_nanos();
        Self {
            inner,
            job_id,
            digest,
            stage,
            before,
            started,
            succeeded: false,
            observed: true,
        }
    }

    pub(crate) fn complete(mut self) {
        self.succeeded = true;
    }
}

impl Drop for PreparationStageGuard {
    fn drop(&mut self) {
        if !self.observed {
            return;
        }
        let finished = self.inner.elapsed_nanos();
        let thread_cpu = cpu::interval(self.before, cpu::sample());
        let mut state = self.inner.lock();
        let totals = &mut state.stages[self.stage.index()];
        if self.succeeded {
            totals.completed = totals.completed.saturating_add(1);
        } else {
            totals.failed = totals.failed.saturating_add(1);
        }
        totals.elapsed_nanos = totals
            .elapsed_nanos
            .saturating_add(finished.saturating_sub(self.started));
        if let Some(interval) = thread_cpu {
            totals.thread_cpu_samples = totals.thread_cpu_samples.saturating_add(1);
            totals.thread_cpu_user_ticks = totals
                .thread_cpu_user_ticks
                .saturating_add(interval.after.user_ticks - interval.before.user_ticks);
            totals.thread_cpu_system_ticks = totals
                .thread_cpu_system_ticks
                .saturating_add(interval.after.system_ticks - interval.before.system_ticks);
        } else {
            totals.thread_cpu_unavailable = totals.thread_cpu_unavailable.saturating_add(1);
        }
        let sequence = state.next_observation;
        state.next_observation = state.next_observation.saturating_add(1);
        if state.observations.len() == MAXIMUM_STAGE_OBSERVATIONS {
            state.observations.pop_front();
            state.dropped_observations = state.dropped_observations.saturating_add(1);
        }
        state.observations.push_back(PreparationStageObservation {
            sequence,
            job_id: self.job_id,
            component_digest: self.digest,
            stage: self.stage,
            started_nanos: self.started,
            finished_nanos: finished,
            succeeded: self.succeeded,
            thread_cpu,
        });
        if let Some(entry) = state
            .running
            .iter_mut()
            .find(|entry| entry.job_id == self.job_id)
        {
            // Between stage brackets, the enclosing preparation is still live.
            entry.stage = PreparationStage::WholeJob;
            entry.started_nanos = finished;
            entry.thread = thread_cpu.map(|interval| interval.after.identity);
        }
        let waker = state.changed();
        drop(state);
        wake(waker);
    }
}
