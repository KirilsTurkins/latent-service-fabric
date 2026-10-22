// SPDX-License-Identifier: MIT OR Apache-2.0
//! Nonsuspending lifecycle state for the selected, captured ThreadPool port.
//!
//! This is not a queue or an executor: original mpsc and UnparkMutex still own
//! messages/futures and decide which wake enqueues. Every method returns before
//! broker admission, allocation, thread creation, callbacks or canonical yield.
//! Callers must release their state lock before any such operation.
use super::Token;

pub(crate) const MAX_WORKERS: usize = 32;
pub(crate) const MAX_FUTURES: usize = 32;
const CLOSE_ROUNDS: u8 = 4;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum Error {
    Capacity,
    Busy,
    WorkPending,
    Closed,
    Stale,
    State,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) struct Generation(u64);
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) struct Worker {
    slot: u8,
    generation: Generation,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) struct Future {
    slot: u8,
    serial: u64,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) struct Close {
    pub(crate) generation: Generation,
    pub(crate) messages: usize,
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum WorkerPhase {
    Reserved,
    Live,
    Closing,
    ExitRequested,
    UserTlsDrained,
}
#[derive(Clone, Copy)]
struct WorkerRecord {
    generation: Generation,
    phase: WorkerPhase,
    canonical: Option<u32>,
}
#[derive(Clone, Copy, PartialEq, Eq)]
enum FuturePhase {
    Reserved,
    Queued,
    Polling,
    Waiting,
    Requeueing,
    Completed,
}
#[derive(Clone, Copy)]
struct FutureRecord {
    serial: u64,
    generation: Generation,
    phase: FuturePhase,
    task: Option<Token>,
    queue: Option<Token>,
}
#[derive(Clone, Copy)]
struct Provision {
    generation: Generation,
    requested: usize,
    issued: usize,
    started: usize,
}

/// Fixed backing is allocated only after the real Executor/support admission.
/// These implementation bounds can refuse earlier; they never grant owners or
/// replace the original activation Task/QueuedWork/Native/byte ceilings.
pub(crate) struct Lifecycle {
    workers: [Option<WorkerRecord>; MAX_WORKERS],
    futures: [Option<FutureRecord>; MAX_FUTURES],
    current: Option<Generation>,
    provision: Option<Provision>,
    generation: u64,
    serial: u64,
    closes: u8,
    retired: bool,
}

impl Lifecycle {
    pub(crate) const fn new() -> Self {
        Self {
            workers: [None; MAX_WORKERS],
            futures: [None; MAX_FUTURES],
            current: None,
            provision: None,
            generation: 0,
            serial: 0,
            closes: 0,
            retired: false,
        }
    }

    /// Reserve only state. No worker or accepted future is invented here.
    /// A closing generation does not prevent an actual admitted successor.
    pub(crate) fn prepare_generation(&mut self, requested: usize) -> Result<Generation, Error> {
        if self.retired {
            return Err(Error::Closed);
        }
        if self.provision.is_some() || self.current.is_some() {
            return Err(Error::Busy);
        }
        if self.closes == CLOSE_ROUNDS
            || requested == 0
            || requested > MAX_WORKERS
            || self.workers.iter().filter(|entry| entry.is_none()).count() < requested
        {
            return Err(Error::Capacity);
        }
        let generation = self.generation.checked_add(1).ok_or(Error::Capacity)?;
        self.generation = generation;
        let generation = Generation(generation);
        self.provision = Some(Provision {
            generation,
            requested,
            issued: 0,
            started: 0,
        });
        Ok(generation)
    }

    pub(crate) fn reserve_worker(&mut self, generation: Generation) -> Result<Worker, Error> {
        let mut provision = self
            .provision
            .filter(|p| p.generation == generation)
            .ok_or(Error::Stale)?;
        if provision.issued == provision.requested {
            return Err(Error::State);
        }
        let slot = self
            .workers
            .iter()
            .position(Option::is_none)
            .ok_or(Error::Capacity)?;
        self.workers[slot] = Some(WorkerRecord {
            generation,
            phase: WorkerPhase::Reserved,
            canonical: None,
        });
        provision.issued += 1;
        self.provision = Some(provision);
        Ok(Worker {
            slot: slot as u8,
            generation,
        })
    }

    /// Called after real Task/Native admission and the canonical initialization
    /// handshake. Merely reserving a slot or executing a closure inline cannot
    /// make a generation eligible to accept a future.
    pub(crate) fn worker_started(&mut self, worker: Worker, canonical: u32) -> Result<(), Error> {
        self.check_worker_start(worker, canonical)?;
        let mut record = self.worker(worker)?;
        let mut provision = self.provision.unwrap();
        record.phase = WorkerPhase::Live;
        record.canonical = Some(canonical);
        self.workers[usize::from(worker.slot)] = Some(record);
        provision.started += 1;
        self.provision = Some(provision);
        Ok(())
    }

    // Validate before the PAL takes ownership of a real worker Arc. The
    // subsequent transition is pure and nonsuspending on this selected
    // single-fiber profile; no fallible broker call follows that transfer.
    pub(crate) fn check_worker_start(&self, worker: Worker, canonical: u32) -> Result<(), Error> {
        let record = self.worker(worker)?;
        if record.phase != WorkerPhase::Reserved
            || self
                .workers
                .iter()
                .flatten()
                .any(|row| row.canonical == Some(canonical))
        {
            return Err(Error::State);
        }
        self.provision
            .filter(|p| p.generation == worker.generation)
            .ok_or(Error::Stale)?;
        Ok(())
    }

    pub(crate) fn commit_generation(&mut self, generation: Generation) -> Result<(), Error> {
        let provision = self
            .provision
            .filter(|p| p.generation == generation)
            .ok_or(Error::Stale)?;
        if provision.issued != provision.requested || provision.started != provision.requested {
            return Err(Error::WorkPending);
        }
        self.current = Some(generation);
        self.provision = None;
        Ok(())
    }

    /// A partially failed pool creation still owes closure and real TLS/frame
    /// retirement for every worker it already started. Unstarted slots may be
    /// discarded only after their actual admission/allocation rollback.
    pub(crate) fn abort_generation(&mut self, generation: Generation) -> Result<Close, Error> {
        self.provision
            .filter(|p| p.generation == generation)
            .ok_or(Error::Stale)?;
        let mut messages = 0;
        for entry in &mut self.workers {
            let Some(record) = entry.as_mut().filter(|r| r.generation == generation) else {
                continue;
            };
            match record.phase {
                WorkerPhase::Reserved => *entry = None,
                WorkerPhase::Live => {
                    record.phase = WorkerPhase::Closing;
                    messages += 1;
                }
                _ => return Err(Error::State),
            }
        }
        self.provision = None;
        Ok(Close {
            generation,
            messages,
        })
    }

    /// Pins the eligible generation across fallible broker admission. Closure
    /// cannot run between this reservation and commit/rollback. The future is
    /// still caller-owned, and is not accepted by a reservation alone.
    pub(crate) fn reserve_future(&mut self) -> Result<Future, Error> {
        if self.retired {
            return Err(Error::Closed);
        }
        if self.provision.is_some() {
            return Err(Error::Busy);
        }
        let generation = self.current.ok_or(Error::WorkPending)?;
        if !self
            .workers
            .iter()
            .flatten()
            .any(|row| row.generation == generation && row.phase == WorkerPhase::Live)
        {
            return Err(Error::WorkPending);
        }
        let slot = self
            .futures
            .iter()
            .position(Option::is_none)
            .ok_or(Error::Capacity)?;
        let serial = self.serial.checked_add(1).ok_or(Error::Capacity)?;
        self.serial = serial;
        self.futures[slot] = Some(FutureRecord {
            serial,
            generation,
            phase: FuturePhase::Reserved,
            task: None,
            queue: None,
        });
        Ok(Future {
            slot: slot as u8,
            serial,
        })
    }

    pub(crate) fn rollback_future(&mut self, future: Future) -> Result<(), Error> {
        if self.future(future)?.phase != FuturePhase::Reserved {
            return Err(Error::State);
        }
        self.futures[usize::from(future.slot)] = None;
        Ok(())
    }

    /// Tokens come from actual typed broker admissions retained by the port's
    /// affine owner bundle. This state machine cannot create or settle them.
    pub(crate) fn commit_future(
        &mut self,
        future: Future,
        task: Token,
        queue: Token,
    ) -> Result<(), Error> {
        let mut record = self.future(future)?;
        if record.phase != FuturePhase::Reserved
            || self.current != Some(record.generation)
            || !valid(task)
            || !valid(queue)
            || task == queue
            || self.futures.iter().flatten().any(|r| {
                r.task == Some(task)
                    || r.queue == Some(task)
                    || r.task == Some(queue)
                    || r.queue == Some(queue)
            })
        {
            return Err(Error::State);
        }
        record.task = Some(task);
        record.queue = Some(queue);
        record.phase = FuturePhase::Queued;
        self.futures[usize::from(future.slot)] = Some(record);
        Ok(())
    }

    /// The original mpsc receiver has really removed this Message::Run. The
    /// returned queue registration is unlinked/freed before its owner settles.
    pub(crate) fn dequeued(&mut self, future: Future) -> Result<Token, Error> {
        let mut record = self.future(future)?;
        if record.phase != FuturePhase::Queued {
            return Err(Error::State);
        }
        let queue = record.queue.take().ok_or(Error::State)?;
        record.phase = FuturePhase::Polling;
        self.futures[usize::from(future.slot)] = Some(record);
        Ok(queue)
    }

    /// Only UnparkMutex::wait returning Ok stores the real task as waiting.
    /// Its immediate Err(task) repoll retains Polling and enqueues nothing.
    pub(crate) fn waiting(&mut self, future: Future) -> Result<(), Error> {
        let mut record = self.future(future)?;
        if record.phase != FuturePhase::Polling {
            return Err(Error::State);
        }
        record.phase = FuturePhase::Waiting;
        self.futures[usize::from(future.slot)] = Some(record);
        Ok(())
    }

    /// Called only when the original UnparkMutex::notify returns its real Task.
    /// Reserve before broker admission, so a reentrant wake cannot duplicate a
    /// queue item. Completed/stale wakers never recreate accepted work.
    pub(crate) fn reserve_requeue(&mut self, future: Future) -> Result<(), Error> {
        let mut record = self.future(future)?;
        if record.phase != FuturePhase::Waiting {
            return Err(Error::State);
        }
        record.phase = FuturePhase::Requeueing;
        self.futures[usize::from(future.slot)] = Some(record);
        Ok(())
    }

    pub(crate) fn commit_requeue(&mut self, future: Future, queue: Token) -> Result<(), Error> {
        let mut record = self.future(future)?;
        if record.phase != FuturePhase::Requeueing
            || !valid(queue)
            || self
                .futures
                .iter()
                .flatten()
                .any(|r| r.queue == Some(queue) || r.task == Some(queue))
        {
            return Err(Error::State);
        }
        record.phase = FuturePhase::Queued;
        record.queue = Some(queue);
        self.futures[usize::from(future.slot)] = Some(record);
        Ok(())
    }

    /// Run after the actual future and retained result are dropped/consumed,
    /// while its live Task can still parent destructor-submitted continuations.
    /// Wake support is kept until the actual final WakeHandle strong drop.
    pub(crate) fn completed(&mut self, future: Future) -> Result<Token, Error> {
        let mut record = self.future(future)?;
        if record.phase != FuturePhase::Polling || record.queue.is_some() {
            return Err(Error::State);
        }
        let task = record.task.ok_or(Error::State)?;
        record.phase = FuturePhase::Completed;
        self.futures[usize::from(future.slot)] = Some(record);
        Ok(task)
    }

    /// The real wake-registration node must already be unlinked/freed. Arc's
    /// Wasm backing bytes remain covered by the original linear-memory limiter.
    pub(crate) fn wake_dropped(&mut self, future: Future) -> Result<(), Error> {
        if self.future(future)?.phase != FuturePhase::Completed {
            return Err(Error::State);
        }
        self.futures[usize::from(future.slot)] = None;
        Ok(())
    }

    pub(crate) fn accepted(&self) -> usize {
        self.futures
            .iter()
            .flatten()
            .filter(|r| r.phase != FuturePhase::Reserved && r.phase != FuturePhase::Completed)
            .count()
    }

    /// Mark a generation closing BEFORE sending its original mpsc Close
    /// messages. A TLS/before_stop submission must provision a real successor
    /// and cannot be silently accepted by workers which have already left.
    pub(crate) fn request_close(&mut self) -> Result<Option<Close>, Error> {
        if self.retired {
            return Err(Error::Closed);
        }
        if self.provision.is_some()
            || self
                .futures
                .iter()
                .flatten()
                .any(|r| r.phase != FuturePhase::Completed)
        {
            return Err(Error::WorkPending);
        }
        let Some(generation) = self.current else {
            return Ok(None);
        };
        if self.closes == CLOSE_ROUNDS {
            return Err(Error::Capacity);
        }
        let mut messages = 0;
        for record in self
            .workers
            .iter_mut()
            .flatten()
            .filter(|r| r.generation == generation)
        {
            if record.phase != WorkerPhase::Live {
                return Err(Error::State);
            }
            record.phase = WorkerPhase::Closing;
            messages += 1;
        }
        if messages == 0 {
            return Err(Error::State);
        }
        self.closes += 1;
        self.current = None;
        Ok(Some(Close {
            generation,
            messages,
        }))
    }

    /// False means put this old-generation message back on the SAME mpsc
    /// queue, release its mutex, then yield through the real PAL. It must not
    /// terminate a successor or lose the old worker's close message.
    pub(crate) fn claim_close(
        &mut self,
        worker: Worker,
        generation: Generation,
    ) -> Result<bool, Error> {
        let mut record = self.worker(worker)?;
        if !self
            .workers
            .iter()
            .flatten()
            .any(|r| r.generation == generation && r.phase == WorkerPhase::Closing)
        {
            return Err(Error::Stale);
        }
        if record.generation != generation {
            return Ok(false);
        }
        if record.phase != WorkerPhase::Closing {
            return Err(Error::State);
        }
        record.phase = WorkerPhase::ExitRequested;
        self.workers[usize::from(worker.slot)] = Some(record);
        Ok(true)
    }

    /// This boundary follows actual before_stop/user TLS destructors. It never
    /// invokes those destructors early and cannot itself prove frame exit.
    pub(crate) fn user_tls_drained(&mut self, worker: Worker) -> Result<(), Error> {
        let mut record = self.worker(worker)?;
        if record.phase != WorkerPhase::ExitRequested {
            return Err(Error::State);
        }
        record.phase = WorkerPhase::UserTlsDrained;
        self.workers[usize::from(worker.slot)] = Some(record);
        Ok(())
    }

    /// Called only with the PAL's authenticated canonical-return/frame proof,
    /// after System context/stack release. A guest phase word alone is not that
    /// proof, and this never refunds a physical Wasmtime stack reservation.
    pub(crate) fn frames_exited(&mut self, worker: Worker) -> Result<(), Error> {
        if self.worker(worker)?.phase != WorkerPhase::UserTlsDrained {
            return Err(Error::State);
        }
        self.workers[usize::from(worker.slot)] = None;
        Ok(())
    }

    pub(crate) fn retire(&mut self) -> Result<(), Error> {
        if self.retired {
            return Err(Error::Closed);
        }
        if self.provision.is_some()
            || self.current.is_some()
            || self.workers.iter().any(Option::is_some)
            || self.futures.iter().any(Option::is_some)
        {
            return Err(Error::WorkPending);
        }
        self.retired = true;
        Ok(())
    }

    fn worker(&self, worker: Worker) -> Result<WorkerRecord, Error> {
        self.workers
            .get(usize::from(worker.slot))
            .and_then(|row| *row)
            .filter(|row| row.generation == worker.generation)
            .ok_or(Error::Stale)
    }
    fn future(&self, future: Future) -> Result<FutureRecord, Error> {
        self.futures
            .get(usize::from(future.slot))
            .and_then(|row| *row)
            .filter(|row| row.serial == future.serial)
            .ok_or(Error::Stale)
    }
}

fn valid(token: Token) -> bool {
    token.generation != 0 && token.id != 0
}
