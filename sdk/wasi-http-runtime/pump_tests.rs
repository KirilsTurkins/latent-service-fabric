use super::*;
use std::sync::{
    atomic::{AtomicUsize, Ordering},
    Arc,
};
use std::task::Wake;

#[derive(Default)]
struct Signal(AtomicUsize);
impl Wake for Signal {
    fn wake(self: Arc<Self>) {
        self.0.fetch_add(1, Ordering::SeqCst);
    }
}
fn signal() -> (Arc<Signal>, Waker) {
    let count = Arc::new(Signal::default());
    (count.clone(), Waker::from(count))
}
#[derive(Default)]
struct Gate {
    released: Cell<bool>,
    complete: Cell<bool>,
    polls: Cell<usize>,
    driver: RefCell<Option<Waker>>,
}
impl Gate {
    fn release(&self) {
        self.released.set(true);
        if let Some(driver) = self.driver.borrow_mut().take() {
            driver.wake();
        }
    }
}
impl Progress for Gate {
    fn pending(&self) -> bool {
        !self.complete.get()
    }
    fn progress(&self, context: &mut Context<'_>) {
        self.polls.set(self.polls.get() + 1);
        if self.released.get() {
            self.complete.set(true);
        } else {
            self.driver.borrow_mut().replace(context.waker().clone());
        }
    }
}
impl Readiness for Gate {
    fn ready(&self) -> bool {
        self.complete.get()
    }
}
fn operation(pump: &Pump, gate: &Rc<Gate>) {
    let operation: Rc<dyn Progress> = gate.clone();
    pump.operations.borrow_mut().push(Rc::downgrade(&operation));
}
fn waiting(pump: &Pump, gate: &Rc<Gate>) -> Rc<Waiting> {
    pump.register(&[gate.clone()])
}

#[test]
fn completed_sibling_wakes_its_caller_while_original_gate_remains_held() {
    let pump = Rc::new(Pump::new());
    let held = Rc::new(Gate::default());
    let sibling = Rc::new(Gate::default());
    operation(&pump, &held);
    operation(&pump, &sibling);
    let original = waiting(&pump, &held);
    let other = waiting(&pump, &sibling);
    let (held_wakes, held_waker) = signal();
    let (sibling_wakes, sibling_waker) = signal();
    let (driver_wakes, driver_waker) = signal();
    assert!(original
        .poll(&Context::from_waker(&held_waker))
        .is_pending());
    assert!(other
        .poll(&Context::from_waker(&sibling_waker))
        .is_pending());
    let mut driver = std::pin::pin!(Drive(pump.clone()));
    let mut context = Context::from_waker(&driver_waker);
    assert!(driver.as_mut().poll(&mut context).is_pending());
    assert_eq!(driver_wakes.0.load(Ordering::SeqCst), 0);
    sibling.release();
    assert_eq!(driver_wakes.0.load(Ordering::SeqCst), 1);
    assert!(driver.as_mut().poll(&mut context).is_pending());
    assert_eq!(
        other.poll(&Context::from_waker(&sibling_waker)),
        Poll::Ready(vec![0])
    );
    assert!(original
        .poll(&Context::from_waker(&held_waker))
        .is_pending());
    assert!(!held.released.get());
    assert_eq!(held_wakes.0.load(Ordering::SeqCst), 0);
    assert_eq!(sibling_wakes.0.load(Ordering::SeqCst), 1);
    assert!(driver.as_mut().poll(&mut context).is_pending());
    assert_eq!(sibling_wakes.0.load(Ordering::SeqCst), 1);
    held.release();
    assert!(driver.as_mut().poll(&mut context).is_pending());
    assert_eq!(
        original.poll(&Context::from_waker(&held_waker)),
        Poll::Ready(vec![0])
    );
    drop(original);
    drop(other);
    pump.draining.set(true);
    assert!(driver.as_mut().poll(&mut context).is_ready());
    assert!(pump.driver_waker.borrow().is_none());
}

#[test]
fn synchronous_observation_only_schedules_and_cannot_poll_or_complete_an_import() {
    let pump = Pump::new();
    let gate = Rc::new(Gate::default());
    operation(&pump, &gate);
    pump.step();
    assert_eq!(gate.polls.get(), 0);
    let (wakes, waker) = signal();
    pump.driver_waker.borrow_mut().replace(waker);
    gate.released.set(true);
    pump.step();
    assert_eq!(wakes.0.load(Ordering::SeqCst), 1);
    assert_eq!(gate.polls.get(), 0);
    assert!(!gate.ready());
}

#[test]
fn readiness_preserves_input_indices_duplicates_and_replaces_only_the_waiters_waker() {
    let pump = Pump::new();
    let held = Rc::new(Gate::default());
    let ready = Rc::new(Gate::default());
    operation(&pump, &held);
    operation(&pump, &ready);
    let wait = pump.register(&[held.clone(), ready.clone(), ready.clone()]);
    let (old_count, old) = signal();
    let (current_count, current) = signal();
    assert!(wait.poll(&Context::from_waker(&old)).is_pending());
    assert!(wait.poll(&Context::from_waker(&current)).is_pending());
    ready.released.set(true);
    assert!(pump
        .drive(&mut Context::from_waker(Waker::noop()))
        .is_pending());
    assert_eq!(old_count.0.load(Ordering::SeqCst), 0);
    assert_eq!(current_count.0.load(Ordering::SeqCst), 1);
    assert_eq!(
        wait.poll(&Context::from_waker(&current)),
        Poll::Ready(vec![1, 2])
    );
    assert!(!held.ready());
}

#[test]
fn abandoned_waiters_release_sources_and_reuse_bounded_slots_without_stale_wakes() {
    let pump = Pump::new();
    let gate = Rc::new(Gate::default());
    let (wakes, waker) = signal();
    for _ in 0..(2 * MAX_WAITERS) {
        let waiter = waiting(&pump, &gate);
        assert!(waiter.poll(&Context::from_waker(&waker)).is_pending());
        assert_eq!(Rc::strong_count(&gate), 2);
        drop(waiter);
        assert_eq!(Rc::strong_count(&gate), 1);
    }
    gate.complete.set(true);
    assert!(pump
        .drive(&mut Context::from_waker(Waker::noop()))
        .is_pending());
    assert_eq!(wakes.0.load(Ordering::SeqCst), 0);
    let waiters: Vec<_> = (0..MAX_WAITERS).map(|_| waiting(&pump, &gate)).collect();
    assert!(
        std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| waiting(&pump, &gate))).is_err()
    );
    assert_eq!(pump.waiters.borrow().len(), MAX_WAITERS);
    drop(waiters);
    assert_eq!(Rc::strong_count(&gate), 1);
    assert_eq!(waiting(&pump, &gate).ready(), vec![0]);
}

#[test]
fn drain_keeps_retired_owners_until_cleanup_and_refuses_live_work_or_waiters() {
    let pump = Pump::new();
    let retained = Rc::new(Cell::new(false));
    let action = retained.clone();
    pump.retired
        .borrow_mut()
        .push(Box::new(move || action.set(true)));
    assert!(pump
        .drive(&mut Context::from_waker(Waker::noop()))
        .is_pending());
    assert!(!retained.get());
    let gate = Rc::new(Gate::default());
    let waiter = waiting(&pump, &gate);
    pump.draining.set(true);
    assert!(std::panic::catch_unwind(std::panic::AssertUnwindSafe(
        || pump.drive(&mut Context::from_waker(Waker::noop()))
    ))
    .is_err());
    assert!(!retained.get());
    drop(waiter);
    operation(&pump, &gate);
    assert!(std::panic::catch_unwind(std::panic::AssertUnwindSafe(
        || pump.drive(&mut Context::from_waker(Waker::noop()))
    ))
    .is_err());
    assert!(retained.get());
    assert!(!gate.ready());
    drop(gate);
    assert!(pump
        .drive(&mut Context::from_waker(Waker::noop()))
        .is_ready());
}
