use std::sync::atomic::AtomicBool;
use std::sync::{Arc, Condvar, Mutex, MutexGuard};
use std::task::Waker;

use latent_core::PlatformError;

use super::{CoalescingKey, CompilerObserver, ReadyGate, ReadyPermit, ReadyPin, Task};
use crate::cache::{PrepareReservation, PreparedCache};
use crate::PreparationObserver;

#[derive(Clone, Copy, PartialEq, Eq)]
pub(super) enum Phase {
    Assigned(usize),
    Queued,
    Running(usize),
    Finishing(usize),
}

pub(super) struct Waiter<T> {
    pub(super) id: u64,
    pub(super) alive: AtomicBool,
    pub(super) state: Mutex<WaiterState<T>>,
}

pub(super) struct WaiterState<T> {
    pub(super) permit: Option<ReadyPermit>,
    pub(super) result: Option<Result<ReadyPin<T>, PlatformError>>,
    pub(super) waker: Option<Waker>,
}

pub(super) struct Job<T> {
    pub(super) id: u64,
    pub(super) creator: u64,
    pub(super) identity: Option<CoalescingKey>,
    pub(super) phase: Phase,
    pub(super) waiters: Vec<Arc<Waiter<T>>>,
    pub(super) reservation: Option<PrepareReservation<T>>,
    pub(super) task: Option<Task<T>>,
    pub(super) submitted_nanos: u64,
    pub(super) documents: usize,
    pub(super) abandoned: bool,
}

pub(super) struct State<T> {
    pub(super) accepting: bool,
    pub(super) next_job: u64,
    pub(super) next_waiter: u64,
    pub(super) jobs: Vec<Job<T>>,
    pub(super) waiters: usize,
    pub(super) documents: usize,
    pub(super) quiescent: usize,
    pub(super) next_shutdown_waiter: u64,
    pub(super) shutdown_waiter: Option<(u64, Waker)>,
}

impl<T> State<T> {
    pub(super) fn new() -> Self {
        Self {
            accepting: true,
            next_job: 0,
            next_waiter: 0,
            jobs: Vec::new(),
            waiters: 0,
            documents: 0,
            quiescent: 0,
            next_shutdown_waiter: 0,
            shutdown_waiter: None,
        }
    }

    pub(super) fn free_worker(&self, workers: usize) -> Option<usize> {
        (0..workers).find(|worker| {
            !self.jobs.iter().any(|job| {
                matches!(job.phase,
            Phase::Assigned(id) | Phase::Running(id) | Phase::Finishing(id) if id == *worker)
            })
        })
    }

    pub(super) fn promote(&mut self, worker: usize) {
        if let Some(job) = self.jobs.iter_mut().find(|job| job.phase == Phase::Queued) {
            job.phase = Phase::Assigned(worker);
        }
    }
}

pub(super) struct Core<T> {
    pub(super) state: Mutex<State<T>>,
    pub(super) wake: Condvar,
    pub(super) cache: Arc<PreparedCache<T>>,
    pub(super) ready: Arc<ReadyGate>,
    pub(super) metrics: CompilerObserver,
    pub(super) costs: fn(&T) -> (usize, usize),
    pub(super) observer: PreparationObserver,
}

impl<T> Core<T> {
    pub(super) fn lock(&self) -> MutexGuard<'_, State<T>> {
        self.state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
    }

    pub(super) fn record(&self, state: &State<T>) {
        self.metrics.update(|snapshot| {
            snapshot.accepting = state.accepting;
            snapshot.assigned_jobs = state
                .jobs
                .iter()
                .filter(|job| job.phase != Phase::Queued)
                .count() as u64;
            snapshot.running_jobs = state
                .jobs
                .iter()
                .filter(|job| matches!(job.phase, Phase::Running(_) | Phase::Finishing(_)))
                .count() as u64;
            snapshot.queued_jobs = state
                .jobs
                .iter()
                .filter(|job| job.phase == Phase::Queued)
                .count() as u64;
            snapshot.waiting_callers = state.waiters as u64;
            snapshot.reserved_document_bytes = state.documents as u64;
        });
    }
}
