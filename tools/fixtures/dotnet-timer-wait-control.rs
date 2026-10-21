//! Exact production Rust Timer/Owner source; ledger/clock/pump/quota are test ports.
use std::{
    cell::{Cell, RefCell},
    collections::BTreeMap,
    future::Future,
    pin::pin,
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
                Wait,
                Timer,
            }
            #[derive(Clone, Copy, Debug, PartialEq, Eq)]
            pub enum Error {
                InvalidToken,
                InvalidState,
            }
            thread_local! {
                pub static OWNERS:RefCell<BTreeMap<u64,OwnerKind>>=RefCell::new(BTreeMap::new());
                static SEQUENCE:Cell<u64>=const{Cell::new(0)};
                pub static CLOSING:Cell<bool>=const{Cell::new(false)};
                pub static WAIT_POLLS:Cell<usize>=const{Cell::new(0)};
            }
            pub fn register(kind: OwnerKind, parent: Option<Token>) -> Result<Token, Error> {
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
                if token.generation != 9
                    || !OWNERS.with(|owners| owners.borrow_mut().remove(&token.id).is_some())
                {
                    return Err(Error::InvalidToken);
                }
                Ok(())
            }
            pub async fn wait_for(_nanos: u64, parent: Option<Token>) -> Result<(), Error> {
                WAIT_POLLS.set(WAIT_POLLS.get() + 1);
                let token = register(OwnerKind::Timer, parent)?;
                settle(token)?;
                Ok(())
            }
            pub fn reset() {
                OWNERS.with(|owners| owners.borrow_mut().clear());
                SEQUENCE.set(0);
                CLOSING.set(false);
                WAIT_POLLS.set(0);
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
pub mod pump {
    use crate::*;
    pub trait Progress {
        fn progress(&self, context: &mut Context<'_>);
    }
    pub trait Readiness {
        fn ready(&self) -> bool;
    }
    pub struct Pump;
    impl Pump {
        pub fn track(_: &Rc<dyn Progress>) {}
        pub fn retire(f: impl FnOnce() + 'static) {
            f()
        }
    }
}
#[path = "../../sdk/dotnet-guest/runtime/http/owner.rs"]
pub mod owner;
#[path = "../../sdk/dotnet-guest/runtime/http/timer.rs"]
pub mod timer;
use crate::{
    latent::runtime::activation as runtime,
    pump::{Progress, Readiness},
    quota::SLOTS,
};
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
#[test]
fn delayed_wait_outlives_its_creator_task() {
    reset();
    let parent = parent();
    let timer = timer::Timer::new(1);
    assert_eq!(runtime::WAIT_POLLS.get(), 0);
    assert_eq!(runtime::count(runtime::OwnerKind::Wait), 1);
    runtime::settle(parent).unwrap();
    assert_eq!(runtime::count(runtime::OwnerKind::Task), 0);
    poll(&timer);
    assert!(timer.ready());
    drop(timer);
    assert!(runtime::empty());
    assert_eq!(SLOTS.get(), 0);
}
#[test]
fn accepted_wait_can_start_after_closing_and_parent_return() {
    reset();
    let parent = parent();
    let timer = timer::Timer::new(1);
    runtime::settle(parent).unwrap();
    runtime::CLOSING.set(true);
    poll(&timer);
    assert!(timer.ready());
    drop(timer);
    assert!(runtime::empty());
    assert_eq!(SLOTS.get(), 0);
}
#[test]
fn later_ambient_task_cannot_reparent_an_already_owned_wait() {
    reset();
    let parent = parent();
    let timer = timer::Timer::new(1);
    runtime::settle(parent).unwrap();
    let foreign = runtime::register(runtime::OwnerKind::Task, None).unwrap();
    owner::set_continuation(Some(foreign));
    poll(&timer);
    assert!(timer.ready());
    drop(timer);
    assert_eq!(runtime::count(runtime::OwnerKind::Task), 1);
    runtime::settle(foreign).unwrap();
    assert!(runtime::empty());
    assert_eq!(SLOTS.get(), 0);
}
#[test]
fn dropping_before_first_poll_releases_the_original_wait() {
    reset();
    let parent = parent();
    let timer = timer::Timer::new(1);
    runtime::settle(parent).unwrap();
    drop(timer);
    assert_eq!(runtime::WAIT_POLLS.get(), 0);
    assert!(runtime::empty());
    assert_eq!(SLOTS.get(), 0);
}
#[test]
fn invalid_constructor_parent_is_still_refused_without_leak() {
    reset();
    owner::set_continuation(Some(runtime::Token {
        generation: 8,
        id: 1,
    }));
    assert!(std::panic::catch_unwind(|| timer::Timer::new(1)).is_err());
    assert!(runtime::empty());
    assert_eq!(SLOTS.get(), 0);
}
#[test]
fn invalid_explicit_wait_token_is_never_ambiently_replaced() {
    reset();
    let parent = parent();
    let mut future = pin!(runtime::wait_for(
        1,
        Some(runtime::Token {
            generation: 8,
            id: parent.id
        })
    ));
    assert_eq!(
        future
            .as_mut()
            .poll(&mut Context::from_waker(Waker::noop())),
        Poll::Ready(Err(runtime::Error::InvalidToken))
    );
    runtime::settle(parent).unwrap();
    assert!(runtime::empty());
    assert_eq!(SLOTS.get(), 0);
}
