// SPDX-License-Identifier: MIT OR Apache-2.0
//! Cooperative std PAL: a FIFO gate prevents incoming readers passing a writer.
use crate::cell::Cell;
use crate::sync::atomic::{Ordering, compiler_fence};
use crate::sys::sync::Mutex;
use crate::sys::thread::lsf::{runtime, wait::WaitQueue};

pub struct RwLock {
    gate: Mutex,
    readers: Cell<usize>,
    writer: Cell<Option<u32>>,
    readers_finished: WaitQueue,
}
// Only the selected serial canonical-thread Store can use these Cell fields.
// All shared transitions are nonsuspending; waits use the original ledger.
unsafe impl Send for RwLock {}
unsafe impl Sync for RwLock {}
impl RwLock {
    pub const fn new() -> Self {
        Self { gate: Mutex::new(), readers: Cell::new(0), writer: Cell::new(None),
               readers_finished: WaitQueue::new() }
    }
    pub fn read(&self) {
        self.gate.lock();
        assert!(self.writer.get().is_none(), "reader entered an active writer");
        self.readers.set(self.readers.get().checked_add(1).expect("rwlock reader overflow"));
        compiler_fence(Ordering::Acquire);
        unsafe { self.gate.unlock(); }
    }
    pub fn try_read(&self) -> bool {
        if !self.gate.try_lock() { return false; }
        let next = self.readers.get().checked_add(1);
        let accepted = self.writer.get().is_none() && next.is_some();
        if accepted {
            self.readers.set(next.unwrap());
            compiler_fence(Ordering::Acquire);
        }
        unsafe { self.gate.unlock(); }
        accepted
    }
    pub fn write(&self) {
        self.gate.lock();
        // Keeping the gate closes admission to later readers. Existing readers
        // never need that gate to release; their final release wakes this wait.
        while self.readers.get() != 0 {
            let wait = self.readers_finished.prepare(None);
            if self.readers.get() == 0 { wait.cancel(); }
            else { wait.wait(); }
        }
        assert!(self.writer.get().is_none(), "overlapping logical writers");
        self.writer.set(Some(runtime::current_index()));
        compiler_fence(Ordering::Acquire);
    }
    pub fn try_write(&self) -> bool {
        if !self.gate.try_lock() { return false; }
        if self.readers.get() != 0 {
            unsafe { self.gate.unlock(); }
            return false;
        }
        assert!(self.writer.get().is_none(), "overlapping logical writer");
        self.writer.set(Some(runtime::current_index()));
        compiler_fence(Ordering::Acquire);
        true
    }
    pub unsafe fn read_unlock(&self) {
        assert!(self.writer.get().is_none(), "read unlock during writer");
        let next = self.readers.get().checked_sub(1).expect("read unlock without reader");
        compiler_fence(Ordering::Release);
        self.readers.set(next);
        if next == 0 { self.readers_finished.notify_one(|_| {}); }
    }
    pub unsafe fn write_unlock(&self) {
        assert_eq!(self.writer.get(), Some(runtime::current_index()), "write unlock owner");
        compiler_fence(Ordering::Release);
        self.writer.set(None);
        unsafe { self.gate.unlock(); }
    }
    pub unsafe fn downgrade(&self) {
        assert_eq!(self.writer.get(), Some(runtime::current_index()), "downgrade owner");
        assert_eq!(self.readers.get(), 0, "downgrade with live reader");
        compiler_fence(Ordering::Release);
        self.readers.set(1);
        self.writer.set(None);
        unsafe { self.gate.unlock(); }
    }
}
