//! Exact production Pump/Timer/Owner source; ledger, clock, ABI and quota are test ports.
use std::{
    cell::{Cell, RefCell},
    collections::BTreeMap,
    future::Future,
    rc::Rc,
    task::{Context, Poll, Waker},
};
pub mod latent {
    pub mod runtime {
        pub mod activation {
            use crate::*;
            #[derive(Clone, Copy, Debug, PartialEq, Eq)]
            pub struct Token {
                pub generation: u64,
                pub id: u64,
            }
            #[derive(Clone, Copy, Debug, PartialEq, Eq)]
            pub enum OwnerKind {
                Task,
                ManagedIdleWorker,
                Executor,
                QueuedWork,
                Wait,
                Timer,
                Result,
                Native,
            }
            #[derive(Clone, Copy, Debug, PartialEq, Eq)]
            pub enum Error {
                Unavailable,
                PermissionDenied,
                ResourceExhausted,
                Cancelled,
                Deadline,
                InvalidToken,
                InvalidState,
            }
            thread_local! {
                pub static OWNERS:RefCell<BTreeMap<u64,OwnerKind>>=RefCell::new(BTreeMap::new());
                static SEQUENCE:Cell<u64>=const{Cell::new(0)};
                pub static CLOSING:Cell<bool>=const{Cell::new(false)};
                pub static WAIT_POLLS:Cell<usize>=const{Cell::new(0)};
                pub static REGISTER_CALLS:Cell<usize>=const{Cell::new(0)};
                pub static WAIT_SETTLES:Cell<usize>=const{Cell::new(0)};
                pub static WAIT_SETTLES_OUTSIDE_TASK:Cell<usize>=const{Cell::new(0)};
                pub static FAIL_WAIT_SETTLE:Cell<bool>=const{Cell::new(false)};
            }
            pub fn register(kind: OwnerKind, parent: Option<Token>) -> Result<Token, Error> {
                REGISTER_CALLS.set(REGISTER_CALLS.get() + 1);
                if let Some(parent) = parent {
                    if parent.generation != 9
                        || !OWNERS.with(|owners| owners.borrow().contains_key(&parent.id))
                    {
                        return Err(Error::InvalidToken);
                    }
                } else if CLOSING.get() {
                    return Err(Error::InvalidState);
                }
                let id = SEQUENCE.get() + 1;
                SEQUENCE.set(id);
                OWNERS.with(|owners| {
                    owners.borrow_mut().insert(id, kind);
                });
                Ok(Token { generation: 9, id })
            }
            pub fn settle(token: Token) -> Result<(), Error> {
                let wait = OWNERS.with(|owners| owners.borrow().get(&token.id).copied())
                    == Some(OwnerKind::Wait);
                if wait {
                    WAIT_SETTLES.set(WAIT_SETTLES.get() + 1);
                    if crate::TASK.get().is_null() {
                        WAIT_SETTLES_OUTSIDE_TASK.set(WAIT_SETTLES_OUTSIDE_TASK.get() + 1);
                    }
                    if FAIL_WAIT_SETTLE.get() {
                        return Err(Error::Cancelled);
                    }
                }
                if token.generation != 9
                    || !OWNERS.with(|owners| owners.borrow_mut().remove(&token.id).is_some())
                {
                    return Err(Error::InvalidToken);
                }
                Ok(())
            }
            pub fn close() -> Result<(), Error> {
                CLOSING.set(true);
                Ok(())
            }
            // A test-only wrapper records the state at physical future drop.
            // The selected generated production binding itself is an async fn.
            pub struct WaitProbe(std::pin::Pin<Box<dyn Future<Output = Result<(), Error>>>>);
            impl Future for WaitProbe {
                type Output = Result<(), Error>;
                fn poll(
                    mut self: std::pin::Pin<&mut Self>,
                    cx: &mut Context<'_>,
                ) -> Poll<Self::Output> {
                    self.0.as_mut().poll(cx)
                }
            }
            impl Drop for WaitProbe {
                fn drop(&mut self) {
                    DROP_OBSERVATIONS.with(|events| {
                        events.borrow_mut().push((
                            count(OwnerKind::Wait),
                            count(OwnerKind::Timer),
                            crate::quota::SLOTS.get(),
                        ))
                    });
                    let hook = crate::FUTURE_DROP_HOOK.with(|hook| hook.borrow_mut().take());
                    if let Some(hook) = hook {
                        hook();
                    }
                }
            }
            pub fn wait_for(nanos: u64, parent: Option<Token>) -> WaitProbe {
                WaitProbe(Box::pin(wait_for_inner(nanos, parent)))
            }
            async fn wait_for_inner(_nanos: u64, parent: Option<Token>) -> Result<(), Error> {
                WAIT_POLLS.set(WAIT_POLLS.get() + 1);
                let token = register(OwnerKind::Timer, parent)?;
                let guard = WaitGuard(token);
                if PENDING.get() {
                    std::future::pending::<()>().await;
                }
                drop(guard);
                Ok(())
            }
            thread_local! { pub static PENDING: Cell<bool> = const { Cell::new(false) }; }
            thread_local! { pub static DROP_OBSERVATIONS: RefCell<Vec<(usize, usize, usize)>> = const { RefCell::new(Vec::new()) }; }
            struct WaitGuard(Token);
            impl Drop for WaitGuard {
                fn drop(&mut self) {
                    settle(self.0).unwrap();
                }
            }
            pub fn reset() {
                PENDING.set(false);
                DROP_OBSERVATIONS.with(|events| events.borrow_mut().clear());
                OWNERS.with(|owners| owners.borrow_mut().clear());
                SEQUENCE.set(0);
                CLOSING.set(false);
                WAIT_POLLS.set(0);
                REGISTER_CALLS.set(0);
                WAIT_SETTLES.set(0);
                WAIT_SETTLES_OUTSIDE_TASK.set(0);
                FAIL_WAIT_SETTLE.set(false);
            }
            pub fn count(kind: OwnerKind) -> usize {
                OWNERS.with(|owners| {
                    owners
                        .borrow()
                        .values()
                        .filter(|value| **value == kind)
                        .count()
                })
            }
            pub fn empty() -> bool {
                OWNERS.with(|owners| owners.borrow().is_empty())
            }
        }
    }
}
pub struct ClosedRuntime;
pub mod exports {
    pub mod latent {
        pub mod dotnet_managed_work {
            pub mod owner {
                pub trait Guest {
                    fn reserve(kind: u32, generation: u64, id: u64) -> Result<(u64, u64), u32>;
                    fn settle(generation: u64, id: u64) -> Result<(), u32>;
                    fn close() -> Result<(), u32>;
                    fn context(generation: u64, id: u64);
                }
            }
        }
    }
}
pub mod quota {
    use crate::*;
    thread_local! {pub static SLOTS:Cell<usize>=const{Cell::new(0)};}
    pub struct Slot;
    impl Slot {
        pub fn new() -> Self {
            SLOTS.set(SLOTS.get() + 1);
            Self
        }
    }
    impl Drop for Slot {
        fn drop(&mut self) {
            SLOTS.set(SLOTS.get() - 1);
        }
    }
}

#[path = "../../sdk/dotnet-guest/runtime/http/owner.rs"]
pub mod owner;
#[path = "../../sdk/dotnet-guest/runtime/http/pump.rs"]
pub mod pump;
#[path = "../../sdk/dotnet-guest/runtime/http/timer.rs"]
pub mod timer;
use crate::{
    latent::runtime::activation as runtime,
    pump::{Progress, Readiness},
    quota::SLOTS,
};
use std::ffi::c_void;
thread_local! { static TASK: Cell<*mut c_void> = const { Cell::new(std::ptr::null_mut()) }; }
thread_local! { static FUTURE_DROP_HOOK: RefCell<Option<Box<dyn FnOnce()>>> = RefCell::new(None); }
thread_local! { static REENTRY_REFUSED: Cell<bool> = const { Cell::new(false) }; }
thread_local! { static REENTRY_WAITS: Cell<usize> = const { Cell::new(0) }; }
#[no_mangle]
pub extern "C" fn wasip3_task_set(task: *mut c_void) -> *mut c_void {
    TASK.replace(task)
}
#[export_name = "[waitable-set-new]"]
pub extern "C" fn waitable_set_new_port() -> u32 {
    1
}
#[export_name = "[waitable-set-drop]"]
pub extern "C" fn waitable_set_drop_port(_: u32) {}
#[export_name = "[waitable-join]"]
pub extern "C" fn waitable_join_port(_: u32, _: u32) {}
#[export_name = "[waitable-set-wait]"]
pub extern "C" fn waitable_set_wait_port(_: u32, _: *mut [u32; 2]) -> u32 {
    0
}
#[export_name = "[waitable-set-poll]"]
pub extern "C" fn waitable_set_poll_port(_: u32, _: *mut [u32; 2]) -> u32 {
    0
}
struct Latch(Cell<bool>);
impl Progress for Latch {
    fn progress(&self, _: &mut Context<'_>) {
        self.0.set(true);
    }
}
impl Readiness for Latch {
    fn ready(&self) -> bool {
        self.0.get()
    }
}
fn reset() {
    runtime::reset();
    assert_eq!(SLOTS.get(), 0);
    owner::set_continuation(None);
}
fn parent() -> runtime::Token {
    let token = runtime::register(runtime::OwnerKind::Task, None).unwrap();
    owner::set_continuation(Some(token));
    token
}
fn poll(timer: &timer::Timer) {
    timer.progress(&mut Context::from_waker(Waker::noop()));
}
fn latch() -> Rc<Latch> {
    let value = Rc::new(Latch(Cell::new(false)));
    let tracked: Rc<dyn Progress> = value.clone();
    pump::Pump::track(&tracked);
    value
}
fn async_poll(value: &Rc<Latch>) {
    value.0.set(false);
    let readiness: Rc<dyn Readiness> = value.clone();
    assert_eq!(pump::Pump::current().poll(&[readiness]), vec![0]);
}
#[test]
fn async_poll_retires_only_never_polled_timers() {
    reset();
    let parent = parent();
    let ready = latch();
    let ordinary = Rc::new(Cell::new(false));
    let ordinary_action = ordinary.clone();
    pump::Pump::retire(move || ordinary_action.set(true));
    let timer = timer::Timer::new(1);
    drop(timer);
    assert_eq!(runtime::WAIT_POLLS.get(), 0);
    assert_eq!(runtime::count(runtime::OwnerKind::Wait), 1);
    assert_eq!(SLOTS.get(), 1);
    assert_eq!(runtime::WAIT_SETTLES.get(), 0);
    async_poll(&ready);
    let observed = (runtime::count(runtime::OwnerKind::Wait), SLOTS.get());
    let ordinary_before_drain = ordinary.get();
    let settles_before_drain = runtime::WAIT_SETTLES.get();
    let outside_before_drain = runtime::WAIT_SETTLES_OUTSIDE_TASK.get();
    pump::Pump::current().drain_retired();
    runtime::settle(parent).unwrap();
    assert!(ordinary.get());
    assert_eq!(observed, (0, 0));
    assert!(!ordinary_before_drain);
    assert_eq!(settles_before_drain, 1);
    assert_eq!(outside_before_drain, 0);
}
#[test]
fn async_poll_does_not_retire_a_polled_pending_wait() {
    reset();
    let parent = parent();
    let ready = latch();
    runtime::PENDING.set(true);
    let timer = timer::Timer::new(1);
    poll(&timer);
    drop(timer);
    async_poll(&ready);
    assert_eq!(runtime::count(runtime::OwnerKind::Wait), 1);
    assert_eq!(runtime::count(runtime::OwnerKind::Timer), 1);
    assert_eq!(SLOTS.get(), 1);
    assert_eq!(runtime::WAIT_SETTLES.get(), 0);
    pump::Pump::current().drain_retired();
    assert_eq!(runtime::count(runtime::OwnerKind::Wait), 0);
    assert_eq!(runtime::count(runtime::OwnerKind::Timer), 0);
    assert_eq!(SLOTS.get(), 0);
    assert_eq!(runtime::WAIT_SETTLES.get(), 1);
    assert_eq!(runtime::WAIT_SETTLES_OUTSIDE_TASK.get(), 0);
    runtime::settle(parent).unwrap();
}

#[test]
fn repeated_async_polls_reuse_the_existing_capacity() {
    reset();
    let parent = parent();
    let ready = latch();
    for _ in 0..40 {
        drop(timer::Timer::new(1));
        async_poll(&ready);
        assert_eq!(runtime::count(runtime::OwnerKind::Wait), 0);
        assert_eq!(SLOTS.get(), 0);
    }
    assert_eq!(runtime::WAIT_POLLS.get(), 0);
    assert_eq!(runtime::WAIT_SETTLES.get(), 40);
    assert_eq!(runtime::WAIT_SETTLES_OUTSIDE_TASK.get(), 0);
    pump::Pump::current().drain_retired();
    runtime::settle(parent).unwrap();
}

#[test]
fn in_flight_owner_counts_during_reentry_and_nested_poll() {
    reset();
    let parent = parent();
    let ready = latch();
    for _ in 0..31 {
        drop(timer::Timer::new(1));
    }
    assert_eq!(runtime::count(runtime::OwnerKind::Wait), 31);
    let nested = ready.clone();
    FUTURE_DROP_HOOK.with(|hook| {
        *hook.borrow_mut() = Some(Box::new(move || {
            let item: Rc<dyn Progress> = Rc::new(Latch(Cell::new(false)));
            let refused = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                pump::Pump::track(&item);
            }))
            .is_err();
            REENTRY_REFUSED.set(refused);
            async_poll(&nested);
            REENTRY_WAITS.set(runtime::count(runtime::OwnerKind::Wait));
        }))
    });
    async_poll(&ready);
    assert!(REENTRY_REFUSED.get());
    assert_eq!(REENTRY_WAITS.get(), 31);
    assert_eq!(runtime::count(runtime::OwnerKind::Wait), 0);
    assert_eq!(runtime::WAIT_SETTLES.get(), 31);
    assert_eq!(runtime::WAIT_SETTLES_OUTSIDE_TASK.get(), 0);
    pump::Pump::current().drain_retired();
    runtime::settle(parent).unwrap();
}

#[test]
fn failed_host_settlement_is_not_retried_or_a_successful_host_retirement() {
    reset();
    let parent = parent();
    let ready = latch();
    drop(timer::Timer::new(1));
    runtime::FAIL_WAIT_SETTLE.set(true);
    async_poll(&ready);
    assert_eq!(runtime::WAIT_SETTLES.get(), 1);
    assert_eq!(runtime::WAIT_SETTLES_OUTSIDE_TASK.get(), 0);
    assert_eq!(runtime::count(runtime::OwnerKind::Wait), 1);
    assert_eq!(SLOTS.get(), 0);
    pump::Pump::current().drain_retired();
    assert_eq!(runtime::WAIT_SETTLES.get(), 1);
    assert!(!runtime::empty()); // The mock host still owns the refused token.
    runtime::settle(parent).unwrap();
    runtime::reset(); // Test-port cleanup; no production settlement retry.
}

#[test]
fn interrupted_retirement_fences_final_drain_without_retry() {
    reset();
    let parent = parent();
    let ready = latch();
    drop(timer::Timer::new(1));
    // Keep the poisoned test-port pump alive through thread-local teardown.
    // The production activation instead fails and its Store remains the owner.
    std::mem::forget(pump::Pump::current());
    FUTURE_DROP_HOOK.with(|hook| {
        *hook.borrow_mut() = Some(Box::new(|| panic!("simulated retirement interruption")))
    });
    let interrupted = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| async_poll(&ready)));
    assert!(interrupted.is_err());
    assert!(TASK.get().is_null());
    let attempts = runtime::WAIT_SETTLES.get();
    let final_drain = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        pump::Pump::current().drain_retired();
    }));
    assert!(final_drain.is_err());
    assert_eq!(runtime::WAIT_SETTLES.get(), attempts);
    runtime::settle(parent).unwrap();
}

#[test]
fn failed_reentrant_timer_admission_retains_provisional_wait() {
    reset();
    let parent = parent();
    let ready = latch();
    let held = timer::Timer::new(1);
    for _ in 0..30 {
        drop(timer::Timer::new(1));
    }
    assert_eq!(runtime::count(runtime::OwnerKind::Wait), 31);
    let nested = ready.clone();
    FUTURE_DROP_HOOK.with(|hook| {
        *hook.borrow_mut() = Some(Box::new(move || {
            let refused = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                drop(timer::Timer::new(1));
            }))
            .is_err();
            REENTRY_REFUSED.set(refused);
            async_poll(&nested);
            REENTRY_WAITS.set(runtime::count(runtime::OwnerKind::Wait));
        }))
    });
    async_poll(&ready);
    assert!(REENTRY_REFUSED.get());
    assert_eq!(REENTRY_WAITS.get(), 32);
    assert_eq!(runtime::count(runtime::OwnerKind::Wait), 1);
    assert_eq!(SLOTS.get(), 1);
    assert_eq!(runtime::WAIT_SETTLES.get(), 31);
    assert_eq!(runtime::WAIT_SETTLES_OUTSIDE_TASK.get(), 0);
    drop(held);
    async_poll(&ready);
    assert_eq!(runtime::count(runtime::OwnerKind::Wait), 0);
    assert_eq!(SLOTS.get(), 0);
    assert_eq!(runtime::WAIT_SETTLES.get(), 32);
    pump::Pump::current().drain_retired();
    runtime::settle(parent).unwrap();
}
