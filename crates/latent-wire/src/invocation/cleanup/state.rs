use std::collections::VecDeque;
use std::sync::{Arc, Mutex, MutexGuard, Weak};
use std::task::Waker;
use std::time::Duration;

use latent_core::{
    BoxFuture, DeadlineDiagnosticDecision, DeadlineDiagnosticObservation,
    DeadlineDiagnosticObserver, PlatformError, PlatformErrorCode,
};
use latent_node::{ActivationHandle, ActivationTransportInterruption};
use tokio::task::AbortHandle;
use tokio::time::Instant;

use super::{boundary_error, ActivationCleanupSnapshot};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(super) enum Phase {
    Free,
    Reserved,
    Queued,
    Running,
}

pub(super) struct Entry {
    pub generation: u64,
    pub phase: Phase,
    pub work: Option<Work>,
}

pub(super) struct Work {
    pub future: BoxFuture<'static, ()>,
    pub deadline: Instant,
}

pub(super) struct State {
    pub slots: Vec<Entry>,
    pub free: Vec<usize>,
    pub queue: VecDeque<usize>,
    pub waker: Option<Waker>,
    pub snapshot: ActivationCleanupSnapshot,
    pub last_retired: Option<Instant>,
}

pub(super) struct Shared {
    pub state: Mutex<State>,
    pub allowance: Duration,
    pub observer: Option<DeadlineDiagnosticObserver>,
    pub abort: Mutex<Weak<AbortHandle>>,
}

pub(in crate::invocation) struct CleanupSlot {
    shared: Arc<Shared>,
    key: Option<(usize, u64)>,
}

#[derive(Clone, Copy)]
pub(super) enum Disposition {
    Completed,
    TimedOut,
    Panicked,
    Fallback,
}

impl Shared {
    pub fn new(capacity: usize, allowance: Duration) -> Self {
        Self {
            allowance,
            observer: None,
            abort: Mutex::new(Weak::new()),
            state: Mutex::new(State {
                slots: (0..capacity)
                    .map(|_| Entry {
                        generation: 0,
                        phase: Phase::Free,
                        work: None,
                    })
                    .collect(),
                free: (0..capacity).rev().collect(),
                queue: VecDeque::with_capacity(capacity),
                waker: None,
                last_retired: None,
                snapshot: ActivationCleanupSnapshot {
                    capacity,
                    accepting: true,
                    driver_alive: true,
                    driver_joined: false,
                    reserved: 0,
                    queued: 0,
                    running: 0,
                    handoffs: 0,
                    completed: 0,
                    timed_out: 0,
                    panicked: 0,
                    fallbacks: 0,
                    failed: false,
                },
            }),
        }
    }

    pub fn lock(&self) -> MutexGuard<'_, State> {
        self.state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
    }

    pub fn snapshot(&self) -> ActivationCleanupSnapshot {
        self.lock().snapshot
    }

    pub fn reserve(self: &Arc<Self>) -> Result<CleanupSlot, PlatformError> {
        let mut state = self.lock();
        if !state.snapshot.accepting || !state.snapshot.driver_alive {
            return Err(boundary_error(
                PlatformErrorCode::Unavailable,
                "activation cleanup is closed",
            ));
        }
        let Some(&index) = state.free.last() else {
            return Err(boundary_error(
                PlatformErrorCode::ResourceExhausted,
                "activation cleanup capacity is full",
            ));
        };
        let Some(generation) = state.slots[index].generation.checked_add(1) else {
            state.snapshot.accepting = false;
            state.snapshot.failed = true;
            let wake = state.waker.take();
            drop(state);
            self.wake(wake);
            return Err(boundary_error(
                PlatformErrorCode::ResourceExhausted,
                "activation cleanup generation exhausted",
            ));
        };
        state.free.pop();
        state.slots[index].generation = generation;
        state.slots[index].phase = Phase::Reserved;
        state.snapshot.reserved += 1;
        Ok(CleanupSlot {
            shared: Arc::clone(self),
            key: Some((index, generation)),
        })
    }

    pub fn close(&self) {
        let wake = {
            let mut state = self.lock();
            state.snapshot.accepting = false;
            state.waker.take()
        };
        self.wake(wake);
    }

    /// Seal before abort; outstanding affine reservations retain safe fallback.
    pub fn seal(&self) {
        let wake = {
            let mut state = self.lock();
            state.snapshot.accepting = false;
            state.snapshot.driver_alive = false;
            state.snapshot.failed = true;
            state.waker.take()
        };
        self.wake(wake);
    }

    pub fn joined(&self, failed: bool) {
        let mut state = self.lock();
        state.snapshot.driver_joined = true;
        state.snapshot.failed |= failed;
    }

    pub fn retired_after(&self, cutoff: Instant) -> bool {
        self.lock()
            .last_retired
            .is_some_and(|retired| retired > cutoff)
    }

    pub fn callback_failed(&self) {
        {
            let mut state = self.lock();
            state.snapshot.accepting = false;
            state.snapshot.failed = true;
        }
        let abort = self
            .abort
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .upgrade();
        if let Some(abort) = abort {
            abort.abort();
        }
    }

    pub fn wake(&self, waker: Option<Waker>) {
        if super::unwind::catch(|| {
            if let Some(waker) = waker {
                waker.wake();
            }
        })
        .is_err()
        {
            self.callback_failed();
        }
    }

    /// Called only after the corresponding future/result has been destroyed.
    pub fn release(&self, key: (usize, u64), phase: Phase, disposition: Option<Disposition>) {
        let retired = Instant::now();
        let wake = {
            let mut state = self.lock();
            let entry = &mut state.slots[key.0];
            if entry.generation != key.1 || entry.phase != phase || entry.work.is_some() {
                state.snapshot.failed = true;
                state.snapshot.accepting = false;
            } else {
                entry.phase = Phase::Free;
                state.free.push(key.0);
                state.last_retired =
                    Some(state.last_retired.map_or(retired, |old| old.max(retired)));
                match phase {
                    Phase::Reserved => state.snapshot.reserved -= 1,
                    Phase::Queued => state.snapshot.queued -= 1,
                    Phase::Running => state.snapshot.running -= 1,
                    Phase::Free => unreachable!("a free slot has no affine owner"),
                }
                if let Some(disposition) = disposition {
                    state.record(disposition);
                }
            }
            if state.snapshot.accepting {
                None
            } else {
                state.waker.take()
            }
        };
        self.wake(wake);
    }
}

impl State {
    pub fn record(&mut self, disposition: Disposition) {
        let counter = match disposition {
            Disposition::Completed => &mut self.snapshot.completed,
            Disposition::TimedOut => &mut self.snapshot.timed_out,
            Disposition::Panicked => &mut self.snapshot.panicked,
            Disposition::Fallback => &mut self.snapshot.fallbacks,
        };
        let next = counter.checked_add(1);
        *counter = next.unwrap_or(u64::MAX);
        if next.is_none() || !matches!(disposition, Disposition::Completed) {
            self.snapshot.failed = true;
        }
        if next.is_none() {
            self.snapshot.accepting = false;
        }
    }
}

impl CleanupSlot {
    pub(in crate::invocation) fn continue_after_interruption(
        self,
        handle: ActivationHandle,
        cause: ActivationTransportInterruption,
    ) {
        let handoff = Instant::now();
        let deadline = handoff
            .checked_add(self.shared.allowance)
            .expect("validated short cleanup duration");
        if let Some(observer) = &self.shared.observer {
            let (slot, generation) = self.key.expect("reserved cleanup observation");
            observer.record_for_activation(
                &handle.activation_id().0,
                DeadlineDiagnosticObservation::TransportHandoff {
                    observed_at: handoff.into_std(),
                    slot: slot as u64,
                    generation,
                    cause: match cause {
                        ActivationTransportInterruption::Disconnected => {
                            DeadlineDiagnosticDecision::Cancelled
                        }
                        ActivationTransportInterruption::DeadlineExceeded => {
                            DeadlineDiagnosticDecision::DeadlineExceeded
                        }
                    },
                },
            );
        }
        let handle = handle.interrupt_for_cleanup(cause);
        self.transfer(Work {
            future: Box::pin(async move {
                drop(handle.await);
            }),
            deadline,
        });
    }

    pub(super) fn transfer(mut self, work: Work) {
        let key = self.key.take().expect("one cleanup slot transfer");
        let mut work = Some(work);
        let wake;
        let queued;
        {
            let mut state = self.shared.lock();
            let valid = state.slots[key.0].generation == key.1
                && state.slots[key.0].phase == Phase::Reserved;
            assert!(valid, "affine cleanup reservation");
            let next = state.snapshot.handoffs.checked_add(1);
            state.snapshot.handoffs = next.unwrap_or(u64::MAX);
            if next.is_none() {
                state.snapshot.failed = true;
                state.snapshot.accepting = false;
            }
            queued = state.snapshot.driver_alive;
            if queued {
                state.slots[key.0].phase = Phase::Queued;
                state.slots[key.0].work = work.take();
                state.snapshot.reserved -= 1;
                state.snapshot.queued += 1;
                state.queue.push_back(key.0);
            }
            wake = state.waker.take();
        }
        self.shared.wake(wake);
        if !queued {
            let disposition = destroy(work, Disposition::Fallback);
            self.shared.release(key, Phase::Reserved, Some(disposition));
        }
    }
}

impl Drop for CleanupSlot {
    fn drop(&mut self) {
        if let Some(key) = self.key.take() {
            self.shared.release(key, Phase::Reserved, None);
        }
    }
}

pub(super) fn destroy<T>(value: T, success: Disposition) -> Disposition {
    if super::unwind::catch(|| drop(value)).is_err() {
        Disposition::Panicked
    } else {
        success
    }
}
