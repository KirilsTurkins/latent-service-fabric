//! Fixed node workers for accepted blocking store operations.
//!
//! Move the engine into this owner. Trusted operations borrow it only on its
//! finite workers; no blocking engine call runs in a future poll. Queue, active
//! read/write jobs, accepted response owners and bytes have explicit limits.
//! Dropping a result waiter detaches it, without cancelling accepted work or
//! refunding buffers still owned by its queued/physical operation.
//!
//! Closing admission is nonblocking. The last worker finalizes and destroys the
//! engine after all accepted physical jobs retire. Async drain borrows a timer
//! future from the node's existing clock/timer driver and permits one waiter.
//! Deadline expiry quarantines the owner; it never implies an aborted write,
//! closed engine or physically retired worker. Quarantine is sticky.

mod drain;
mod job;
mod recovery;
mod retained;
mod retirement;
mod startup;
mod state;
mod types;
mod worker;

pub use drain::StoreIoDrain;
pub use job::StoreIoJob;
pub use recovery::{StoreIoRecoveryCapacity, StoreIoRecoverySnapshot};
pub use retained::StoreIoRetained;
pub use retirement::{StoreIoRetirement, StoreIoRetirementWitness};
pub use startup::{StoreIoReady, StoreIoStartup};
pub use types::{
    StoreIoAdmissionError, StoreIoEnginePhase, StoreIoError, StoreIoKind, StoreIoLimits,
    StoreIoRecoveryLimits, StoreIoShutdown, StoreIoSnapshot, StoreIoStartError,
};

use std::future::Future;
use std::sync::{Arc, Condvar, Mutex};
use std::thread::JoinHandle;
use std::time::Instant;

use job::{Completion, Reservation, TypedWork};
use latent_core::{ActivationClock, SystemActivationClock};
use state::{Bootstrap, Control, QueuedWork, State};

/// One engine, fixed node workers and bounded accepted ownership.
pub struct StoreIoOwner<S> {
    inner: Arc<Owner<S>>,
}

struct Owner<S> {
    control: Arc<Control<S>>,
    threads: Mutex<Vec<JoinHandle<()>>>,
}

impl<S> Clone for StoreIoOwner<S> {
    fn clone(&self) -> Self {
        Self {
            inner: Arc::clone(&self.inner),
        }
    }
}

impl<S> Drop for Owner<S> {
    fn drop(&mut self) {
        self.control.close(false);
    }
}

impl<S: Send + Sync + 'static> StoreIoOwner<S> {
    /// Creation errors preserve a partial worker owner for physical drain.
    pub fn new(
        store: S,
        limits: StoreIoLimits,
        finalizer: impl FnOnce(&S) -> Result<(), StoreIoError> + Send + 'static,
    ) -> Result<Self, StoreIoStartError<S>> {
        Self::with_clock(store, limits, finalizer, Arc::new(SystemActivationClock))
    }

    pub fn with_clock(
        store: S,
        limits: StoreIoLimits,
        finalizer: impl FnOnce(&S) -> Result<(), StoreIoError> + Send + 'static,
        clock: Arc<dyn ActivationClock>,
    ) -> Result<Self, StoreIoStartError<S>> {
        if let Err(reason) = limits.validate() {
            return Err(StoreIoStartError {
                reason,
                owner: None,
                store: Some(store),
            });
        }
        let workers = limits.workers;
        let control = Arc::new(Control {
            state: Mutex::new(State::new(limits, Box::new(finalizer))),
            changed: Condvar::new(),
            clock,
        });
        let owner = Self {
            inner: Arc::new(Owner {
                control: Arc::clone(&control),
                threads: Mutex::new(Vec::new()),
            }),
        };
        let engine = Arc::new(store);
        for index in 0..workers {
            let worker_control = Arc::clone(&control);
            let worker_engine = Arc::clone(&engine);
            let recovery = control
                .state
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner)
                .limits
                .recovery
                .is_some_and(|limits| index < limits.workers);
            let name = if recovery {
                format!("latent-store-recovery-{index}")
            } else {
                format!("latent-store-io-{index}")
            };
            if let Ok(thread) = std::thread::Builder::new()
                .name(name)
                .stack_size(1024 * 1024)
                .spawn(move || worker::run(worker_control, worker_engine, recovery))
            {
                owner
                    .inner
                    .threads
                    .lock()
                    .unwrap_or_else(std::sync::PoisonError::into_inner)
                    .push(thread);
                control
                    .state
                    .lock()
                    .unwrap_or_else(std::sync::PoisonError::into_inner)
                    .live_workers += 1;
            } else {
                drop(engine);
                {
                    let mut state = control
                        .state
                        .lock()
                        .unwrap_or_else(std::sync::PoisonError::into_inner);
                    state.bootstrap = Bootstrap::Failed;
                    state.quarantined = true;
                    state.closed = true;
                    state.failure = Some(StoreIoError::WorkerStartFailed);
                    if state.live_workers == 0 {
                        state.engine_phase = StoreIoEnginePhase::Closed;
                        state.retained_bytes -= state.limits.resident_bytes;
                    }
                }
                control.notify();
                return Err(StoreIoStartError {
                    reason: StoreIoError::WorkerStartFailed,
                    owner: Some(owner),
                    store: None,
                });
            }
        }
        drop(engine);
        control
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .bootstrap = Bootstrap::Ready;
        control.notify();
        Ok(owner)
    }

    /// The host reserves all captured payload and possible result bytes first.
    /// Quota rejection returns the existing operation without allocating a job.
    #[allow(clippy::result_large_err)]
    pub fn submit<T: Send + 'static, F: FnOnce(&S) -> T + Send + 'static>(
        &self,
        kind: StoreIoKind,
        retained_bytes: u64,
        operation: F,
    ) -> Result<StoreIoJob<T>, StoreIoAdmissionError<F>> {
        let control = &self.inner.control;
        let Ok(mut state) = control.state.lock() else {
            return Err(StoreIoAdmissionError {
                reason: StoreIoError::Poisoned,
                operation,
            });
        };
        let prepared = (|| {
            let metadata = std::mem::size_of::<TypedWork<S, T, F>>()
                .checked_add(std::mem::size_of::<Completion<T>>())
                // Arc/box headers, bounded queue slot and response-owner shell.
                .and_then(|bytes| bytes.checked_add(128))
                .and_then(|bytes| u64::try_from(bytes).ok())
                .ok_or(StoreIoError::Exhausted)?;
            let charge = retained_bytes
                .checked_add(metadata)
                .ok_or(StoreIoError::Exhausted)?;
            state.admit(kind.is_recovery(), charge)?;
            let next = state
                .next_job
                .checked_add(1)
                .ok_or(StoreIoError::Exhausted)?;
            Ok((charge, next))
        })();
        let (charge, next) = match prepared {
            Ok(prepared) => prepared,
            Err(reason) => return Err(StoreIoAdmissionError { reason, operation }),
        };
        state.next_job = next;
        state.reserve(kind.is_recovery(), charge);
        let completion = Arc::new(Completion::new());
        let reservation = Reservation {
            control: Arc::clone(control),
            bytes: charge,
            recovery: kind.is_recovery(),
        };
        let work = TypedWork {
            operation,
            completion: Arc::clone(&completion),
            reservation,
        };
        let queue = if kind.is_recovery() {
            &mut state.recovery_queue
        } else {
            &mut state.queue
        };
        queue.push_back(QueuedWork {
            kind,
            work: Box::new(work),
        });
        drop(state);
        control.notify();
        Ok(StoreIoJob::new(completion))
    }

    pub fn close(&self) {
        self.inner.control.close(false);
    }

    /// Gate new work after a backend uncertainty; accepted live I/O still owns it.
    pub fn quarantine(&self) {
        self.inner.control.close(true);
    }

    pub fn snapshot(&self) -> Result<StoreIoSnapshot, StoreIoError> {
        let state = self
            .inner
            .control
            .state
            .lock()
            .map_err(|_| StoreIoError::Poisoned)?;
        Ok(state.snapshot())
    }

    /// The supplied wait uses the same clock and original absolute deadline.
    pub fn drain_async<F: Future<Output = ()>>(
        &self,
        deadline: Instant,
        deadline_wait: F,
    ) -> Result<StoreIoDrain<S, F>, StoreIoError> {
        StoreIoDrain::new(Arc::clone(&self.inner.control), deadline, deadline_wait)
    }

    /// Reap finished OS threads without waiting for live physical workers.
    pub fn reap_retired_threads(&self) -> Result<usize, StoreIoError> {
        let mut threads = self
            .inner
            .threads
            .lock()
            .map_err(|_| StoreIoError::Poisoned)?;
        let mut retired = 0;
        let mut index = 0;
        while index < threads.len() {
            if threads[index].is_finished() {
                let thread = threads.swap_remove(index);
                if thread.join().is_err() {
                    return Err(StoreIoError::RecoveryRequired);
                }
                retired += 1;
            } else {
                index += 1;
            }
        }
        Ok(retired)
    }
}

#[cfg(test)]
mod tests;
