// SPDX-License-Identifier: MIT OR Apache-2.0
// Pinned std PAL for one unshared memory32 / cooperative canonical-thread Store.
use crate::cell::Cell;
use crate::sync::atomic::{Ordering, compiler_fence};
use crate::sys::thread::lsf::{runtime, wait::WaitQueue};

pub struct Mutex {
    owner: Cell<Option<u32>>,
    waiters: WaitQueue,
}
// The selected engine never runs these logical threads in parallel. All Cell
// transitions below are nonsuspending; only the explicit owned wait can switch.
unsafe impl Send for Mutex {}
unsafe impl Sync for Mutex {}
impl Mutex {
    pub const fn new() -> Self {
        Self { owner: Cell::new(None), waiters: WaitQueue::new() }
    }
    pub fn lock(&self) {
        let current = runtime::current_index();
        assert_ne!(self.owner.get(), Some(current), "recursive logical mutex lock");
        if self.owner.get().is_none() && self.waiters.is_empty() {
            self.owner.set(Some(current));
        } else {
            // Admission can suspend. Publish the stable admitted waiter, then
            // recheck the lock so an unlock during admission is never lost.
            let wait = self.waiters.prepare(None);
            if self.owner.get().is_none() {
                self.owner.set(Some(current));
                wait.cancel();
            } else {
                wait.wait();
                assert_eq!(self.owner.get(), Some(current), "mutex handoff identity");
            }
        }
        compiler_fence(Ordering::Acquire);
    }
    pub fn try_lock(&self) -> bool {
        if self.owner.get().is_some() || !self.waiters.is_empty() { return false; }
        self.owner.set(Some(runtime::current_index()));
        compiler_fence(Ordering::Acquire);
        true
    }
    pub unsafe fn unlock(&self) {
        assert_eq!(self.owner.get(), Some(runtime::current_index()), "mutex unlock owner");
        compiler_fence(Ordering::Release);
        // Install ownership before any wake/provider operation can suspend.
        // A newly arriving locker cannot steal a handoff from the admitted FIFO.
        self.owner.set(None);
        self.waiters.notify_one(|next| self.owner.set(Some(next)));
    }
}
