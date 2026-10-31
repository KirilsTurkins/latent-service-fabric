//! Actual owner/queue/driver bodies with explicit canonical/host/TLS ports.
//! These are bounded source controls, not engine suspension or sysroot proof.
#![allow(dead_code)]
use std::cell::RefCell;
use std::collections::{BTreeMap, BTreeSet};
pub use std::{cell, mem, ptr, time};
pub mod alloc {
    pub use std::alloc::{GlobalAlloc, Layout, System};
}
#[path = "../runtime_owner.rs"]
mod owner;
use owner::{Kind, Token};
#[path = "../thread_wait_driver.rs"]
mod driver;
#[path = "../thread_wait.rs"]
pub mod wait;
#[path = "../thread_wait_registry.rs"]
mod wait_registry;
pub mod sys {
    pub mod thread {
        pub mod lsf {
            pub use crate::wait;
            pub mod runtime {
                pub(crate) use crate::driver::*;
                pub(crate) use crate::{current_index, Token};
            }
        }
    }
}

const ROOT: Token = Token {
    generation: 41,
    id: 99,
};
pub(crate) fn current_task() -> Token {
    ROOT
}
pub(crate) fn current_index() -> u32 {
    0
}
#[derive(Default)]
struct Ports {
    next: u64,
    owners: BTreeMap<u64, u32>,
    timers: BTreeSet<u64>,
    calls: Vec<&'static str>,
    suspend: Option<Box<dyn FnOnce()>>,
    suspend_cancelled: u32,
    next_timer: Option<Box<dyn FnOnce()>>,
    park: Option<Box<dyn FnOnce()>>,
    timer_error: Option<u8>,
    timer_start_error: Option<u8>,
    malformed_start: bool,
    wake_error: Option<u8>,
    timer_closed: bool,
}
std::thread_local! { static PORTS: RefCell<Ports> = RefCell::new(Ports::default()); }
fn reset() {
    PORTS.with(|p| {
        let mut p = p.borrow_mut();
        assert!(
            p.owners.is_empty() && p.timers.is_empty(),
            "previous actual backing still live"
        );
        *p = Ports::default();
    });
}
fn call(name: &'static str) {
    PORTS.with(|p| p.borrow_mut().calls.push(name));
}
fn calls() -> Vec<&'static str> {
    PORTS.with(|p| p.borrow().calls.clone())
}
fn assert_retired() {
    PORTS.with(|p| {
        let p = p.borrow();
        assert!(p.owners.is_empty() && p.timers.is_empty());
        assert_eq!(p.calls.last(), Some(&"settle-wait"));
    });
}
unsafe fn success(out: *mut u8) {
    unsafe {
        out.write(0);
    }
}
unsafe fn failure(out: *mut u8, error: u8) {
    unsafe {
        out.write(1);
        out.add(1).write(error);
    }
}
unsafe fn write_token(out: *mut u8, token: Token) {
    unsafe {
        success(out);
        ptr::copy_nonoverlapping(token.generation.to_le_bytes().as_ptr(), out.add(8), 8);
        ptr::copy_nonoverlapping(token.id.to_le_bytes().as_ptr(), out.add(16), 8);
    }
}
#[unsafe(no_mangle)]
unsafe extern "C" fn register(kind: u32, present: u32, generation: u64, parent: u64, out: *mut u8) {
    assert_eq!((present, generation), (1, ROOT.generation));
    assert_eq!(parent, ROOT.id, "actual TLS Task, never root prefix zero");
    let id = PORTS.with(|p| {
        let mut p = p.borrow_mut();
        p.next += 1;
        let id = p.next;
        assert!(p.owners.insert(id, kind).is_none());
        id
    });
    call(match kind {
        4 => "admit-wait",
        _ => panic!("unexpected owner"),
    });
    unsafe {
        write_token(out, Token { generation, id });
    }
}
#[unsafe(no_mangle)]
unsafe extern "C" fn settle(generation: u64, id: u64, out: *mut u8) {
    assert_eq!(generation, ROOT.generation);
    let kind = PORTS.with(|p| p.borrow_mut().owners.remove(&id).unwrap());
    assert_eq!(kind, Kind::Wait as u32);
    call("settle-wait");
    unsafe {
        success(out);
    }
}
#[unsafe(no_mangle)]
unsafe extern "C" fn park(generation: u64, id: u64, out: *mut u8) {
    assert_eq!((generation, id), (ROOT.generation, ROOT.id));
    call("park-task");
    let callback = PORTS.with(|p| p.borrow_mut().park.take());
    if let Some(callback) = callback {
        callback();
    }
    unsafe {
        success(out);
    }
}
#[unsafe(no_mangle)]
unsafe extern "C" fn wake(generation: u64, id: u64, out: *mut u8) {
    assert_eq!((generation, id), (ROOT.generation, ROOT.id));
    call("wake-task");
    if let Some(error) = PORTS.with(|p| p.borrow().wake_error) {
        unsafe {
            failure(out, error);
        }
    } else {
        unsafe {
            success(out);
        }
    }
}
#[unsafe(no_mangle)]
unsafe extern "C" fn suspend() -> u32 {
    call("suspend");
    let callback = PORTS.with(|p| p.borrow_mut().suspend.take().unwrap());
    callback();
    // Pinned libcall returns a cancellation bool, never a resumer index.
    PORTS.with(|p| p.borrow().suspend_cancelled)
}
#[unsafe(no_mangle)]
unsafe extern "C" fn resume_later(index: u32) {
    assert_eq!(index, 0);
    call("resume-later");
}
#[unsafe(no_mangle)]
unsafe extern "C" fn start_timer(
    nanos: u64,
    period_present: u32,
    period: u64,
    present: u32,
    generation: u64,
    parent: u64,
    out: *mut u8,
) {
    assert_eq!(
        (period_present, period, present, generation),
        (0, 0, 1, ROOT.generation)
    );
    assert!(nanos > 0);
    call("timer-start");
    let error = PORTS.with(|p| p.borrow().timer_start_error);
    if let Some(error) = error {
        unsafe {
            out.write(1);
            out.add(8).write(error);
        }
        return;
    }
    if PORTS.with(|p| p.borrow().malformed_start) {
        unsafe {
            out.write(17);
        }
        return;
    }
    let id = PORTS.with(|p| {
        let mut p = p.borrow_mut();
        assert_eq!(p.owners.get(&parent), Some(&(Kind::Wait as u32)));
        p.next += 1;
        let id = p.next;
        p.timers.insert(id);
        id
    });
    unsafe {
        write_token(out, Token { generation, id });
    }
}
#[unsafe(no_mangle)]
unsafe extern "C" fn next_timer(generation: u64, id: u64, out: *mut u8) {
    assert_eq!(generation, ROOT.generation);
    assert!(PORTS.with(|p| p.borrow().timers.contains(&id)));
    call("timer-next");
    let callback = PORTS.with(|p| p.borrow_mut().next_timer.take());
    if let Some(callback) = callback {
        callback();
    }
    if let Some(error) = PORTS.with(|p| p.borrow().timer_error) {
        unsafe {
            out.write(1);
            out.add(8).write(error);
        }
    } else {
        unsafe {
            success(out);
            ptr::write_unaligned(out.add(8).cast::<u64>(), 0);
        }
    }
}
#[unsafe(no_mangle)]
unsafe extern "C" fn stop_timer(generation: u64, id: u64, out: *mut u8) {
    assert_eq!(generation, ROOT.generation);
    assert!(
        PORTS.with(|p| p.borrow_mut().timers.remove(&id)),
        "one actual close, not duplicate"
    );
    call("timer-stop");
    PORTS.with(|p| p.borrow_mut().timer_closed = true);
    unsafe {
        success(out);
    }
}
fn notify(queue: &wait::WaitQueue) -> Box<dyn FnOnce()> {
    let pointer = queue as *const wait::WaitQueue;
    Box::new(move || assert!(unsafe { &*pointer }.notify_one(|_| {})))
}

#[test]
fn early_untimed_notification_never_resumes_a_running_thread() {
    reset();
    let q = wait::WaitQueue::new();
    let wait = q.prepare(None);
    assert!(q.notify_one(|_| {}));
    assert!(wait.wait());
    assert_eq!(
        calls(),
        ["admit-wait", "park-task", "wake-task", "settle-wait"]
    );
    assert_retired();
}
#[test]
fn untimed_wait_uses_exact_explicit_canonical_suspension_after_park() {
    reset();
    let q = wait::WaitQueue::new();
    PORTS.with(|p| p.borrow_mut().suspend = Some(notify(&q)));
    assert!(q.prepare(None).wait());
    assert_eq!(
        calls(),
        [
            "admit-wait",
            "park-task",
            "suspend",
            "resume-later",
            "wake-task",
            "settle-wait"
        ]
    );
    assert_retired();
}
#[test]
fn a_notification_during_task_park_is_rechecked_before_suspension() {
    reset();
    let q = wait::WaitQueue::new();
    PORTS.with(|p| p.borrow_mut().park = Some(notify(&q)));
    assert!(q.prepare(None).wait());
    assert!(!calls()
        .iter()
        .any(|c| matches!(*c, "suspend" | "resume-later")));
    assert_retired();
}
#[test]
fn only_actual_one_shot_readiness_becomes_elapsed_sleep() {
    reset();
    let q = wait::WaitQueue::new();
    assert!(!q.prepare(Some(time::Duration::from_nanos(23))).wait());
    assert_eq!(
        calls(),
        [
            "admit-wait",
            "timer-start",
            "park-task",
            "timer-next",
            "wake-task",
            "timer-stop",
            "settle-wait"
        ]
    );
    assert_retired();
}
#[test]
fn timed_notification_stops_only_its_timer_and_never_resumes_an_engine_await() {
    reset();
    let q = wait::WaitQueue::new();
    PORTS.with(|p| {
        let mut p = p.borrow_mut();
        p.next_timer = Some(notify(&q));
        p.timer_error = Some(3); // Actual typed Cancelled from this timer stop.
    });
    assert!(q.prepare(Some(time::Duration::from_nanos(23))).wait());
    assert_eq!(calls().iter().filter(|c| **c == "timer-stop").count(), 1);
    assert!(!calls().contains(&"resume-later"));
    assert_retired();
}
#[test]
fn early_timed_notification_closes_without_entering_timer_next() {
    reset();
    let q = wait::WaitQueue::new();
    let wait = q.prepare(Some(time::Duration::from_nanos(23)));
    q.notify_all();
    assert!(wait.wait());
    assert!(!calls().contains(&"timer-next"));
    assert_eq!(calls().iter().filter(|c| **c == "timer-stop").count(), 1);
    assert_retired();
}
#[test]
fn local_timer_close_does_not_hide_root_cancellation_on_authoritative_wake() {
    reset();
    let q = wait::WaitQueue::new();
    PORTS.with(|p| {
        let mut p = p.borrow_mut();
        p.next_timer = Some(notify(&q));
        p.timer_error = Some(3);
        p.wake_error = Some(3);
    });
    let error = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        q.prepare(Some(time::Duration::from_nanos(23))).wait()
    }))
    .unwrap_err();
    assert!(error
        .downcast_ref::<String>()
        .unwrap()
        .contains("std Task wake rejected: Cancelled"));
    assert_retired();
}
#[test]
fn real_timer_admission_refusal_precedes_node_allocation_and_publication() {
    reset();
    PORTS.with(|p| p.borrow_mut().timer_start_error = Some(2));
    let q = wait::WaitQueue::new();
    let error = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        q.prepare(Some(time::Duration::from_nanos(23)))
    }))
    .err()
    .unwrap();
    assert!(error
        .downcast_ref::<String>()
        .unwrap()
        .contains("Timer admission rejected: ResourceExhausted"));
    assert_eq!(calls(), ["admit-wait", "timer-start", "settle-wait"]);
    assert_retired();
}
#[test]
fn malformed_canonical_result_is_refused_without_publishing_a_waiter() {
    reset();
    PORTS.with(|p| p.borrow_mut().malformed_start = true);
    let q = wait::WaitQueue::new();
    assert!(std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        q.prepare(Some(time::Duration::from_nanos(23)))
    }))
    .is_err());
    assert_eq!(calls(), ["admit-wait", "timer-start", "settle-wait"]);
    assert_retired();
}

#[test]
fn nested_same_thread_wait_is_refused_before_any_second_admission_or_node_allocation() {
    reset();
    let q = wait::WaitQueue::new();
    let first = q.prepare(None);
    assert_eq!(calls(), ["admit-wait"]);
    let error = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| q.prepare(None)));
    assert!(error.is_err());
    assert_eq!(calls(), ["admit-wait"]);
    first.cancel();
    assert_retired();
}

#[test]
fn canonical_cancelled_result_cannot_become_a_successful_notified_wait() {
    reset();
    let q = wait::WaitQueue::new();
    PORTS.with(|p| {
        let mut p = p.borrow_mut();
        p.suspend = Some(notify(&q));
        p.suspend_cancelled = 1;
    });
    let error = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| q.prepare(None).wait()))
        .unwrap_err();
    assert!(error
        .downcast_ref::<String>()
        .unwrap()
        .contains("canonical std Wait was cancelled"));
    assert!(
        calls().contains(&"wake-task"),
        "authoritative root liveness recheck retained"
    );
    assert_retired();
}
