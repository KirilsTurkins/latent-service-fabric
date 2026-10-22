// SPDX-License-Identifier: MIT OR Apache-2.0
use crate::cell::Cell;
use crate::pin::Pin;
use crate::sync::atomic::{Ordering, compiler_fence};
use crate::sys::thread::lsf::wait::WaitQueue;
use crate::time::Duration;

pub struct Parker { notified: Cell<bool>, waiters: WaitQueue }
unsafe impl Send for Parker {}
unsafe impl Sync for Parker {}
impl Parker {
    pub unsafe fn new_in_place(pointer: *mut Self) {
        unsafe { pointer.write(Self { notified: Cell::new(false), waiters: WaitQueue::new() }); }
    }
    pub unsafe fn park(self: Pin<&Self>) { self.park_inner(None); }
    pub unsafe fn park_timeout(self: Pin<&Self>, timeout: Duration) { self.park_inner(Some(timeout)); }
    fn park_inner(self: Pin<&Self>, timeout: Option<Duration>) {
        if self.notified.replace(false) { compiler_fence(Ordering::Acquire); return; }
        let wait = self.waiters.prepare(timeout);
        // prepare can call the admitted host bridge. Preserve unpark which
        // arrived before publication without turning it into a second permit.
        if self.notified.replace(false) { wait.cancel(); }
        else {
            let notified = wait.wait();
            if notified { assert!(self.notified.replace(false), "park wake without unpark permit"); }
        }
        compiler_fence(Ordering::Acquire);
    }
    pub fn unpark(self: Pin<&Self>) {
        compiler_fence(Ordering::Release);
        self.notified.set(true);
        self.waiters.notify_one(|_| {});
    }
}
