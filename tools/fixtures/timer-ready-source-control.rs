//! Exact production Pump/Timer/Owner source; ledger, clock, ABI and quota are test ports.
use std::{
    cell::{Cell, RefCell},
    collections::BTreeMap,
    future::Future,
    rc::Rc,
    task::{Context, Poll, Waker},
};
pub mod latent {
    pub mod clock { pub mod monotonic { pub fn now_nanos() -> u64 { 0 } } }
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
                    crate::DROP_INPUT_WRAPPERS.with(|values| values.borrow_mut().push(crate::INPUT_WRAPPERS.get()));
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
    pub mod wasi { pub mod io { pub mod poll {
        use std::any::Any;
        pub struct Pollable(Box<dyn Any>);
        impl Pollable {
            pub fn new<T: 'static>(value: T) -> Self { Self(Box::new(value)) }
            pub fn get<T: 'static>(&self) -> &T { self.0.downcast_ref().expect("test pollable type") }
        }
        pub struct PollableBorrow<'a>(&'a Pollable);
        impl Pollable {
            pub fn borrow(&self) -> PollableBorrow<'_> {
                crate::INPUT_WRAPPERS.set(crate::INPUT_WRAPPERS.get() + 1);
                PollableBorrow(self)
            }
        }
        impl PollableBorrow<'_> {
            pub fn get<T: 'static>(&self) -> &T { self.0.get::<T>() }
        }
        impl Drop for PollableBorrow<'_> {
            fn drop(&mut self) { crate::INPUT_WRAPPERS.set(crate::INPUT_WRAPPERS.get() - 1); }
        }
        #[allow(async_fn_in_trait)]
        pub trait GuestPollable { async fn block(&self); }
    } } }
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
#[path = "../../sdk/dotnet-guest/runtime/http/poll.rs"]
pub mod poll;
#[path = "../../sdk/dotnet-guest/runtime/http/timer.rs"]
pub mod timer;
use crate::{
    latent::runtime::activation as runtime,
    pump::{Progress, Readiness},
    quota::SLOTS,
};
use std::ffi::c_void;
thread_local! { static TASK: Cell<*mut c_void> = const { Cell::new(std::ptr::null_mut()) }; }
thread_local! { static SET_CREATIONS: Cell<usize> = const { Cell::new(0) }; }
thread_local! { static TASK_SWITCHES: Cell<usize> = const { Cell::new(0) }; }
// Test port for the Rust wrapper vector only; this is not the component-model borrow.
thread_local! { static INPUT_WRAPPERS: Cell<usize> = const { Cell::new(0) }; }
thread_local! { static DROP_INPUT_WRAPPERS: RefCell<Vec<usize>> = const { RefCell::new(Vec::new()) }; }
thread_local! { static FUTURE_DROP_HOOK: RefCell<Option<Box<dyn FnOnce()>>> = RefCell::new(None); }
thread_local! { static REENTRY_REFUSED: Cell<bool> = const { Cell::new(false) }; }
thread_local! { static REENTRY_WAITS: Cell<usize> = const { Cell::new(0) }; }
#[no_mangle]
pub extern "C" fn wasip3_task_set(task: *mut c_void) -> *mut c_void {
    TASK_SWITCHES.set(TASK_SWITCHES.get() + 1);
    TASK.replace(task)
}
#[export_name = "[waitable-set-new]"]
pub extern "C" fn waitable_set_new_port() -> u32 {
    SET_CREATIONS.set(SET_CREATIONS.get() + 1);
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
    DROP_INPUT_WRAPPERS.with(|values| values.borrow_mut().clear());
    assert_eq!(INPUT_WRAPPERS.get(), 0);
}
fn parent() -> runtime::Token {
    let token = runtime::register(runtime::OwnerKind::Task, None).unwrap();
    owner::set_continuation(Some(token));
    token
}
fn poll(timer: &timer::Timer) {
    timer.progress(&mut Context::from_waker(Waker::noop()));
}
// The WIT resource, clock, owner ledger, canonical ABI and quotas remain test
// ports; these execute the actual production poll, Pump and Timer sources.
#[test]
fn ready_poll_without_a_retired_timer_does_not_create_a_pump() {
    std::thread::spawn(|| {
        reset();
        let closed = poll::Pollable::closed();
        assert_eq!(poll::Pollable::poll(vec![closed.borrow()]), vec![0]);
        {
            let mut block = std::pin::pin!(<poll::Pollable as exports::wasi::io::poll::GuestPollable>::block(
                closed.get::<poll::Pollable>()));
            assert!(matches!(block.as_mut().poll(&mut Context::from_waker(Waker::noop())), Poll::Ready(())));
        }
        assert_eq!(SET_CREATIONS.get(), 0);
        assert!(TASK.get().is_null());
        drop(closed);
        assert_eq!(SLOTS.get(), 0);
        assert!(runtime::empty());
    }).join().unwrap();
}

#[test]
fn ready_poll_retires_the_original_unpolled_timer() {
    reset();
    let parent = parent();
    drop(timer::Timer::new(1));
    let closed = poll::Pollable::closed();
    assert_eq!(runtime::count(runtime::OwnerKind::Wait), 1);
    assert_eq!(poll::Pollable::poll(vec![closed.borrow()]), vec![0]);
    let observed = (runtime::count(runtime::OwnerKind::Wait), SLOTS.get(),
        runtime::WAIT_SETTLES.get(), runtime::WAIT_SETTLES_OUTSIDE_TASK.get(), runtime::WAIT_POLLS.get());
    let drops = runtime::DROP_OBSERVATIONS.with(|v| v.borrow().clone());
    let wrappers = DROP_INPUT_WRAPPERS.with(|v| v.borrow().clone());
    drop(closed);
    pump::Pump::current().drain_retired();
    runtime::settle(parent).unwrap();
    assert_eq!(observed, (0, 1, 1, 0, 0));
    assert_eq!(drops, vec![(1, 0, 2)]);
    assert_eq!(wrappers, vec![0]);
    assert!(runtime::empty());
}

#[test]
fn ready_block_retires_the_original_unpolled_timer() {
    reset();
    let parent = parent();
    drop(timer::Timer::new(1));
    let closed = poll::Pollable::closed();
    {
        let mut block = std::pin::pin!(<poll::Pollable as exports::wasi::io::poll::GuestPollable>::block(
            closed.get::<poll::Pollable>()));
        assert!(matches!(block.as_mut().poll(&mut Context::from_waker(Waker::noop())), Poll::Ready(())));
    }
    let observed = (runtime::count(runtime::OwnerKind::Wait), SLOTS.get(),
        runtime::WAIT_SETTLES.get(), runtime::WAIT_SETTLES_OUTSIDE_TASK.get());
    drop(closed);
    pump::Pump::current().drain_retired();
    runtime::settle(parent).unwrap();
    assert_eq!(observed, (0, 1, 1, 0));
    assert!(runtime::empty());
}

#[test]
fn ready_poll_leaves_the_started_wait_for_the_original_drain() {
    reset();
    let parent = parent();
    runtime::PENDING.set(true);
    let started = timer::Timer::new(1); poll(&started); drop(started);
    drop(timer::Timer::new(1));
    let closed = poll::Pollable::closed();
    assert_eq!(poll::Pollable::poll(vec![closed.borrow()]), vec![0]);
    let observed = (runtime::count(runtime::OwnerKind::Wait), runtime::count(runtime::OwnerKind::Timer),
        SLOTS.get(), runtime::WAIT_SETTLES.get(), runtime::WAIT_SETTLES_OUTSIDE_TASK.get());
    drop(closed);
    pump::Pump::current().drain_retired();
    runtime::settle(parent).unwrap();
    assert_eq!(observed, (1, 1, 2, 1, 0));
    assert!(runtime::empty());
    assert_eq!(SLOTS.get(), 0);
}

#[test]
fn ready_poll_reentry_keeps_the_in_flight_original_owner() {
    reset();
    let parent = parent();
    drop(timer::Timer::new(1));
    let closed = Rc::new(poll::Pollable::closed());
    let nested = closed.clone();
    FUTURE_DROP_HOOK.with(|hook| *hook.borrow_mut() = Some(Box::new(move || {
        assert_eq!(poll::Pollable::poll(vec![nested.borrow()]), vec![0]);
        REENTRY_WAITS.set(runtime::count(runtime::OwnerKind::Wait));
    })));
    assert_eq!(poll::Pollable::poll(vec![closed.borrow()]), vec![0]);
    let observed = (runtime::count(runtime::OwnerKind::Wait), runtime::WAIT_SETTLES.get(),
        runtime::WAIT_SETTLES_OUTSIDE_TASK.get());
    let nested_waits = REENTRY_WAITS.get();
    drop(closed);
    pump::Pump::current().drain_retired();
    runtime::settle(parent).unwrap();
    assert_eq!(observed, (0, 1, 0));
    assert_eq!(nested_waits, 1);
    assert!(runtime::empty());
}

#[test]
fn ready_poll_keeps_the_input_timer_alias_live_while_reaping_another() {
    reset();
    let parent = parent();
    let timer = timer::Timer::new(1);
    let identity = Rc::as_ptr(&timer);
    let weak = Rc::downgrade(&timer);
    let first: Rc<dyn Readiness> = timer.clone();
    let second: Rc<dyn Readiness> = timer.clone();
    let first = poll::Pollable::new(first);
    let second = poll::Pollable::new(second);
    drop(timer);
    drop(first); // The second pollable still owns this exact Timer.
    drop(timer::Timer::new(2)); // Only this independent Timer is retired.
    let closed = poll::Pollable::closed();
    assert_eq!(poll::Pollable::poll(vec![closed.borrow(), second.borrow()]), vec![0]);
    let retained = weak.upgrade().expect("input alias must retain the original timer");
    let same_identity = Rc::as_ptr(&retained) == identity;
    let was_ready = retained.ready();
    let observed = (runtime::count(runtime::OwnerKind::Wait), SLOTS.get(),
        runtime::WAIT_SETTLES.get(), runtime::WAIT_POLLS.get(), INPUT_WRAPPERS.get());
    let wrappers = DROP_INPUT_WRAPPERS.with(|v| v.borrow().clone());
    drop(retained);
    drop(second); // The last owner now transfers its unpolled Wait to the Pump.
    assert_eq!(poll::Pollable::poll(vec![closed.borrow()]), vec![0]);
    let after_last_alias = runtime::count(runtime::OwnerKind::Wait);
    drop(closed);
    pump::Pump::current().drain_retired();
    runtime::settle(parent).unwrap();
    assert!(same_identity && !was_ready);
    assert_eq!(observed, (1, 3, 1, 0, 0));
    assert_eq!(wrappers, vec![0]);
    assert_eq!(after_last_alias, 0);
    assert!(runtime::empty());
    assert_eq!(SLOTS.get(), 0);
}

#[test]
fn repeated_ready_polls_after_reap_create_no_canonical_work() {
    reset();
    let parent = parent();
    drop(timer::Timer::new(1));
    let closed = poll::Pollable::closed();
    assert_eq!(poll::Pollable::poll(vec![closed.borrow()]), vec![0]);
    let before = (SET_CREATIONS.get(), TASK_SWITCHES.get(), runtime::WAIT_SETTLES.get(),
        runtime::WAIT_POLLS.get(), runtime::count(runtime::OwnerKind::Wait), SLOTS.get());
    for _ in 0..128 {
        assert_eq!(poll::Pollable::poll(vec![closed.borrow()]), vec![0]);
    }
    let after = (SET_CREATIONS.get(), TASK_SWITCHES.get(), runtime::WAIT_SETTLES.get(),
        runtime::WAIT_POLLS.get(), runtime::count(runtime::OwnerKind::Wait), SLOTS.get());
    drop(closed);
    pump::Pump::current().drain_retired();
    runtime::settle(parent).unwrap();
    assert_eq!(before, (1, 2, 1, 0, 0, 1));
    assert_eq!(after, before);
    assert!(runtime::empty());
}

#[test]
fn ready_poll_rechecks_readiness_after_reentrant_retirement() {
    reset();
    let parent = parent();
    drop(timer::Timer::new(1));
    let changing = Rc::new(Latch(Cell::new(true)));
    let source: Rc<dyn Readiness> = changing.clone();
    let input = poll::Pollable::new(source);
    let closed = poll::Pollable::closed();
    let nested = changing.clone();
    FUTURE_DROP_HOOK.with(|hook| *hook.borrow_mut() = Some(Box::new(move || nested.0.set(false))));
    let result = poll::Pollable::poll(vec![closed.borrow(), input.borrow()]);
    let was_ready = changing.ready();
    drop(input); drop(closed);
    pump::Pump::current().drain_retired();
    runtime::settle(parent).unwrap();
    assert_eq!(result, vec![0]);
    assert!(!was_ready);
    assert!(runtime::empty());
}

#[test]
fn interrupted_ready_reap_does_not_retry_and_fences_final_drain() {
    reset();
    let parent = parent();
    drop(timer::Timer::new(1));
    let closed = poll::Pollable::closed();
    // Preserve the deliberately poisoned test-port Pump through TLS teardown;
    // production instead traps and retains the original Store authority.
    std::mem::forget(pump::Pump::current());
    FUTURE_DROP_HOOK.with(|hook| *hook.borrow_mut() = Some(Box::new(|| panic!("simulated ready retirement interruption"))));
    let failure = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        poll::Pollable::poll(vec![closed.borrow()]);
    }));
    let attempts = runtime::WAIT_SETTLES.get();
    let no_wrapper = INPUT_WRAPPERS.get();
    assert_eq!(poll::Pollable::poll(vec![closed.borrow()]), vec![0]);
    let drain = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        pump::Pump::current().drain_retired();
    }));
    let after = runtime::WAIT_SETTLES.get();
    drop(closed);
    runtime::settle(parent).unwrap();
    assert!(failure.is_err() && drain.is_err());
    assert_eq!(no_wrapper, 0);
    assert_eq!(after, attempts);
    assert!(TASK.get().is_null());
}
