// SPDX-License-Identifier: MIT OR Apache-2.0
//! Bounded owner/lifecycle half of the captured executor's guest-local bridge.
//! Root's two-phase registration owns this backing before pool allocation.
//! No new owner grants or user future execution occur in this state machine.
use super::executor_lifecycle::{self as life, Lifecycle};
use super::owner::{Kind, Owner, Token};
use super::{io_error, WaitQueue};
use crate::cell::UnsafeCell;
use crate::io;

const SLOTS: usize = 32;
#[derive(Clone, Copy)]
struct Generation {
    id: u64,
    value: life::Generation,
}
struct Worker {
    id: u64,
    value: life::Worker,
    generation: Generation,
    canonical: Option<u32>,
    close: Option<Owner>,
}
struct Future {
    id: u64,
    value: life::Future,
    task: Option<Owner>,
    queue: Option<Owner>,
    completed: bool,
}
struct Inner {
    life: Lifecycle,
    serial: u64,
    current: Option<Generation>,
    provision: Option<Generation>,
    workers: [Option<Worker>; SLOTS],
    futures: [Option<Future>; SLOTS],
}
pub(crate) struct Control {
    inner: UnsafeCell<Inner>,
    generation_changed: WaitQueue,
}
pub(crate) enum Drain {
    Pending,
    Close { generation: u64, messages: usize },
    Quiescent,
}
fn invalid() -> io::Error {
    io::Error::from(io::ErrorKind::InvalidInput)
}
fn state_error(error: life::Error) -> io::Error {
    io::Error::from(match error {
        life::Error::Capacity => io::ErrorKind::WouldBlock,
        life::Error::Busy | life::Error::WorkPending => io::ErrorKind::WouldBlock,
        life::Error::Closed | life::Error::Stale | life::Error::State => {
            io::ErrorKind::InvalidInput
        }
    })
}
impl Inner {
    fn next(&mut self) -> io::Result<u64> {
        self.serial = self
            .serial
            .checked_add(1)
            .ok_or_else(|| io::Error::from(io::ErrorKind::WouldBlock))?;
        Ok(self.serial)
    }
    fn worker(&self, key: u64) -> io::Result<usize> {
        self.workers
            .iter()
            .position(|row| row.as_ref().is_some_and(|r| r.id == key))
            .ok_or_else(invalid)
    }
    fn future(&self, key: u64) -> io::Result<usize> {
        self.futures
            .iter()
            .position(|row| row.as_ref().is_some_and(|r| r.id == key))
            .ok_or_else(invalid)
    }
}
impl Control {
    pub(crate) fn new() -> Self {
        Self {
            inner: UnsafeCell::new(Inner {
                life: Lifecycle::new(),
                serial: 0,
                current: None,
                provision: None,
                workers: crate::array::from_fn(|_| None),
                futures: crate::array::from_fn(|_| None),
            }),
            generation_changed: WaitQueue::new(),
        }
    }
    // Pure nonallocating state only. No broker, callback, Drop of an Owner,
    // allocator, user code or canonical handoff may occur inside this borrow.
    fn state<R>(&self, f: impl FnOnce(&mut Inner) -> R) -> R {
        unsafe { f(&mut *self.inner.get()) }
    }
    pub(crate) fn begin_generation(&self, size: usize) -> io::Result<Option<u64>> {
        loop {
            let ready = self.state(|state| state.current.is_some());
            if ready {
                return Ok(None);
            }
            if self.state(|state| state.provision.is_some()) {
                let wait = self.generation_changed.prepare(None);
                if self.state(|state| state.provision.is_some()) {
                    assert!(wait.wait());
                } else {
                    wait.cancel();
                }
                continue;
            }
            return self.state(|state| {
                // No yield can race the preceding test and this transition.
                let id = state.next()?;
                let value = state.life.prepare_generation(size).map_err(state_error)?;
                state.provision = Some(Generation { id, value });
                Ok(Some(id))
            });
        }
    }
    pub(crate) fn reserve_worker(&self, generation: u64, parent: Token) -> io::Result<u64> {
        let (id, slot) = self.state(|state| {
            let gen = state
                .provision
                .filter(|g| g.id == generation)
                .ok_or_else(invalid)?;
            let slot = state
                .workers
                .iter()
                .position(Option::is_none)
                .ok_or_else(|| io::Error::from(io::ErrorKind::WouldBlock))?;
            let id = state.next()?;
            let value = state.life.reserve_worker(gen.value).map_err(state_error)?;
            state.workers[slot] = Some(Worker {
                id,
                value,
                generation: gen,
                canonical: None,
                close: None,
            });
            Ok::<_, io::Error>((id, slot))
        })?;
        // Prepaid Close record precedes thread/channel/handshake allocation.
        // On Err the constructor aborts this real provisioning generation.
        let close = Owner::admit(Kind::QueuedWork, Some(parent)).map_err(io_error)?;
        self.state(|state| {
            let row = state.workers[slot].as_mut().expect("reserved pool worker");
            assert_eq!(row.id, id);
            assert!(row.close.replace(close).is_none());
        });
        Ok(id)
    }
    pub(crate) fn check_worker_start(&self, key: u64, canonical: u32) -> io::Result<()> {
        self.state(|state| {
            let slot = state.worker(key)?;
            let row = state.workers[slot].as_ref().unwrap();
            if row.canonical.is_some() || row.close.is_none() {
                return Err(invalid());
            }
            state
                .life
                .check_worker_start(row.value, canonical)
                .map_err(state_error)
        })
    }
    // The caller must first install the one actual pool Arc lease on this
    // running PAL child. That installation is nonsuspending, so no state
    // borrow or host operation separates it from this authenticated transition.
    pub(crate) fn worker_started(&self, key: u64, canonical: u32) -> io::Result<()> {
        self.state(|state| {
            let slot = state.worker(key)?;
            let row = state.workers[slot].as_ref().unwrap();
            if row.canonical.is_some() || row.close.is_none() {
                return Err(invalid());
            }
            state
                .life
                .worker_started(row.value, canonical)
                .map_err(state_error)?;
            state.workers[slot].as_mut().unwrap().canonical = Some(canonical);
            Ok(())
        })
    }
    pub(crate) fn commit_generation(&self, key: u64) -> io::Result<()> {
        self.state(|state| {
            let generation = state
                .provision
                .filter(|g| g.id == key)
                .ok_or_else(invalid)?;
            state
                .life
                .commit_generation(generation.value)
                .map_err(state_error)?;
            state.current = Some(generation);
            state.provision = None;
            Ok::<_, io::Error>(())
        })?;
        self.generation_changed.notify_all();
        Ok(())
    }
    pub(crate) fn abort_generation(&self, key: u64) -> io::Result<(u64, usize)> {
        let (close, rollback) = self.state(|state| {
            let generation = state
                .provision
                .filter(|g| g.id == key)
                .ok_or_else(invalid)?;
            let close = state
                .life
                .abort_generation(generation.value)
                .map_err(state_error)?;
            assert_eq!(close.generation, generation.value);
            let rollback = crate::array::from_fn::<_, SLOTS, _>(|slot| {
                if state.workers[slot]
                    .as_ref()
                    .is_some_and(|r| r.generation.id == key && r.canonical.is_none())
                {
                    state.workers[slot].take().and_then(|mut r| r.close.take())
                } else {
                    None
                }
            });
            state.provision = None;
            Ok::<_, io::Error>((close, rollback))
        })?;
        // Real unstarted admissions settle only after leaving the state borrow.
        drop(rollback);
        self.generation_changed.notify_all();
        Ok((key, close.messages))
    }
    pub(crate) fn admit_future(&self, parent: Token) -> io::Result<u64> {
        let (key, slot, value) = self.state(|state| {
            let slot = state
                .futures
                .iter()
                .position(Option::is_none)
                .ok_or_else(|| io::Error::from(io::ErrorKind::WouldBlock))?;
            let key = state.next()?;
            let value = state.life.reserve_future().map_err(state_error)?;
            // The real reservation remains visible through both fallible calls.
            state.futures[slot] = Some(Future {
                id: key,
                value,
                task: None,
                queue: None,
                completed: false,
            });
            Ok::<_, io::Error>((key, slot, value))
        })?;
        let admission = (|| {
            let task = Owner::admit(Kind::Task, Some(parent)).map_err(io_error)?;
            let queue = Owner::admit(Kind::QueuedWork, Some(task.token())).map_err(io_error)?;
            Ok::<_, io::Error>((task, queue))
        })();
        let (task, queue) = match admission {
            Ok(owners) => owners,
            Err(error) => {
                self.state(|state| {
                    state
                        .life
                        .rollback_future(value)
                        .expect("unaccepted pool future rollback");
                    assert_eq!(state.futures[slot].as_ref().unwrap().id, key);
                    state.futures[slot] = None;
                });
                return Err(error);
            }
        };
        self.state(|state| {
            state
                .life
                .commit_future(value, task.token(), queue.token())
                .expect("admitted pool future publication");
            let row = state.futures[slot].as_mut().unwrap();
            assert_eq!(row.id, key);
            row.task = Some(task);
            row.queue = Some(queue);
        });
        Ok(key)
    }
    pub(crate) fn dequeued(&self, key: u64) -> io::Result<()> {
        let queue = self.state(|state| {
            let slot = state.future(key)?;
            let row = state.futures[slot].as_mut().unwrap();
            let token = state.life.dequeued(row.value).map_err(state_error)?;
            let owner = row.queue.take().expect("actual dequeued queue owner");
            assert_eq!(owner.token(), token);
            Ok::<_, io::Error>(owner)
        })?;
        drop(queue);
        Ok(())
    }
    pub(crate) fn waiting(&self, key: u64) -> io::Result<()> {
        self.state(|state| {
            let slot = state.future(key)?;
            state
                .life
                .waiting(state.futures[slot].as_ref().unwrap().value)
                .map_err(state_error)
        })
    }
    pub(crate) fn requeue(&self, key: u64) -> io::Result<()> {
        let (value, parent) = self.state(|state| {
            let slot = state.future(key)?;
            let row = state.futures[slot].as_ref().unwrap();
            state.life.reserve_requeue(row.value).map_err(state_error)?;
            Ok::<_, io::Error>((
                row.value,
                row.task.as_ref().expect("accepted future Task").token(),
            ))
        })?;
        // ArcWake is infallible; source caller traps on refusal rather than
        // discarding the already accepted future or trying a legacy allocator.
        let queue = Owner::admit(Kind::QueuedWork, Some(parent)).map_err(io_error)?;
        self.state(|state| {
            let slot = state.future(key).expect("accepted requeue identity");
            state
                .life
                .commit_requeue(value, queue.token())
                .expect("one real requeue publication");
            assert!(state.futures[slot]
                .as_mut()
                .unwrap()
                .queue
                .replace(queue)
                .is_none());
        });
        Ok(())
    }
    pub(crate) fn completed(&self, key: u64) -> io::Result<()> {
        self.state(|state| {
            let slot = state.future(key)?;
            let row = state.futures[slot].as_mut().unwrap();
            let task = state.life.completed(row.value).map_err(state_error)?;
            assert_eq!(row.task.as_ref().unwrap().token(), task);
            row.completed = true;
            Ok(())
        })
        // Keep Task until the final real wake support drop. Future Ready alone
        // does not certify destruction of late callback/waker continuations.
    }
    pub(crate) fn wake_dropped(&self, key: u64) -> io::Result<()> {
        let owners = self.state(|state| {
            let slot = state.future(key)?;
            let row = state.futures[slot].as_ref().unwrap();
            if !row.completed || row.queue.is_some() {
                return Err(invalid());
            }
            state.life.wake_dropped(row.value).map_err(state_error)?;
            Ok::<_, io::Error>(state.futures[slot].take().unwrap())
        })?;
        drop(owners);
        Ok(())
    }
    pub(crate) fn claim_close(&self, key: u64, generation: u64) -> io::Result<bool> {
        let owner = self.state(|state| {
            let slot = state.worker(key)?;
            let row = state.workers[slot].as_ref().unwrap();
            let gen = state
                .workers
                .iter()
                .flatten()
                .find(|r| r.generation.id == generation)
                .ok_or_else(invalid)?
                .generation;
            if !state
                .life
                .claim_close(row.value, gen.value)
                .map_err(state_error)?
            {
                return Ok(None);
            }
            Ok::<_, io::Error>(Some(
                state.workers[slot]
                    .as_mut()
                    .unwrap()
                    .close
                    .take()
                    .expect("prepaid actual Close owner"),
            ))
        })?;
        let consumed = owner.is_some();
        drop(owner);
        Ok(consumed)
    }
    pub(crate) fn worker_tls_drained(&self, canonical: u32) -> io::Result<()> {
        self.state(|state| {
            let worker = state
                .workers
                .iter()
                .flatten()
                .find(|r| r.canonical == Some(canonical))
                .ok_or_else(invalid)?
                .value;
            state.life.user_tls_drained(worker).map_err(state_error)
        })
    }
    pub(crate) fn worker_frames_exited(&self, canonical: u32) -> io::Result<()> {
        self.state(|state| {
            let slot = state
                .workers
                .iter()
                .position(|r| r.as_ref().is_some_and(|r| r.canonical == Some(canonical)))
                .ok_or_else(invalid)?;
            let row = state.workers[slot].as_ref().unwrap();
            assert!(row.close.is_none());
            state.life.frames_exited(row.value).map_err(state_error)?;
            state.workers[slot] = None;
            Ok(())
        })
    }
    pub(crate) fn drain(&self) -> io::Result<Drain> {
        self.state(|state| match state.life.request_close() {
            Ok(Some(close)) => {
                let generation = state
                    .current
                    .take()
                    .expect("closing actual active generation");
                assert_eq!(generation.value, close.generation);
                Ok(Drain::Close {
                    generation: generation.id,
                    messages: close.messages,
                })
            }
            Ok(None) => Ok(if state.workers.iter().any(Option::is_some) {
                Drain::Pending
            } else {
                Drain::Quiescent
            }),
            Err(life::Error::WorkPending) => Ok(Drain::Pending),
            Err(error) => Err(state_error(error)),
        })
    }
    pub(crate) fn retire(&self) -> io::Result<()> {
        self.state(|state| {
            if state.current.is_some()
                || state.provision.is_some()
                || state.workers.iter().any(Option::is_some)
                || state.futures.iter().any(Option::is_some)
            {
                return Err(invalid());
            }
            state.life.retire().map_err(state_error)
        })
    }
}
