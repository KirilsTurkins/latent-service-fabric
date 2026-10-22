// SPDX-License-Identifier: MIT OR Apache-2.0
//! Nonsuspending identity/closure part of the selected std thread PAL.
//!
//! This table does not allocate or admit owners and never executes a closure.
//! The PAL keeps the real ThreadInit, affine owners and System context backing
//! outside this Copy state. It must drop the table borrow before an allocator,
//! host operation, canonical handoff, std initialization or TLS destructor.
use super::Token;

pub(crate) const MAX_THREADS: usize = 32;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum Error {
    Capacity,
    Closed,
    Stale,
    State,
    JoinClaimed,
    SelfJoin,
    Cycle,
    Pending,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) struct Handle {
    slot: u8,
    serial: u64,
}
impl Handle {
    pub(crate) fn slot(self) -> usize {
        usize::from(self.slot)
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Phase {
    Reserved,
    Admitted,
    Ready,
    Running,
    TlsDrained,
    Reaping,
    Reaped,
}

#[derive(Clone, Copy)]
struct Record {
    serial: u64,
    phase: Phase,
    task: Option<Token>,
    context: Option<usize>,
    canonical: Option<u32>,
    joined_by: Option<u32>,
    waiting_for: Option<Handle>,
    detached: bool,
}

pub(crate) struct Registry {
    records: [Option<Record>; MAX_THREADS],
    serial: u64,
    root: u32,
    closing: bool,
}

impl Registry {
    pub(crate) const fn new(root: u32) -> Self {
        Self {
            records: [None; MAX_THREADS],
            serial: 0,
            root,
            closing: false,
        }
    }

    /// Reserve before broker admission or allocation. No ThreadInit ownership
    /// crosses into the table until the caller can publish all actual backing.
    pub(crate) fn reserve(&mut self) -> Result<Handle, Error> {
        if self.closing {
            return Err(Error::Closed);
        }
        let slot = self
            .records
            .iter()
            .position(Option::is_none)
            .ok_or(Error::Capacity)?;
        let serial = self.serial.checked_add(1).ok_or(Error::Capacity)?;
        self.serial = serial;
        self.records[slot] = Some(Record {
            serial,
            phase: Phase::Reserved,
            task: None,
            context: None,
            canonical: None,
            joined_by: None,
            waiting_for: None,
            detached: false,
        });
        Ok(Handle {
            slot: slot as u8,
            serial,
        })
    }

    /// The actual admission and any allocation rollback precede this removal.
    /// Once canonical creation has started, no unstarted rollback is accepted.
    pub(crate) fn rollback(&mut self, handle: Handle) -> Result<(), Error> {
        if self.record(handle)?.phase != Phase::Reserved {
            return Err(Error::State);
        }
        self.records[usize::from(handle.slot)] = None;
        Ok(())
    }

    /// Publish only a real Task, allocated aligned context, and the index
    /// returned by authenticated canonical thread.new. No guest-derived index
    /// or pointer is used as a substitute for the generation-scoped handle.
    pub(crate) fn admitted(
        &mut self,
        handle: Handle,
        task: Token,
        context: usize,
        canonical: u32,
    ) -> Result<(), Error> {
        let mut record = self.record(handle)?;
        if record.phase != Phase::Reserved
            || !task.valid()
            || context == 0
            || context % 8 != 0
            || canonical == self.root
            || self.records.iter().flatten().any(|row| {
                row.task == Some(task)
                    || row.context == Some(context)
                    || row.canonical == Some(canonical)
            })
        {
            return Err(Error::State);
        }
        record.task = Some(task);
        record.context = Some(context);
        record.canonical = Some(canonical);
        record.phase = Phase::Admitted;
        self.put(handle, record);
        Ok(())
    }

    /// Called from the actual separate child entry after the generated wrapper
    /// installed slot1. It proves only identity/context handshake, never that
    /// ThreadInit.init(), rust_start, user work or TLS destructors have run.
    pub(crate) fn entered(&mut self, canonical: u32, context: usize) -> Result<Handle, Error> {
        let (handle, mut record) = self.by_index(canonical)?;
        if record.phase != Phase::Admitted || record.context != Some(context) {
            return Err(Error::State);
        }
        record.phase = Phase::Ready;
        self.put(handle, record);
        Ok(handle)
    }

    /// Immediately before the unchanged ThreadInit.init()/rust_start call,
    /// after the initial child-to-parent identity handshake has returned.
    pub(crate) fn start(&mut self, handle: Handle, canonical: u32) -> Result<(), Error> {
        let mut record = self.record(handle)?;
        if record.phase != Phase::Ready || record.canonical != Some(canonical) {
            return Err(Error::State);
        }
        record.phase = Phase::Running;
        self.put(handle, record);
        Ok(())
    }

    /// User Rust closure and real std/TLS destructors have returned. The
    /// translated Rust epilogue and host canonical thread still remain live.
    pub(crate) fn tls_drained(&mut self, handle: Handle, canonical: u32) -> Result<(), Error> {
        let mut record = self.record(handle)?;
        if record.phase != Phase::Running
            || record.canonical != Some(canonical)
            || record.waiting_for.is_some()
        {
            return Err(Error::State);
        }
        record.phase = Phase::TlsDrained;
        self.put(handle, record);
        Ok(())
    }

    /// Call ONLY after authenticated final wrapper phase/SP/TLS checks AND
    /// the real canonical handoff returned to a distinct live caller. The PAL
    /// then physically frees the child's context/stack/backing before settling
    /// its logical owners. This state itself does neither operation.
    pub(crate) fn reaped(&mut self, handle: Handle) -> Result<(), Error> {
        let mut record = self.record(handle)?;
        if record.phase != Phase::Reaping || record.waiting_for.is_some() {
            return Err(Error::Pending);
        }
        record.phase = Phase::Reaped;
        self.put(handle, record);
        Ok(())
    }

    pub(crate) fn claim_reap(&mut self, handle: Handle) -> Result<(), Error> {
        let mut record = self.record(handle)?;
        if record.phase != Phase::TlsDrained || record.waiting_for.is_some() {
            return Err(Error::Pending);
        }
        record.phase = Phase::Reaping;
        self.put(handle, record);
        Ok(())
    }

    pub(crate) fn claim_join(&mut self, target: Handle, caller: u32) -> Result<(), Error> {
        let mut record = self.record(target)?;
        if record.detached || record.joined_by.is_some() || record.phase == Phase::Reserved {
            return Err(Error::JoinClaimed);
        }
        if record.canonical == Some(caller) {
            return Err(Error::SelfJoin);
        }
        let caller_record = if caller == self.root {
            None
        } else {
            Some(self.by_index(caller)?)
        };
        if caller_record.is_some_and(|(_, row)| row.waiting_for.is_some()) {
            return Err(Error::State);
        }
        let mut dependency = Some(target);
        let mut depth = 0;
        while let Some(handle) = dependency {
            depth += 1;
            if depth > MAX_THREADS {
                return Err(Error::Cycle);
            }
            let row = self.record(handle)?;
            if row.canonical == Some(caller) {
                return Err(Error::Cycle);
            }
            dependency = row.waiting_for;
        }
        record.joined_by = Some(caller);
        self.put(target, record);
        if let Some((handle, mut row)) = caller_record {
            row.waiting_for = Some(target);
            self.put(handle, row);
        }
        Ok(())
    }

    pub(crate) fn complete_join(&mut self, target: Handle, caller: u32) -> Result<(), Error> {
        let record = self.record(target)?;
        if record.phase != Phase::Reaped || record.joined_by != Some(caller) || record.detached {
            return Err(Error::Pending);
        }
        if caller != self.root {
            let (handle, mut row) = self.by_index(caller)?;
            if row.waiting_for != Some(target) {
                return Err(Error::State);
            }
            row.waiting_for = None;
            self.put(handle, row);
        }
        self.records[usize::from(target.slot)] = None;
        Ok(())
    }

    /// Dropping the ordinary JoinHandle detaches only its claim. It cannot
    /// remove accepted work, free a child, settle an owner or report a join.
    pub(crate) fn detach(&mut self, handle: Handle) -> Result<(), Error> {
        let mut record = self.record(handle)?;
        if record.joined_by.is_some() || record.detached || record.phase == Phase::Reserved {
            return Err(Error::State);
        }
        record.detached = true;
        self.put(handle, record);
        Ok(())
    }

    pub(crate) fn retire_detached(&mut self, handle: Handle) -> Result<(), Error> {
        let record = self.record(handle)?;
        if record.phase != Phase::Reaped || !record.detached || record.joined_by.is_some() {
            return Err(Error::Pending);
        }
        self.records[usize::from(handle.slot)] = None;
        Ok(())
    }

    pub(crate) fn current_task(&self, canonical: u32) -> Result<Token, Error> {
        let (_, row) = self.by_index(canonical)?;
        if row.phase == Phase::Reserved || row.phase == Phase::Reaped {
            return Err(Error::State);
        }
        row.task.ok_or(Error::State)
    }

    pub(crate) fn handles(&self) -> [Option<Handle>; MAX_THREADS] {
        crate::array::from_fn(|slot| {
            self.records[slot].map(|row| Handle {
                slot: slot as u8,
                serial: row.serial,
            })
        })
    }
    pub(crate) fn is_reaped(&self, handle: Handle) -> Result<bool, Error> {
        Ok(self.record(handle)?.phase == Phase::Reaped)
    }
    pub(crate) fn tls_finished(&self, handle: Handle) -> Result<bool, Error> {
        Ok(self.record(handle)?.phase == Phase::TlsDrained)
    }
    pub(crate) fn is_detached(&self, handle: Handle) -> Result<bool, Error> {
        Ok(self.record(handle)?.detached)
    }
    pub(crate) fn child(&self, canonical: u32, context: usize) -> Result<Handle, Error> {
        let (handle, row) = self.by_index(canonical)?;
        if row.context != Some(context) {
            return Err(Error::State);
        }
        Ok(handle)
    }

    /// The captured executor may attach only to a real started worker. An
    /// unstarted handshake, ended TLS frame, root or foreign context refuses.
    pub(crate) fn running_child(&self, canonical: u32, context: usize) -> Result<Handle, Error> {
        let (handle, row) = self.by_index(canonical)?;
        if row.phase != Phase::Running || row.context != Some(context) {
            return Err(Error::State);
        }
        Ok(handle)
    }

    /// Final System-only root postlude, after ALL root Rust/TLS frames ended.
    /// No handle is usable by another user frame now. Only physically reaped
    /// identity tombstones may be forgotten; pending work is never erased.
    pub(crate) fn close_after_root_frames(&mut self) -> Result<(), Error> {
        if self
            .records
            .iter()
            .flatten()
            .any(|r| r.phase != Phase::Reaped || r.waiting_for.is_some())
        {
            return Err(Error::Pending);
        }
        self.records.fill(None);
        self.closing = true;
        Ok(())
    }

    /// Ready or running threads may be in a canonical yield; TLS-complete
    /// threads need one final dispatch/return. The scheduler checks its wait
    /// registry separately before dispatching a blocked Ready/Running record.
    pub(crate) fn candidates(&self) -> [Option<(Handle, u32)>; MAX_THREADS] {
        crate::array::from_fn(|slot| {
            self.records[slot].and_then(|row| {
                matches!(row.phase, Phase::Ready | Phase::Running | Phase::TlsDrained).then(|| {
                    (
                        Handle {
                            slot: slot as u8,
                            serial: row.serial,
                        },
                        row.canonical.unwrap(),
                    )
                })
            })
        })
    }

    /// Root close forbids new ordinary threads only after accepted late/TLS
    /// work has drained. Executor successor provisioning must finish BEFORE
    /// this permanent phase, not reinterpret Closed as accepted continuation.
    pub(crate) fn close(&mut self) -> Result<(), Error> {
        if self.records.iter().any(Option::is_some) {
            return Err(Error::Pending);
        }
        self.closing = true;
        Ok(())
    }

    fn by_index(&self, canonical: u32) -> Result<(Handle, Record), Error> {
        self.records
            .iter()
            .enumerate()
            .find_map(|(slot, row)| {
                row.filter(|row| row.canonical == Some(canonical))
                    .map(|row| {
                        (
                            Handle {
                                slot: slot as u8,
                                serial: row.serial,
                            },
                            row,
                        )
                    })
            })
            .ok_or(Error::Stale)
    }
    fn record(&self, handle: Handle) -> Result<Record, Error> {
        self.records
            .get(usize::from(handle.slot))
            .and_then(|row| *row)
            .filter(|row| row.serial == handle.serial)
            .ok_or(Error::Stale)
    }
    fn put(&mut self, handle: Handle, record: Record) {
        self.records[usize::from(handle.slot)] = Some(record);
    }
}
