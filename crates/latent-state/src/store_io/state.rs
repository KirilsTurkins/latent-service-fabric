use std::collections::VecDeque;
use std::sync::{Arc, Condvar, Mutex};
use std::task::Waker;
use std::time::Instant;

use latent_core::ActivationClock;

use super::{
    StoreIoEnginePhase, StoreIoError, StoreIoKind, StoreIoLimits, StoreIoShutdown, StoreIoSnapshot,
};

pub(super) enum Bootstrap {
    Spawning,
    Ready,
    Failed,
}

pub(super) trait Work<S>: Send {
    fn run(self: Box<Self>, store: &S);
    fn reject(self: Box<Self>);
}

pub(super) trait Retirement: Send {
    fn retire(self: Box<Self>);
}

pub(super) type Finalizer<S> = Box<dyn FnOnce(&S) -> Result<(), StoreIoError> + Send>;

pub(super) struct QueuedWork<S> {
    pub kind: StoreIoKind,
    pub work: Box<dyn Work<S>>,
}

pub(super) struct State<S> {
    pub limits: StoreIoLimits,
    pub queue: VecDeque<QueuedWork<S>>,
    pub retirements: VecDeque<Box<dyn Retirement>>,
    pub physical_owners: usize,
    pub accepted: usize,
    pub retained_bytes: u64,
    pub active_reads: usize,
    pub active_writes: usize,
    pub live_workers: usize,
    pub exiting_workers: usize,
    pub next_job: u64,
    pub next_drain: u64,
    pub drain_waiter: Option<(u64, Option<Waker>)>,
    pub closed: bool,
    pub quarantined: bool,
    pub failure: Option<StoreIoError>,
    pub engine_phase: StoreIoEnginePhase,
    pub retired_at: Option<Instant>,
    pub shutdown_deadline: Option<Instant>,
    pub finalizer: Option<Finalizer<S>>,
    pub bootstrap: Bootstrap,
}

impl<S> State<S> {
    pub fn new(limits: StoreIoLimits, finalizer: Finalizer<S>) -> Self {
        let queue = VecDeque::with_capacity(limits.queued_jobs);
        let retirements = VecDeque::with_capacity(limits.accepted_jobs);
        let retained_bytes = limits.resident_bytes;
        Self {
            limits,
            queue,
            retirements,
            physical_owners: 0,
            accepted: 0,
            retained_bytes,
            active_reads: 0,
            active_writes: 0,
            live_workers: 0,
            exiting_workers: 0,
            next_job: 0,
            next_drain: 0,
            drain_waiter: None,
            closed: false,
            quarantined: false,
            failure: None,
            engine_phase: StoreIoEnginePhase::Owned,
            retired_at: None,
            shutdown_deadline: None,
            finalizer: Some(finalizer),
            bootstrap: Bootstrap::Spawning,
        }
    }

    pub fn admit(&self, bytes: u64) -> Result<(), StoreIoError> {
        if self.closed {
            return Err(StoreIoError::AdmissionClosed);
        }
        if self.queue.len() >= self.limits.queued_jobs {
            return Err(StoreIoError::QueueFull);
        }
        if self.accepted >= self.limits.accepted_jobs {
            return Err(StoreIoError::AcceptedFull);
        }
        if bytes > self.limits.job_bytes {
            return Err(StoreIoError::JobTooLarge);
        }
        if self
            .retained_bytes
            .checked_add(bytes)
            .is_none_or(|sum| sum > self.limits.retained_bytes)
        {
            return Err(StoreIoError::ByteBudget);
        }
        Ok(())
    }

    pub fn can_run(&self, kind: StoreIoKind) -> bool {
        match kind {
            StoreIoKind::Read => self.active_reads < self.limits.active_reads,
            StoreIoKind::Write => self.active_writes < self.limits.active_writes,
        }
    }

    pub fn running(&mut self, kind: StoreIoKind, enter: bool) {
        let count = match kind {
            StoreIoKind::Read => &mut self.active_reads,
            StoreIoKind::Write => &mut self.active_writes,
        };
        if enter {
            *count += 1;
        } else {
            *count -= 1;
        }
    }

    pub fn snapshot(&self) -> StoreIoSnapshot {
        StoreIoSnapshot {
            queued: self.queue.len(),
            active_reads: self.active_reads,
            active_writes: self.active_writes,
            accepted: self.accepted,
            retained_bytes: self.retained_bytes,
            physical_owners: self.physical_owners,
            queued_retirements: self.retirements.len(),
            live_workers: self.live_workers,
            admission_closed: self.closed,
            engine_phase: self.engine_phase,
            quarantined: self.quarantined,
            failure: self.failure,
        }
    }

    pub fn shutdown_report(&mut self, deadline: Instant) -> StoreIoShutdown {
        let deadline = self
            .shutdown_deadline
            .map_or(deadline, |original| original.min(deadline));
        if self.retired_at.is_some_and(|retired| retired > deadline) {
            self.quarantined = true;
        }
        let snapshot = self.snapshot();
        StoreIoShutdown {
            clean: snapshot.physically_retired()
                && !snapshot.quarantined
                && snapshot.failure.is_none(),
            snapshot,
        }
    }

    pub fn check_shutdown_deadline(&mut self, now: Instant) {
        if self
            .shutdown_deadline
            .is_some_and(|deadline| now >= deadline)
            && !self.snapshot().physically_retired()
        {
            self.quarantined = true;
        }
    }
}

pub(super) struct Control<S> {
    pub state: Mutex<State<S>>,
    pub changed: Condvar,
    pub clock: Arc<dyn ActivationClock>,
}

impl<S> Control<S> {
    pub fn fail(&self, error: StoreIoError) {
        {
            let mut state = self
                .state
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            state.closed = true;
            state.quarantined = true;
            state.failure = Some(error);
        }
        self.notify();
    }
    pub fn notify(&self) {
        let waker = self
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .drain_waiter
            .as_ref()
            .and_then(|(_, waker)| waker.clone());
        self.changed.notify_all();
        if let Some(waker) = waker {
            waker.wake();
        }
    }

    pub fn close(&self, quarantine: bool) {
        {
            let mut state = self
                .state
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            state.closed = true;
            state.quarantined |= quarantine;
        }
        self.notify();
    }
}
