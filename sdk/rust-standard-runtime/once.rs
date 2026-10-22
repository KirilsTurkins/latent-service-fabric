// SPDX-License-Identifier: MIT OR Apache-2.0
//! Pinned std Once shape with real contended logical waiters and poison state.
use crate::cell::Cell;
use crate::sync as public;
use crate::sync::atomic::{Ordering, compiler_fence};
use crate::sync::once::OnceExclusiveState;
use crate::sys::thread::lsf::{runtime, wait::WaitQueue};

#[derive(Clone, Copy, PartialEq, Eq)]
enum State { Incomplete, Poisoned, Running, Complete }
pub struct Once {
    state: Cell<State>,
    runner: Cell<Option<u32>>,
    waiters: WaitQueue,
}
pub struct OnceState {
    poisoned: bool,
    set_state_to: Cell<State>,
}
struct CompletionGuard<'a> { once: &'a Once, next: State }
impl Drop for CompletionGuard<'_> {
    fn drop(&mut self) {
        assert!(self.once.state.get() == State::Running, "Once completion state");
        assert_eq!(self.once.runner.get(), Some(runtime::current_index()), "Once completion owner");
        compiler_fence(Ordering::Release);
        self.once.runner.set(None);
        self.once.state.set(self.next);
        // State and runner are final before waking an eligible waiter can yield.
        self.once.waiters.notify_all();
    }
}
unsafe impl Sync for Once {}
impl Once {
    pub const fn new() -> Self { Self::with_state(State::Incomplete) }
    pub const fn new_complete() -> Self { Self::with_state(State::Complete) }
    const fn with_state(state: State) -> Self {
        Self { state: Cell::new(state), runner: Cell::new(None), waiters: WaitQueue::new() }
    }
    pub fn is_completed(&self) -> bool {
        let complete = self.state.get() == State::Complete;
        if complete { compiler_fence(Ordering::Acquire); }
        complete
    }
    pub(crate) fn state(&mut self) -> OnceExclusiveState {
        match self.state.get() {
            State::Incomplete => OnceExclusiveState::Incomplete,
            State::Poisoned => OnceExclusiveState::Poisoned,
            State::Complete => OnceExclusiveState::Complete,
            State::Running => panic!("exclusive access to running Once"),
        }
    }
    pub(crate) fn set_state(&mut self, state: OnceExclusiveState) {
        assert!(self.runner.get().is_none() && self.waiters.is_empty(), "live exclusive Once state");
        self.state.set(match state {
            OnceExclusiveState::Incomplete => State::Incomplete,
            OnceExclusiveState::Poisoned => State::Poisoned,
            OnceExclusiveState::Complete => State::Complete,
        });
    }
    #[cold]
    #[track_caller]
    pub fn wait(&self, ignore_poisoning: bool) {
        loop {
            match self.state.get() {
                State::Complete => { compiler_fence(Ordering::Acquire); return; }
                State::Poisoned if !ignore_poisoning => panic!("Once instance has previously been poisoned"),
                _ => {}
            }
            assert_ne!(self.runner.get(), Some(runtime::current_index()), "recursive Once wait");
            let wait = self.waiters.prepare(None);
            if matches!(self.state.get(), State::Complete)
                || self.state.get() == State::Poisoned && !ignore_poisoning {
                wait.cancel();
            } else { wait.wait(); }
        }
    }
    #[cold]
    #[track_caller]
    pub fn call(&self, ignore_poisoning: bool, f: &mut impl FnMut(&public::OnceState)) {
        loop {
            match self.state.get() {
                State::Complete => { compiler_fence(Ordering::Acquire); return; }
                State::Poisoned if !ignore_poisoning => panic!("Once instance has previously been poisoned"),
                State::Running => {
                    assert_ne!(self.runner.get(), Some(runtime::current_index()), "recursive Once initialization");
                    let wait = self.waiters.prepare(None);
                    if self.state.get() == State::Running { wait.wait(); }
                    else { wait.cancel(); }
                }
                state @ (State::Incomplete | State::Poisoned) => {
                    self.runner.set(Some(runtime::current_index()));
                    self.state.set(State::Running);
                    let mut guard = CompletionGuard { once: self, next: State::Poisoned };
                    let argument = public::OnceState { inner: OnceState {
                        poisoned: state == State::Poisoned,
                        set_state_to: Cell::new(State::Complete),
                    }};
                    f(&argument);
                    guard.next = argument.inner.set_state_to.get();
                    drop(guard);
                    return;
                }
            }
        }
    }
}
impl OnceState {
    pub fn is_poisoned(&self) -> bool { self.poisoned }
    pub fn poison(&self) { self.set_state_to.set(State::Poisoned); }
}
