use std::collections::VecDeque;
use std::sync::atomic::AtomicBool;
use std::sync::{Mutex, MutexGuard};
use std::task::Waker;
use std::time::Instant;

use super::model::{
    PreparationStage, PreparationStageObservation, PreparationStageTotals, RunningPreparation,
};

pub(super) const MAXIMUM_STAGE_OBSERVATIONS: usize = 256;

pub(super) struct State {
    pub(super) revision: u64,
    pub(super) next_job: u64,
    pub(super) next_observation: u64,
    pub(super) next_waiter: u64,
    pub(super) active_jobs: u64,
    pub(super) maximum_running: usize,
    pub(super) dropped_running: u64,
    pub(super) dropped_observations: u64,
    pub(super) stages: [PreparationStageTotals; 7],
    pub(super) running: Vec<RunningPreparation>,
    pub(super) observations: VecDeque<PreparationStageObservation>,
    pub(super) waiter: Option<(u64, Waker)>,
}

impl State {
    pub(super) fn new(maximum_running: usize) -> Self {
        Self {
            revision: 0,
            next_job: 0,
            next_observation: 0,
            next_waiter: 0,
            active_jobs: 0,
            maximum_running,
            dropped_running: 0,
            dropped_observations: 0,
            stages: PreparationStage::ALL.map(PreparationStageTotals::new),
            running: Vec::with_capacity(maximum_running),
            observations: VecDeque::with_capacity(MAXIMUM_STAGE_OBSERVATIONS),
            waiter: None,
        }
    }

    pub(super) fn changed(&mut self) -> Option<Waker> {
        self.revision = self.revision.saturating_add(1);
        self.waiter.take().map(|(_, waker)| waker)
    }
}

pub(super) struct Inner {
    pub(super) compiler: Mutex<Option<std::sync::Arc<Mutex<super::PreparationCompilerSnapshot>>>>,
    pub(super) enabled: AtomicBool,
    pub(super) origin: Instant,
    pub(super) state: Mutex<State>,
}

impl Inner {
    pub(super) fn lock(&self) -> MutexGuard<'_, State> {
        self.state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
    }

    pub(super) fn elapsed_nanos(&self) -> u64 {
        u64::try_from(self.origin.elapsed().as_nanos()).unwrap_or(u64::MAX)
    }
}

pub(super) fn wake(waker: Option<Waker>) {
    if let Some(waker) = waker {
        // Observer consumers cannot turn diagnostic wakeups into runtime panics.
        let _ = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| waker.wake()));
    }
}
