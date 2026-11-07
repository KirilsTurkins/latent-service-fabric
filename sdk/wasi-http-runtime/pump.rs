//! Bounded callback-safe readiness for independently pending Rust HTTP callers.
//!
//! Only the private async driver polls accepted imports. Synchronous WASI calls
//! inspect state and signal work; they neither block a callback nor manufacture
//! completion. The pinned bindgen executor supplies real inter-task wakeups.
use std::{
    cell::{Cell, RefCell},
    future::{poll_fn, Future},
    pin::Pin,
    rc::{Rc, Weak},
    task::{Context, Poll, Waker},
};

const MAX_OPERATIONS: usize = 32;
const MAX_WAITERS: usize = 64;

pub trait Progress {
    fn progress(&self, context: &mut Context<'_>);
    fn pending(&self) -> bool;
}
pub trait Readiness {
    fn ready(&self) -> bool;
}

struct Waiting {
    sources: Vec<Rc<dyn Readiness>>,
    waker: RefCell<Option<Waker>>,
}
impl Waiting {
    fn ready(&self) -> Vec<u32> {
        self.sources
            .iter()
            .enumerate()
            .filter(|(_, source)| source.ready())
            .map(|(index, _)| index as u32)
            .collect()
    }
    fn poll(&self, context: &Context<'_>) -> Poll<Vec<u32>> {
        let ready = self.ready();
        if !ready.is_empty() {
            self.waker.borrow_mut().take();
            return Poll::Ready(ready);
        }
        // All guest execution is cooperative. Register before yielding so a
        // driver completion cannot fall between inspection and subscription.
        self.waker.borrow_mut().replace(context.waker().clone());
        Poll::Pending
    }
}

pub struct Pump {
    operations: RefCell<Vec<Weak<dyn Progress>>>,
    waiters: RefCell<Vec<Weak<Waiting>>>,
    retired: RefCell<Vec<Box<dyn FnOnce()>>>,
    driver_waker: RefCell<Option<Waker>>,
    draining: Cell<bool>,
    #[cfg(target_arch = "wasm32")]
    driver: RefCell<Option<wit_bindgen::JoinHandle<()>>>,
}
thread_local! {
    static CURRENT: Rc<Pump> = Rc::new(Pump::new());
}

impl Pump {
    fn new() -> Self {
        Self {
            operations: RefCell::new(Vec::with_capacity(MAX_OPERATIONS)),
            waiters: RefCell::new(Vec::with_capacity(MAX_WAITERS)),
            retired: RefCell::new(Vec::with_capacity(MAX_OPERATIONS)),
            driver_waker: RefCell::new(None),
            draining: Cell::new(false),
            #[cfg(target_arch = "wasm32")]
            driver: RefCell::new(None),
        }
    }

    pub fn current() -> Rc<Self> {
        CURRENT.with(Rc::clone)
    }

    pub fn track(operation: &Rc<dyn Progress>) {
        let pump = Self::current();
        let mut operations = pump.operations.borrow_mut();
        operations.retain(|owner| owner.strong_count() != 0);
        assert!(
            !pump.draining.get() && operations.len() + pump.retired.borrow().len() < MAX_OPERATIONS,
            "HTTP readiness owner limit"
        );
        operations.push(Rc::downgrade(operation));
        drop(operations);
        pump.step();
    }

    /// Preserve original futures and owners until the explicit async drain.
    /// A synchronous destructor must not perform a blocking canonical cancel.
    pub fn retire(action: impl FnOnce() + 'static) {
        let pump = Self::current();
        let mut retired = pump.retired.borrow_mut();
        assert!(
            retired.len() < MAX_OPERATIONS,
            "canonical retirement owner limit"
        );
        retired.push(Box::new(action));
    }

    /// Only schedule the original driver. In particular, ready/get/read cannot
    /// enter an async host import under an unrelated synchronous WIT task.
    pub fn step(&self) {
        let waker = self.driver_waker.borrow().clone();
        if let Some(waker) = waker {
            waker.wake();
        }
    }

    fn register(&self, sources: &[Rc<dyn Readiness>]) -> Rc<Waiting> {
        assert!(
            !sources.is_empty() && sources.len() <= MAX_WAITERS,
            "WASI poll input limit"
        );
        let mut waiters = self.waiters.borrow_mut();
        waiters.retain(|waiter| waiter.strong_count() != 0);
        assert!(
            !self.draining.get() && waiters.len() < MAX_WAITERS,
            "HTTP waiter limit"
        );
        let waiter = Rc::new(Waiting {
            sources: sources.to_vec(),
            waker: RefCell::new(None),
        });
        waiters.push(Rc::downgrade(&waiter));
        waiter
    }

    pub async fn poll(self: &Rc<Self>, sources: &[Rc<dyn Readiness>]) -> Vec<u32> {
        let waiter = self.register(sources);
        self.start();
        self.step();
        poll_fn(|context| waiter.poll(context)).await
    }

    #[cfg(target_arch = "wasm32")]
    fn start(self: &Rc<Self>) {
        if self.driver.borrow().is_none() {
            // This method is reached only while polling an actual async export.
            // The same pinned bindgen runtime owns this task and its imports.
            let driver = wit_bindgen::spawn_local(Drive(Rc::clone(self)));
            self.driver.borrow_mut().replace(driver);
        }
    }

    #[cfg(not(target_arch = "wasm32"))]
    fn start(self: &Rc<Self>) {
        // Native controls drive Drive directly; they do not emulate a guest.
        panic!("canonical HTTP driver requires wasm32");
    }

    pub async fn drain_retired(self: &Rc<Self>) {
        self.require_no_waiters();
        assert!(!self.draining.replace(true), "duplicate HTTP drain");
        self.start();
        self.step();
        #[cfg(target_arch = "wasm32")]
        {
            let driver = self.driver.borrow_mut().take().expect("HTTP driver owner");
            assert!(driver.await.is_some(), "HTTP driver did not retire");
        }
        self.draining.set(false);
    }

    fn require_no_waiters(&self) {
        assert!(
            self.waiters
                .borrow()
                .iter()
                .all(|waiter| waiter.strong_count() == 0),
            "root still has HTTP readiness waiters"
        );
    }

    fn drive(&self, context: &mut Context<'_>) -> Poll<()> {
        self.driver_waker
            .borrow_mut()
            .replace(context.waker().clone());
        if self.draining.get() {
            self.require_no_waiters();
            // Drop in the SAME driver's async task, before its completion and
            // before refunding any captured continuation owner or quota slot.
            for _ in 0..MAX_OPERATIONS {
                let action = self.retired.borrow_mut().pop();
                let Some(action) = action else { break };
                action();
            }
            assert!(
                self.retired.borrow().is_empty(),
                "recursive HTTP retirement limit"
            );
            assert!(
                self.operations
                    .borrow()
                    .iter()
                    .filter_map(Weak::upgrade)
                    .all(|owner| !owner.pending()),
                "root still has accepted canonical work"
            );
            self.driver_waker.borrow_mut().take();
            return Poll::Ready(());
        }
        // End list borrows before calling code which can retire an operation.
        let owners: Vec<_> = self
            .operations
            .borrow()
            .iter()
            .filter_map(Weak::upgrade)
            .collect();
        for owner in owners {
            owner.progress(context);
        }
        let waiters: Vec<_> = self
            .waiters
            .borrow()
            .iter()
            .filter_map(Weak::upgrade)
            .collect();
        for waiter in waiters {
            if waiter.sources.iter().any(|source| source.ready()) {
                let waker = waiter.waker.borrow_mut().take();
                if let Some(waker) = waker {
                    waker.wake();
                }
            }
        }
        Poll::Pending
    }
}

struct Drive(Rc<Pump>);
impl Future for Drive {
    type Output = ();
    fn poll(self: Pin<&mut Self>, context: &mut Context<'_>) -> Poll<()> {
        self.0.drive(context)
    }
}

#[cfg(test)]
#[path = "pump_tests.rs"]
mod tests;
