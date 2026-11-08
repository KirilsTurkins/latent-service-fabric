//! Copied production synchronization bodies with explicit canonical/ledger ports.
//! These are source state-machine controls, not a real guest scheduler or proof.
pub use std::{cell, pin, ptr, time};
pub mod sync {
    pub use std::sync::atomic;
    pub struct OnceState { pub(crate) inner: crate::once::OnceState }
    pub mod once {
        #[derive(Debug, PartialEq, Eq)]
        pub enum OnceExclusiveState { Incomplete, Poisoned, Complete }
    }
}
pub mod sys {
    pub mod sync { pub use crate::mutex::Mutex; }
    pub mod thread {
        pub mod lsf {
            pub use crate::wait;
            pub mod runtime {
                use crate::cell::{Cell, RefCell};
                use crate::time::Duration;
                use super::wait::{self, Node};
                use std::collections::{BTreeMap, BTreeSet};
                #[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord)]
                pub struct Token(u64);
                #[derive(Default)]
                struct Ports {
                    index: Cell<u32>,
                    next: Cell<u64>,
                    live: RefCell<BTreeMap<Token, Option<*mut Node>>>,
                    timers: RefCell<BTreeSet<Token>>,
                    last_timeout: Cell<Option<Duration>>,
                    timed_durations: RefCell<Vec<Duration>>,
                    refuse_timer: Cell<bool>,
                    refuse_wait: Cell<bool>,
                    refuse_immediate: Cell<bool>,
                    wait_admissions: Cell<usize>,
                    immediate_calls: Cell<usize>,
                    on_index: RefCell<Option<Box<dyn FnOnce()>>>,
                    on_immediate: RefCell<Option<Box<dyn FnOnce()>>>,
                    on_admit: RefCell<Option<Box<dyn FnOnce()>>>,
                    on_wait: RefCell<Option<Box<dyn FnOnce()>>>,
                    on_wake: RefCell<Option<Box<dyn FnOnce()>>>,
                }
                std::thread_local! { static PORTS: Ports = Ports::default(); }
                pub struct WaitLease(Token);
                impl WaitLease {
                    pub fn admit(timeout: Option<Duration>) -> Self {
                        PORTS.with(|p| {
                            p.wait_admissions.set(p.wait_admissions.get() + 1);
                            assert!(!p.refuse_wait.get(), "port: Wait admission refused");
                        });
                        if let Some(duration) = timeout {
                            PORTS.with(|p| assert!(!p.refuse_timer.get(), "port: Timer admission refused"));
                            u64::try_from(duration.as_nanos())
                                .expect("std timeout exceeds the supported monotonic range");
                            PORTS.with(|p| p.last_timeout.set(Some(duration)));
                            PORTS.with(|p| p.timed_durations.borrow_mut().push(duration));
                        }
                        let token = PORTS.with(|p| {
                            let id = p.next.get() + 1; p.next.set(id);
                            let token = Token(id);
                            assert!(p.live.borrow_mut().insert(token, None).is_none());
                            if timeout.is_some() { assert!(p.timers.borrow_mut().insert(token)); }
                            token
                        });
                        // Taking the callback releases the port borrow before
                        // it simulates a canonical handoff during host admission.
                        let callback = PORTS.with(|p| p.on_admit.borrow_mut().take());
                        if let Some(callback) = callback { callback(); }
                        Self(token)
                    }
                    pub fn token(&self) -> Token { self.0 }
                    pub fn immediate_ready(self) {
                        let _ = current_index();
                        PORTS.with(|p| {
                            assert_eq!(p.live.borrow().get(&self.0), Some(&None));
                            p.immediate_calls.set(p.immediate_calls.get() + 1);
                            assert!(!p.refuse_immediate.get(), "port: terminal Task wake refused");
                        });
                        let callback = PORTS.with(|p| p.on_immediate.borrow_mut().take());
                        if let Some(callback) = callback { callback(); }
                    }
                }
                impl Drop for WaitLease {
                    fn drop(&mut self) {
                        PORTS.with(|p| assert_eq!(p.live.borrow_mut().remove(&self.0), Some(None)));
                        PORTS.with(|p| { p.timers.borrow_mut().remove(&self.0); });
                    }
                }
                pub fn current_index() -> u32 {
                    let callback = PORTS.with(|p| p.on_index.borrow_mut().take());
                    if let Some(callback) = callback { callback(); }
                    PORTS.with(|p| p.index.get())
                }
                pub fn index(index: u32) { PORTS.with(|p| p.index.set(index)); }
                pub fn on_index(f: impl FnOnce() + 'static) { PORTS.with(|p| *p.on_index.borrow_mut() = Some(Box::new(f))); }
                pub fn on_immediate(f: impl FnOnce() + 'static) { PORTS.with(|p| *p.on_immediate.borrow_mut() = Some(Box::new(f))); }
                pub fn refuse_timer(value: bool) { PORTS.with(|p| p.refuse_timer.set(value)); }
                pub fn refuse_wait(value: bool) { PORTS.with(|p| p.refuse_wait.set(value)); }
                pub fn refuse_immediate(value: bool) { PORTS.with(|p| p.refuse_immediate.set(value)); }
                pub fn wait_admissions() -> usize { PORTS.with(|p| p.wait_admissions.get()) }
                pub fn immediate_calls() -> usize { PORTS.with(|p| p.immediate_calls.get()) }
                pub fn live() -> usize { PORTS.with(|p| p.live.borrow().len()) }
                pub fn last_timeout() -> Option<Duration> { PORTS.with(|p| p.last_timeout.get()) }
                pub fn timed_durations() -> Vec<Duration> { PORTS.with(|p| p.timed_durations.borrow().clone()) }
                pub fn on_admit(f: impl FnOnce() + 'static) { PORTS.with(|p| *p.on_admit.borrow_mut() = Some(Box::new(f))); }
                pub fn on_wait(f: impl FnOnce() + 'static) { PORTS.with(|p| *p.on_wait.borrow_mut() = Some(Box::new(f))); }
                pub fn on_wake(f: impl FnOnce() + 'static) { PORTS.with(|p| *p.on_wake.borrow_mut() = Some(Box::new(f))); }
                pub(crate) fn allocate_wait_node(_lease: &mut WaitLease, value: Node) -> *mut Node {
                    Box::into_raw(Box::new(value))
                }
                pub(crate) unsafe fn deallocate_wait_node(_lease: &mut WaitLease, pointer: *mut Node) {
                    drop(unsafe { Box::from_raw(pointer) });
                }
                pub(crate) fn register_wait(lease: &mut WaitLease, node: *mut Node) {
                    let token = lease.token();
                    PORTS.with(|p| {
                        let mut live = p.live.borrow_mut();
                        let entry = live.get_mut(&token).expect("admitted before register");
                        assert!(entry.replace(node).is_none());
                    });
                }
                pub(crate) fn unregister_wait(lease: &mut WaitLease, node: *mut Node) {
                    let token = lease.token();
                    PORTS.with(|p| {
                        let mut live = p.live.borrow_mut();
                        assert_eq!(live.get_mut(&token).expect("registered waiter").take(), Some(node));
                    });
                }
                pub fn wake_wait(_index: u32, token: Token) {
                    let node = PORTS.with(|p| p.live.borrow()[&token].unwrap());
                    assert!(!unsafe { wait::waiting(node) });
                    let callback = PORTS.with(|p| p.on_wake.borrow_mut().take());
                    if let Some(callback) = callback { callback(); }
                }
                pub fn drive_wait(token: Token) {
                    let callback = PORTS.with(|p| p.on_wait.borrow_mut().take());
                    if let Some(callback) = callback { callback(); }
                    let node = PORTS.with(|p| p.live.borrow()[&token].unwrap());
                    assert!(!unsafe { wait::waiting(node) }, "source port supplied no real readiness");
                }
                pub fn expire_one_live_timer() {
                    let token = PORTS.with(|p| {
                        assert_eq!(p.timers.borrow().len(), 1);
                        *p.timers.borrow().first().unwrap()
                    });
                    // The port supplies only a real admitted matching Timer
                    // event. The production wait queue still decides elapsed.
                    let node = PORTS.with(|p| p.live.borrow()[&token].unwrap());
                    unsafe { wait::elapsed(node); }
                }
            }
        }
    }
}
#[path = "../thread_wait.rs"] pub mod wait;
#[path = "../mutex.rs"] mod mutex;
#[path = "../condvar.rs"] mod condvar;
#[path = "../parker.rs"] mod parker;
#[path = "../rwlock.rs"] mod rwlock;
#[path = "../once.rs"] mod once;
use sys::thread::lsf::runtime;

#[test]
fn mutex_handoff_precedes_reentrant_host_wake_and_wait_node_retirement() {
    let mutex: &'static mutex::Mutex = Box::leak(Box::new(mutex::Mutex::new()));
    runtime::index(1); mutex.lock();
    runtime::index(2);
    runtime::on_wait(move || { runtime::index(1); unsafe { mutex.unlock(); } runtime::index(2); });
    runtime::on_wake(move || { runtime::index(3); assert!(!mutex.try_lock()); runtime::index(1); });
    mutex.lock();
    runtime::index(2); unsafe { mutex.unlock(); }
    assert_eq!(runtime::live(), 0);
}

#[test]
fn mutex_rechecks_after_admission_suspension_without_losing_an_unlock() {
    let mutex: &'static mutex::Mutex = Box::leak(Box::new(mutex::Mutex::new()));
    runtime::index(1); mutex.lock(); runtime::index(2);
    runtime::on_admit(move || { runtime::index(1); unsafe { mutex.unlock(); } runtime::index(2); });
    mutex.lock(); unsafe { mutex.unlock(); }
    assert_eq!(runtime::live(), 0);
}

#[test]
fn rwlock_gate_blocks_new_readers_until_existing_reader_releases_and_writer_finishes() {
    let lock: &'static rwlock::RwLock = Box::leak(Box::new(rwlock::RwLock::new()));
    runtime::index(1); lock.read(); runtime::index(2);
    runtime::on_wait(move || {
        runtime::index(3); assert!(!lock.try_read());
        runtime::index(1); unsafe { lock.read_unlock(); }
        runtime::index(2);
    });
    lock.write(); assert!(!lock.try_read());
    unsafe { lock.downgrade(); lock.read_unlock(); }
    assert!(lock.try_write()); unsafe { lock.write_unlock(); }
    assert_eq!(runtime::live(), 0);
}

#[test]
fn once_initializer_is_run_once_and_original_poison_force_semantics_are_retained() {
    let once = once::Once::new();
    let calls = cell::Cell::new(0);
    runtime::index(1);
    once.call(false, &mut |_| calls.set(calls.get() + 1));
    once.call(false, &mut |_| panic!("completed Once reran initializer"));
    assert_eq!(calls.get(), 1);
    assert!(once.is_completed()); once.wait(false);
    let poisoned = once::Once::new();
    let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        poisoned.call(false, &mut |_| panic!("actual initializer panic"));
    }));
    assert!(result.is_err());
    assert!(!poisoned.is_completed());
    poisoned.call(true, &mut |s| assert!(s.inner.is_poisoned()));
    assert!(poisoned.is_completed());
    assert_eq!(runtime::live(), 0);
}

#[test]
fn condvar_notification_after_unlock_before_park_is_not_lost() {
    let mutex: &'static mutex::Mutex = Box::leak(Box::new(mutex::Mutex::new()));
    let condvar: &'static condvar::Condvar = Box::leak(Box::new(condvar::Condvar::new()));
    runtime::index(1); mutex.lock();
    runtime::on_wait(move || {
        runtime::index(2); mutex.lock(); condvar.notify_one(); unsafe { mutex.unlock(); }
        runtime::index(1);
    });
    unsafe { condvar.wait(mutex); mutex.unlock(); }
    assert_eq!(runtime::live(), 0);
}

#[test]
fn condvar_false_timeout_requires_matching_admitted_timer_event_and_reacquires_mutex() {
    let mutex = mutex::Mutex::new(); let condvar = condvar::Condvar::new();
    runtime::index(1); mutex.lock();
    runtime::on_wait(runtime::expire_one_live_timer);
    assert!(!unsafe { condvar.wait_timeout(&mutex, time::Duration::from_nanos(1)) });
    assert!(!mutex.try_lock()); unsafe { mutex.unlock(); }
    assert_eq!(runtime::live(), 0);
}

#[test]
fn parker_preserves_wake_before_park_one_permit_then_real_notified_and_timed_waits() {
    let mut allocation = Box::<parker::Parker>::new_uninit();
    unsafe { parker::Parker::new_in_place(allocation.as_mut_ptr()); }
    let parker: &'static parker::Parker = Box::leak(unsafe { allocation.assume_init() });
    let pinned = unsafe { pin::Pin::new_unchecked(parker) };
    runtime::index(1); pinned.unpark(); pinned.unpark(); unsafe { pinned.park(); }
    assert_eq!(runtime::live(), 0);
    runtime::on_wait(move || { runtime::index(2); pinned.unpark(); runtime::index(1); });
    unsafe { pinned.park(); }
    runtime::on_wait(runtime::expire_one_live_timer);
    unsafe { pinned.park_timeout(time::Duration::from_nanos(1)); }
    assert_eq!(runtime::live(), 0);
}

#[test]
fn missing_readiness_refuses_without_turning_cancellation_into_elapsed_success() {
    let queue = wait::WaitQueue::new();
    let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        queue.prepare(Some(time::Duration::from_nanos(1))).wait();
    }));
    assert!(result.is_err()); assert!(queue.is_empty()); assert_eq!(runtime::live(), 0);
}

#[test]
fn parker_timeout_above_host_range_uses_a_real_bounded_timer() {
    let mut allocation = Box::<parker::Parker>::new_uninit();
    unsafe { parker::Parker::new_in_place(allocation.as_mut_ptr()); }
    let parker: &'static parker::Parker = Box::leak(unsafe { allocation.assume_init() });
    let pinned = unsafe { pin::Pin::new_unchecked(parker) };
    runtime::index(1); runtime::on_wait(runtime::expire_one_live_timer);
    let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        unsafe { pinned.park_timeout(time::Duration::MAX); }
    }));
    assert!(result.is_ok(), "large park timeout should not overflow conversion");
    assert_eq!(runtime::last_timeout(), Some(time::Duration::from_nanos(u64::MAX)));
    assert_eq!(runtime::live(), 0);
}

#[test]
fn condvar_timeout_above_host_range_does_not_claim_requested_time_elapsed() {
    let mutex = mutex::Mutex::new(); let condvar = condvar::Condvar::new();
    runtime::index(1); mutex.lock(); runtime::on_wait(runtime::expire_one_live_timer);
    let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        unsafe { condvar.wait_timeout(&mutex, time::Duration::MAX) }
    }));
    assert!(!mutex.try_lock(), "original mutex must be held after the wait");
    unsafe { mutex.unlock(); }
    assert!(result.is_ok(), "large condvar timeout should not overflow conversion");
    assert!(result.unwrap(), "capped readiness is a permitted spurious return, not full elapsed time");
    assert_eq!(runtime::last_timeout(), Some(time::Duration::from_nanos(u64::MAX)));
    assert_eq!(runtime::live(), 0);
}

#[test]
fn condvar_timeout_at_exact_host_range_reports_real_elapsed_readiness() {
    let mutex = mutex::Mutex::new(); let condvar = condvar::Condvar::new();
    runtime::index(1); mutex.lock(); runtime::on_wait(runtime::expire_one_live_timer);
    assert!(!unsafe { condvar.wait_timeout(&mutex, time::Duration::from_nanos(u64::MAX)) });
    assert!(!mutex.try_lock()); unsafe { mutex.unlock(); }
    assert_eq!(runtime::live(), 0);
}

#[test]
fn large_timeout_never_fabricates_a_wake_without_timer_readiness() {
    let mut allocation = Box::<parker::Parker>::new_uninit();
    unsafe { parker::Parker::new_in_place(allocation.as_mut_ptr()); }
    let parker: &'static parker::Parker = Box::leak(unsafe { allocation.assume_init() });
    let pinned = unsafe { pin::Pin::new_unchecked(parker) };
    runtime::index(1);
    let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        unsafe { pinned.park_timeout(time::Duration::MAX); }
    }));
    assert!(result.is_err(), "missing readiness is not a spurious successful timer");
    assert_eq!(runtime::live(), 0);
}

#[test]
fn long_sleep_waits_for_every_real_bounded_timer() {
    runtime::index(1);
    let maximum = time::Duration::from_nanos(u64::MAX);
    runtime::on_wait(|| {
        runtime::expire_one_live_timer();
        runtime::on_wait(runtime::expire_one_live_timer);
        runtime::on_admit(|| assert_eq!(runtime::live(), 1, "prior Wait retired before next admission"));
    });
    wait::sleep(maximum + time::Duration::from_nanos(1));
    assert_eq!(runtime::timed_durations(), [maximum, time::Duration::from_nanos(1)]);
    assert_eq!(runtime::live(), 0);
}

#[test]
fn long_sleep_does_not_return_when_a_later_chunk_lacks_readiness() {
    runtime::index(1);
    let maximum = time::Duration::from_nanos(u64::MAX);
    runtime::on_wait(runtime::expire_one_live_timer);
    let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        wait::sleep(maximum + time::Duration::from_nanos(1));
    }));
    assert!(result.is_err(), "earlier timer readiness must not complete the whole sleep");
    assert_eq!(runtime::timed_durations(), [maximum, time::Duration::from_nanos(1)]);
    assert_eq!(runtime::live(), 0);
}

#[test]
fn zero_sleep_does_not_admit_a_timer() {
    runtime::index(1);
    wait::sleep(time::Duration::ZERO);
    assert!(runtime::timed_durations().is_empty());
    assert_eq!(runtime::live(), 0);
}

#[test]
fn ordinary_short_sleep_uses_one_exact_timer() {
    runtime::index(1); runtime::on_wait(runtime::expire_one_live_timer);
    let duration = time::Duration::from_nanos(1);
    wait::sleep(duration);
    assert_eq!(runtime::timed_durations(), [duration]);
    assert_eq!(runtime::live(), 0);
}

#[test]
fn zero_parker_timeout_publishes_immediate_ready_without_a_timer() {
    let mut allocation = Box::<parker::Parker>::new_uninit();
    unsafe { parker::Parker::new_in_place(allocation.as_mut_ptr()); }
    let parker: &'static parker::Parker = Box::leak(unsafe { allocation.assume_init() });
    let pinned = unsafe { pin::Pin::new_unchecked(parker) };
    runtime::index(1); runtime::refuse_timer(true);
    unsafe { pinned.park_timeout(time::Duration::ZERO); }
    assert_eq!((runtime::wait_admissions(), runtime::immediate_calls()), (1, 1));
    assert_eq!(runtime::live(), 0);
    // An unpark after the zero timeout remains available to the next park.
    pinned.unpark(); unsafe { pinned.park(); }
    assert_eq!(runtime::wait_admissions(), 1);
}

#[test]
fn zero_parker_consumes_unpark_that_arrives_during_wait_admission() {
    let mut allocation = Box::<parker::Parker>::new_uninit();
    unsafe { parker::Parker::new_in_place(allocation.as_mut_ptr()); }
    let parker: &'static parker::Parker = Box::leak(unsafe { allocation.assume_init() });
    let pinned = unsafe { pin::Pin::new_unchecked(parker) };
    runtime::index(1); runtime::refuse_timer(true);
    runtime::on_admit(move || pinned.unpark());
    unsafe { pinned.park_timeout(time::Duration::ZERO); }
    assert_eq!((runtime::wait_admissions(), runtime::immediate_calls()), (1, 0));
    runtime::refuse_timer(false);
    let waited = std::rc::Rc::new(cell::Cell::new(false)); let observed = waited.clone();
    runtime::on_wait(move || { observed.set(true); runtime::expire_one_live_timer(); });
    unsafe { pinned.park_timeout(time::Duration::from_nanos(1)); }
    assert!(waited.get(), "admission-time unpark was consumed exactly once");
    assert_eq!(runtime::live(), 0);
}

#[test]
fn zero_parker_preserves_unpark_after_immediate_readiness_begins() {
    let mut allocation = Box::<parker::Parker>::new_uninit();
    unsafe { parker::Parker::new_in_place(allocation.as_mut_ptr()); }
    let parker: &'static parker::Parker = Box::leak(unsafe { allocation.assume_init() });
    let pinned = unsafe { pin::Pin::new_unchecked(parker) };
    runtime::index(1); runtime::refuse_timer(true);
    // Stronger source-port reentry than the selected sync host callback.
    runtime::on_immediate(move || pinned.unpark());
    unsafe { pinned.park_timeout(time::Duration::ZERO); pinned.park(); }
    assert_eq!((runtime::wait_admissions(), runtime::immediate_calls()), (1, 1));
    assert_eq!(runtime::live(), 0);
}

#[test]
fn zero_condvar_timeout_reacquires_a_contended_mutex_without_a_timer() {
    let mutex: &'static mutex::Mutex = Box::leak(Box::new(mutex::Mutex::new()));
    let condvar = condvar::Condvar::new();
    runtime::index(1); mutex.lock(); runtime::refuse_timer(true);
    let handoff = std::rc::Rc::new(cell::Cell::new(false)); let observed = handoff.clone();
    // Probe the real Mutex between unlock/relock with stronger source-port
    // reentry; the ordinary selected host callback itself is synchronous.
    runtime::on_index(move || {
        runtime::on_index(move || {
            runtime::index(2);
            assert!(mutex.try_lock(), "second identity acquired released mutex");
            runtime::index(1);
            runtime::on_wait(move || {
                runtime::index(2); unsafe { mutex.unlock(); }
                observed.set(true); runtime::index(1);
            });
        });
    });
    assert!(!unsafe { condvar.wait_timeout(mutex, time::Duration::ZERO) });
    assert!(handoff.get(), "caller waited for the actual mutex handoff");
    assert_eq!((runtime::wait_admissions(), runtime::immediate_calls()), (2, 1));
    assert!(!mutex.try_lock(), "caller owns the mutex again");
    unsafe { mutex.unlock(); }
    assert_eq!(runtime::live(), 0);
}

#[test]
fn zero_timeouts_do_not_turn_refused_task_wake_into_success() {
    let mut allocation = Box::<parker::Parker>::new_uninit();
    unsafe { parker::Parker::new_in_place(allocation.as_mut_ptr()); }
    let parker: &'static parker::Parker = Box::leak(unsafe { allocation.assume_init() });
    let pinned = unsafe { pin::Pin::new_unchecked(parker) };
    runtime::index(1); runtime::refuse_immediate(true);
    let parked = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        unsafe { pinned.park_timeout(time::Duration::ZERO); }
    }));
    let mutex = mutex::Mutex::new(); let condvar = condvar::Condvar::new(); mutex.lock();
    let conditional = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        unsafe { condvar.wait_timeout(&mutex, time::Duration::ZERO); }
    }));
    runtime::refuse_immediate(false);
    assert!(parked.is_err() && conditional.is_err());
    // Native unwinding is only a test port: selected guest panic=abort.
    assert!(mutex.try_lock()); unsafe { mutex.unlock(); }
}

#[test]
fn zero_timeouts_refuse_terminal_wait_admission_before_mutex_release() {
    let mut allocation = Box::<parker::Parker>::new_uninit();
    unsafe { parker::Parker::new_in_place(allocation.as_mut_ptr()); }
    let parker: &'static parker::Parker = Box::leak(unsafe { allocation.assume_init() });
    let pinned = unsafe { pin::Pin::new_unchecked(parker) };
    runtime::index(1); runtime::refuse_wait(true);
    let parked = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        unsafe { pinned.park_timeout(time::Duration::ZERO); }
    }));
    let mutex = mutex::Mutex::new(); let condvar = condvar::Condvar::new(); mutex.lock();
    let conditional = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        unsafe { condvar.wait_timeout(&mutex, time::Duration::ZERO); }
    }));
    runtime::refuse_wait(false);
    assert!(parked.is_err() && conditional.is_err());
    assert!(!mutex.try_lock(), "refusal precedes actual mutex release");
    unsafe { mutex.unlock(); }
    assert_eq!(runtime::immediate_calls(), 0);
    assert_eq!(runtime::live(), 0);
}
