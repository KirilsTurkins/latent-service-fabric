// SPDX-License-Identifier: MIT OR Apache-2.0
//! Intrusive admitted waits used by the selected std PAL, never app callbacks.
//! Queue mutation is nonsuspending. All host operations happen before publish
//! or after unlink/state/handoff, and no node pointer survives a host await.
use crate::cell::Cell;
use crate::ptr;
use crate::sys::thread::lsf::runtime::{self, Token, WaitLease};
use crate::time::Duration;

const MAX_WAITERS: usize = 32; // finite profile registry; original ledger can refuse earlier
#[derive(Clone, Copy, PartialEq, Eq)]
enum State {
    Waiting,
    Notified,
    TimedOut,
}
pub(crate) struct Node {
    queue: *const WaitQueue,
    next: Cell<*mut Node>,
    linked: Cell<bool>,
    state: Cell<State>,
    index: u32,
    token: Token,
}
pub(crate) struct WaitQueue {
    head: Cell<*mut Node>,
    tail: Cell<*mut Node>,
    count: Cell<usize>,
}
// Selected canonical threads share one unshared memory and execute serially.
// No checkpoint/host call may be inserted into these pointer/Cell operations.
unsafe impl Send for WaitQueue {}
unsafe impl Sync for WaitQueue {}
impl WaitQueue {
    pub(crate) const fn new() -> Self {
        Self {
            head: Cell::new(ptr::null_mut()),
            tail: Cell::new(ptr::null_mut()),
            count: Cell::new(0),
        }
    }
    pub(crate) fn is_empty(&self) -> bool {
        self.count.get() == 0
    }
    pub(crate) fn prepare(&self, timeout: Option<Duration>) -> Wait<'_> {
        // Wait/Timer admission may suspend. A fixed node slot was reserved
        // before admission; initialization and queue publication follow only
        // after admission returns. Callers then recheck their predicate.
        let mut lease = WaitLease::admit(timeout);
        let token = lease.token();
        let pointer = runtime::allocate_wait_node(&mut lease, Node {
            queue: self,
            next: Cell::new(ptr::null_mut()),
            linked: Cell::new(false),
            state: Cell::new(State::Waiting),
            index: runtime::current_index(),
            token,
        });
        let mut wait = Wait {
            queue: self,
            pointer,
            lease: Some(lease),
        };
        runtime::register_wait(wait.lease.as_mut().unwrap(), pointer);
        assert!(
            self.count.get() < MAX_WAITERS,
            "logical wait registry limit"
        );
        unsafe {
            let tail = self.tail.get();
            if tail.is_null() {
                self.head.set(pointer);
            } else {
                (*tail).next.set(pointer);
            }
            (*pointer).linked.set(true);
        }
        self.tail.set(pointer);
        self.count.set(self.count.get() + 1);
        // No host call, allocator or application code after publication.
        wait
    }
    fn unlink(&self, pointer: *mut Node) {
        if !unsafe { (*pointer).linked.get() } {
            return;
        }
        let mut previous: *mut Node = ptr::null_mut();
        let mut current = self.head.get();
        let mut visited = 0;
        while !current.is_null() && current != pointer {
            visited += 1;
            assert!(visited <= MAX_WAITERS, "cyclic logical wait queue");
            previous = current;
            current = unsafe { (*current).next.get() };
        }
        assert_eq!(current, pointer, "missing admitted logical waiter");
        let next = unsafe { (*pointer).next.get() };
        if previous.is_null() {
            self.head.set(next);
        } else {
            unsafe {
                (*previous).next.set(next);
            }
        }
        if self.tail.get() == pointer {
            self.tail.set(previous);
        }
        unsafe {
            (*pointer).next.set(ptr::null_mut());
            (*pointer).linked.set(false);
        }
        self.count.set(
            self.count
                .get()
                .checked_sub(1)
                .expect("wait queue count underflow"),
        );
    }
    pub(crate) fn notify_one(&self, before_wake: impl FnOnce(u32)) -> bool {
        let pointer = self.head.get();
        if pointer.is_null() {
            return false;
        }
        let (index, token) = unsafe {
            let node = &*pointer;
            assert!(
                node.state.get() == State::Waiting,
                "queued waiter is not waiting"
            );
            self.unlink(pointer);
            node.state.set(State::Notified);
            (node.index, node.token)
        };
        // Mutex ownership/handoff is installed before wake can suspend.
        // No access to pointer follows this call; the waiter may then retire.
        before_wake(index);
        runtime::wake_wait(index, token);
        true
    }
    pub(crate) fn notify_all(&self) {
        let original_count = self.count.get();
        assert!(original_count <= MAX_WAITERS, "logical notify bound");
        for _ in 0..original_count {
            if !self.notify_one(|_| {}) {
                break;
            }
        }
    }
}
impl Drop for WaitQueue {
    fn drop(&mut self) {
        assert!(
            self.is_empty() && self.head.get().is_null() && self.tail.get().is_null(),
            "destroying a queue with live logical waiters"
        );
    }
}

pub(crate) struct Wait<'a> {
    queue: &'a WaitQueue,
    pointer: *mut Node,
    lease: Option<WaitLease>,
}
impl Wait<'_> {
    fn token(&self) -> Token {
        self.lease.as_ref().expect("live admitted wait").token()
    }
    pub(crate) fn cancel(self) {
        drop(self);
    }
    pub(crate) fn wait(self) -> bool {
        // Runtime looks up each live node from the original generation+Wait
        // token after every yield. It must not retain another node pointer
        // while awaiting a timer/native operation whose caller may resume.
        runtime::drive_wait(self.token());
        match unsafe { (*self.pointer).state.get() } {
            State::Notified => true,
            State::TimedOut => false,
            State::Waiting => panic!("wait returned without readiness or elapsed timer"),
        }
    }
}
impl Drop for Wait<'_> {
    fn drop(&mut self) {
        self.queue.unlink(self.pointer);
        let mut lease = self.lease.take().expect("one affine logical wait");
        // Remove all runtime references before releasing the reserved fixed
        // node. Host Timer/Wait settlement may suspend, so it follows physical
        // node removal. Pending native timer state retains its own charge.
        runtime::unregister_wait(&mut lease, self.pointer);
        unsafe {
            runtime::deallocate_wait_node(&mut lease, self.pointer);
        }
        drop(lease);
    }
}

/// Called only after a real matching timer returned readiness and its token
/// was looked up again in the live runtime registry after the host await.
/// Root cancellation/deadline/error must never call this elapsed-time path.
pub(crate) unsafe fn elapsed(pointer: *mut Node) {
    let (index, token) = unsafe {
        let node = &*pointer;
        if node.state.get() != State::Waiting {
            return;
        }
        let queue = &*node.queue;
        queue.unlink(pointer);
        node.state.set(State::TimedOut);
        (node.index, node.token)
    };
    runtime::wake_wait(index, token);
}
pub(crate) unsafe fn waiting(pointer: *const Node) -> bool {
    unsafe { (*pointer).state.get() == State::Waiting }
}
