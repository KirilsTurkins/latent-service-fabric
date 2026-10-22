// SPDX-License-Identifier: MIT OR Apache-2.0
use crate::cell::Cell;
use crate::sys::sync::Mutex;
use crate::sys::thread::lsf::wait::WaitQueue;
use crate::time::Duration;

pub struct Condvar { mutex: Cell<*const Mutex>, waiters: WaitQueue }
unsafe impl Send for Condvar {}
unsafe impl Sync for Condvar {}
impl Condvar {
    pub const fn new() -> Self {
        Self { mutex: Cell::new(crate::ptr::null()), waiters: WaitQueue::new() }
    }
    pub fn notify_one(&self) { self.waiters.notify_one(|_| {}); }
    pub fn notify_all(&self) { self.waiters.notify_all(); }
    pub unsafe fn wait(&self, mutex: &Mutex) { unsafe { self.wait_inner(mutex, None); } }
    pub unsafe fn wait_timeout(&self, mutex: &Mutex, timeout: Duration) -> bool {
        unsafe { self.wait_inner(mutex, Some(timeout)) }
    }
    unsafe fn wait_inner(&self, mutex: &Mutex, timeout: Option<Duration>) -> bool {
        let address = mutex as *const Mutex;
        let previous = self.mutex.get();
        assert!(previous.is_null() || previous == address, "condvar used with a different mutex");
        self.mutex.set(address);
        // Enqueue before releasing the mutex. A notification between unlock and
        // the actual park sets this waiter's state; it is not an elapsed timer.
        let wait = self.waiters.prepare(timeout);
        unsafe { mutex.unlock(); }
        let notified = wait.wait();
        mutex.lock();
        // Pinned std interprets false only as an observed elapsed timeout.
        notified
    }
}
