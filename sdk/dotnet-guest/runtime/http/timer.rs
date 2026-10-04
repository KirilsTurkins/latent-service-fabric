//! Real activation-owned timer readiness for the pinned CLR event loop.
use super::{latent::runtime::activation as runtime, owner::Owner, pump, quota::Slot};
use std::{
    cell::{Cell, RefCell},
    future::Future,
    pin::Pin,
    rc::Rc,
    task::{Context, Poll},
};

type Work = Pin<Box<dyn Future<Output = Result<(), runtime::Error>>>>;
pub struct Timer {
    work: RefCell<Option<Work>>,
    elapsed: Cell<bool>,
    failure: Cell<Option<runtime::Error>>,
    _owner: Owner,
    _slot: Slot,
}
impl Timer {
    pub fn new(nanos: u64) -> Rc<Self> {
        let slot = Slot::new();
        let owner = Owner::new(runtime::OwnerKind::Wait)
            .expect("activation timer authority or capacity unavailable");
        let timer = Rc::new(Self {
            work: RefCell::new(Some(Box::pin(runtime::wait_for(nanos, None)))),
            elapsed: Cell::new(false),
            failure: Cell::new(None),
            _owner: owner,
            _slot: slot,
        });
        let operation: Rc<dyn pump::Progress> = timer.clone();
        pump::Pump::track(&operation);
        timer
    }
}
impl pump::Progress for Timer {
    fn progress(&self, context: &mut Context<'_>) {
        let Some(mut work) = self.work.borrow_mut().take() else {
            return;
        };
        match work.as_mut().poll(context) {
            Poll::Pending => *self.work.borrow_mut() = Some(work),
            Poll::Ready(Ok(())) => self.elapsed.set(true),
            Poll::Ready(Err(error)) => self.failure.set(Some(error)),
        }
    }
}
impl pump::Readiness for Timer {
    fn ready(&self) -> bool {
        assert!(
            self.failure.get().is_none(),
            "activation timer did not elapse"
        );
        self.elapsed.get()
    }
}
impl Drop for Timer {
    fn drop(&mut self) {
        pump::Pump::current().enter(|| {
            self.work.get_mut().take();
        });
    }
}
