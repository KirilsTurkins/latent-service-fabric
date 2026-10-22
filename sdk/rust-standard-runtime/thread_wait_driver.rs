// SPDX-License-Identifier: MIT OR Apache-2.0
//! Real original-ledger/canonical waiter bridge for the selected std PAL.
//! The enclosing PAL supplies current_task from selected TLS, not a prefix's
//! lazy-root zero token. No mutable registry borrow crosses a broker operation,
//! canonical suspension, timer host await, allocator, or user callback.
use super::owner::{self, Error, Kind, Owner};
use super::wait_registry::{Domain, Registry, Reservation, Start, Wake};
use super::{current_index, current_task, Token};
use crate::cell::UnsafeCell;
use crate::sys::thread::lsf::wait::{self, Node};
use crate::time::Duration;

// Fixed linear-memory state. This module is only valid in the explicitly
// selected unshared, cooperative, nonreentrant Store. Access closures below
// perform Copy-only bounded state changes; they may not invoke the engine.
struct Storage(UnsafeCell<Registry>);
unsafe impl Sync for Storage {}
static WAITS: Storage = Storage(UnsafeCell::new(Registry::new()));
fn state<R>(f: impl FnOnce(&mut Registry) -> R) -> R {
    unsafe { f(&mut *WAITS.0.get()) }
}
pub(crate) fn quiescent() -> bool { state(|r| r.is_empty()) }

pub(crate) struct WaitLease {
    wait: Owner,
    timer: Option<Token>,
    index: u32,
    registered: bool,
    reservation: Slot,
}
struct Slot(Option<Reservation>);
impl Drop for Slot {
    fn drop(&mut self) {
        if let Some(ticket) = self.0.take() {
            state(|r| r.cancel(ticket)).expect("stale std Wait capacity reservation");
        }
    }
}
impl WaitLease {
    pub(crate) fn admit(timeout: Option<Duration>) -> Self {
        let index = current_index();
        let reservation = Slot(Some(
            state(|r| r.reserve(index))
                .expect("bounded std Wait registry exhausted before admission"),
        ));
        let task = current_task();
        assert!(task.valid(), "wait requires a real current Task");
        let wait = Owner::admit(Kind::Wait, Some(task))
            .unwrap_or_else(|error| panic!("std Wait admission rejected: {:?}", error));
        // The admitted Wait is a still-live parent for its one-shot timer.
        // The timer host owns its real Timer record and timer-next's separate
        // physical Wait. All use the original limits, without a fresh quota.
        let timer = timeout.map(|duration| {
            let nanos = u64::try_from(duration.as_nanos())
                .expect("std timeout exceeds the supported monotonic range");
            timer_start(nanos, wait.token())
                .unwrap_or_else(|error| panic!("std Timer admission rejected: {:?}", error))
        });
        assert_eq!(
            current_index(),
            index,
            "admission restored another canonical thread"
        );
        Self {
            wait,
            timer,
            index,
            registered: false,
            reservation,
        }
    }
    pub(crate) fn token(&self) -> Token {
        self.wait.token()
    }
}
impl Drop for WaitLease {
    fn drop(&mut self) {
        assert!(!self.registered, "freeing a still-registered std Wait");
        if let Some(timer) = self.timer.take() {
            timer_stop(timer)
                .unwrap_or_else(|error| panic!("std Timer close rejected: {:?}", error));
        }
        // The affine Wait field settles only after timer close returned and
        // the queue node was unlinked, unregistered and physically freed.
    }
}

pub(crate) fn register_wait(lease: &mut WaitLease, pointer: *mut Node) {
    assert!(!lease.registered && current_index() == lease.index);
    let domain = lease
        .timer
        .map_or(Domain::CanonicalSuspend, |timer| Domain::EngineTimerAwait {
            timer,
        });
    let ticket = lease
        .reservation
        .0
        .take()
        .expect("one std Wait registry reservation");
    state(|r| r.install(ticket, lease.token(), lease.index, pointer.addr(), domain))
        .expect("std Wait identity publication refused");
    lease.registered = true;
}
pub(crate) fn unregister_wait(lease: &mut WaitLease, pointer: *mut Node) {
    assert!(lease.registered && current_index() == lease.index);
    lease.timer = state(|r| r.remove(lease.token(), lease.index, pointer.addr()))
        .expect("std Wait removal before actual return or with stale identity");
    lease.registered = false;
}

pub(crate) fn wake_wait(index: u32, token: Token) {
    // The queue already installed Notified or TimedOut and any mutex handoff.
    // In particular, it must not read the node after this function can yield.
    let action = state(|r| r.notify(token, index)).expect("stale std Wait notification");
    match action {
        Wake::BeforeSuspension | Wake::AlreadyReady => {}
        Wake::ResumeExplicitlySuspended { canonical } => unsafe {
            resume_later(canonical);
        },
        Wake::StopTimer { timer } => {
            // Claiming the stop happened in the Copy state BEFORE the host
            // call. No row or node is accessed afterwards: timer-next may
            // return and the waiter may free both during this call.
            timer_stop(timer)
                .unwrap_or_else(|error| panic!("notified std Timer close rejected: {:?}", error));
        }
    }
}

pub(crate) fn drive_wait(token: Token) {
    let index = current_index();
    let task = current_task();
    owner::park_task(task).unwrap_or_else(|error| panic!("std Task park rejected: {:?}", error));
    let start = state(|r| r.start(token, index)).expect("std Wait suspension state");
    let mut canonical_cancelled = 0;
    // No checkpoint may be inserted between publishing Waiting and these
    // exact canonical operations. The selected compiler must prove this.
    match start {
        Start::AlreadyNotified => {}
        Start::SuspendCanonical => {
            canonical_cancelled = unsafe { suspend() };
            assert_eq!(
                current_index(),
                index,
                "suspend resumed another canonical thread"
            );
            state(|r| r.returned(token, index)).expect("unsolicited canonical std Wait resume");
        }
        Start::AwaitTimer { timer } => {
            let result = timer_next(timer);
            assert_eq!(
                current_index(),
                index,
                "timer resumed another canonical thread"
            );
            match result {
                Ok(0) => {
                    if state(|r| r.elapsed(token, timer, index)).expect("stale std Timer readiness")
                    {
                        let pointer = state(|r| r.pointer(token, index))
                            .expect("elapsed std Wait node vanished")
                            as *mut Node;
                        // No engine operation/borrow is live at this lookup.
                        // elapsed unlinks/marks the node before its wake call.
                        unsafe {
                            wait::elapsed(pointer);
                        }
                    }
                }
                // A real notification can close ONLY this timer. The live
                // wake below rechecks root cancellation/deadline/authority;
                // the error is never converted into elapsed sleep success.
                Err(Error::Cancelled)
                    if state(|r| r.notified(token, index))
                        .expect("cancelled std Wait identity vanished") => {}
                other => panic!("std Timer wait did not complete: {:?}", other),
            }
            state(|r| r.returned(token, index)).expect("std Timer frame still live");
        }
    }
    // This existing authoritative operation also refuses a stopped/revoked
    // root. A local timer-stop Cancelled must not conceal global cancellation.
    owner::wake_task(task).unwrap_or_else(|error| panic!("std Task wake rejected: {:?}", error));
    assert_eq!(canonical_cancelled, 0, "canonical std Wait was cancelled");
}

#[repr(C, align(8))]
struct TokenResult([u8; 24]);
#[repr(C, align(8))]
struct TimerResult([u8; 16]);
fn timer_start(nanos: u64, parent: Token) -> Result<Token, Error> {
    let mut result = TokenResult([0xff; 24]);
    unsafe {
        start_timer(
            nanos,
            0,
            0,
            1,
            parent.generation,
            parent.id,
            result.0.as_mut_ptr(),
        );
    }
    match result.0[0] {
        0 => {
            let token = Token {
                generation: u64::from_le_bytes(result.0[8..16].try_into().unwrap()),
                id: u64::from_le_bytes(result.0[16..24].try_into().unwrap()),
            };
            assert!(
                token.valid() && token != parent,
                "invalid canonical Timer result"
            );
            Ok(token)
        }
        1 => Err(owner::error(result.0[8])),
        _ => panic!("invalid canonical timer-start discriminant"),
    }
}
fn timer_next(timer: Token) -> Result<u64, Error> {
    let mut result = TimerResult([0xff; 16]);
    unsafe {
        next_timer(timer.generation, timer.id, result.0.as_mut_ptr());
    }
    match result.0[0] {
        0 => Ok(u64::from_le_bytes(result.0[8..16].try_into().unwrap())),
        1 => Err(owner::error(result.0[8])),
        _ => panic!("invalid canonical timer-next discriminant"),
    }
}
fn timer_stop(timer: Token) -> Result<(), Error> {
    let mut result = [0xff; 2];
    unsafe {
        stop_timer(timer.generation, timer.id, result.as_mut_ptr());
    }
    match result[0] {
        0 => Ok(()),
        1 => Err(owner::error(result[1])),
        _ => panic!("invalid canonical timer-stop discriminant"),
    }
}

#[cfg_attr(target_arch = "wasm32", link(wasm_import_module = "$root"))]
unsafe extern "C" {
    #[cfg_attr(target_arch = "wasm32", link_name = "[thread-suspend]")]
    fn suspend() -> u32;
    #[cfg_attr(target_arch = "wasm32", link_name = "[thread-resume-later]")]
    fn resume_later(index: u32);
}
#[cfg_attr(
    target_arch = "wasm32",
    link(wasm_import_module = "latent:runtime/activation@0.1.0")
)]
unsafe extern "C" {
    #[cfg_attr(target_arch = "wasm32", link_name = "timer-start")]
    fn start_timer(
        nanos: u64,
        period_present: u32,
        period: u64,
        continuation_present: u32,
        generation: u64,
        id: u64,
        result: *mut u8,
    );
    #[cfg_attr(target_arch = "wasm32", link_name = "timer-next")]
    fn next_timer(generation: u64, id: u64, result: *mut u8);
    #[cfg_attr(target_arch = "wasm32", link_name = "timer-stop")]
    fn stop_timer(generation: u64, id: u64, result: *mut u8);
}
