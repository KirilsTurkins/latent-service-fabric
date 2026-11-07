use super::*;
use crate::{
    BudgetCancellationProbe, BudgetProfile, ClockSample, DelegationLimits,
    EffectiveActivationBudget,
};
use std::{
    panic::{catch_unwind, AssertUnwindSafe},
    sync::{
        atomic::{AtomicBool, AtomicUsize, Ordering},
        Arc, Mutex,
    },
    task::Waker,
};

#[derive(Default)]
struct State {
    ready: AtomicBool,
    builds: AtomicUsize,
    drops: AtomicUsize,
    builder_panics: AtomicBool,
    drop_panics: AtomicBool,
    waiter: Mutex<Option<Waker>>,
}

struct Probe(Arc<State>);

struct SignalFuture {
    state: Arc<State>,
    budget: ActivationBudget,
}

impl Future for SignalFuture {
    type Output = ();

    fn poll(self: Pin<&mut Self>, context: &mut Context<'_>) -> Poll<()> {
        if self.state.ready.load(Ordering::Acquire) {
            Poll::Ready(())
        } else {
            *self.state.waiter.lock().unwrap() = Some(context.waker().clone());
            Poll::Pending
        }
    }
}

impl Drop for SignalFuture {
    fn drop(&mut self) {
        assert!(self.budget.host_memory_bytes() >= future_bytes());
        self.state.drops.fetch_add(1, Ordering::SeqCst);
        assert!(
            !self.state.drop_panics.load(Ordering::Acquire),
            "signal drop"
        );
    }
}

impl BudgetCancellationProbe for Probe {
    fn is_cancelled(&self) -> bool {
        self.0.ready.load(Ordering::Acquire)
    }

    fn cancelled(&self) -> BoxFuture<'_, ()> {
        Box::pin(std::future::pending())
    }

    fn cancelled_owned(
        self: Arc<Self>,
        budget: &ActivationBudget,
    ) -> Result<OwnedCancellationFuture, PlatformError> {
        let observed_budget = budget.clone();
        OwnedCancellationFuture::new(budget, move || {
            self.0.builds.fetch_add(1, Ordering::SeqCst);
            assert!(
                !self.0.builder_panics.load(Ordering::Acquire),
                "signal builder"
            );
            SignalFuture {
                state: self.0.clone(),
                budget: observed_budget,
            }
        })
    }

    fn mark_terminal(&self) {
        self.0.ready.store(true, Ordering::Release);
        if let Some(waker) = self.0.waiter.lock().unwrap().take() {
            waker.wake();
        }
    }
}

fn storage_bytes() -> u64 {
    charge(size_of::<Signals>()).unwrap()
}

fn future_bytes() -> u64 {
    charge(size_of::<SignalFuture>()).unwrap()
}

fn root(bytes: u64, state: Arc<State>) -> (ActivationBudget, ClockSample) {
    root_with_probe(bytes, Arc::new(Probe(state)))
}

fn root_with_probe(
    bytes: u64,
    probe: Arc<dyn BudgetCancellationProbe>,
) -> (ActivationBudget, ClockSample) {
    root_with_limits(bytes, probe, DelegationLimits::default())
}

fn root_with_limits(
    bytes: u64,
    probe: Arc<dyn BudgetCancellationProbe>,
    limits: DelegationLimits,
) -> (ActivationBudget, ClockSample) {
    let sample = ClockSample::new(1000, Instant::now());
    let mut requested = super::super::tests::request(1000, bytes, 32);
    requested.wall_time_limit_millis = Some(60_000);
    let grant = EffectiveActivationBudget::admit_profile_at(
        BudgetProfile::Phase3,
        &requested,
        &requested,
        &requested,
        None,
        sample,
    )
    .unwrap();
    let budget = ActivationBudget::with_profile(grant, BudgetProfile::Phase3).unwrap();
    budget.enable_descendants(limits, probe).unwrap();
    (budget, sample)
}

fn child(
    parent: &ActivationBudget,
    state: Arc<State>,
    sample: ClockSample,
) -> super::super::ChildBudgetOwner {
    let mut requested = super::super::tests::request(100, 5_000, 0);
    requested.wall_time_limit_millis = Some(60_000);
    let delegation = parent
        .delegate_at(&requested, &requested, parent.granted(), None, sample)
        .unwrap();
    let grant = delegation.grant();
    delegation
        .accept(&grant, Arc::new(Probe(state)), sample.monotonic())
        .unwrap()
}

fn poll(watcher: &mut DescendantCancellation) -> Poll<()> {
    Pin::new(watcher).poll(&mut Context::from_waker(Waker::noop()))
}

#[test]
fn parent_custody_is_held_through_wake_and_physical_drop() {
    let state = Arc::new(State::default());
    let (budget, sample) = root(10_000, state.clone());
    let mut watcher = budget
        .prepare_descendant_cancellation_at(sample.monotonic())
        .unwrap();
    let expected = storage_bytes() + future_bytes();
    eprintln!(
        "watcher backing={} future={}",
        storage_bytes(),
        future_bytes()
    );
    assert_eq!(budget.host_memory_bytes(), expected);
    assert_eq!(state.builds.load(Ordering::SeqCst), 1);
    assert!(poll(&mut watcher).is_pending());
    Probe(state.clone()).mark_terminal();
    assert!(poll(&mut watcher).is_ready());
    assert_eq!(budget.host_memory_bytes(), expected);
    drop(watcher);
    assert_eq!(state.drops.load(Ordering::SeqCst), 1);
    assert_eq!(budget.host_memory_bytes(), 0);
    assert_eq!(budget.outstanding_reservations(), 0);
}

#[test]
fn watcher_is_charged_to_calling_parent_not_ancestor_or_delegated_child() {
    let ancestor = Arc::new(State::default());
    let calling = Arc::new(State::default());
    let (root, sample) = root(20_000, ancestor.clone());
    let child = child(&root, calling.clone(), sample);
    let calling_budget = child.accounting().clone();
    let mut watcher = calling_budget
        .prepare_descendant_cancellation_at(sample.monotonic())
        .unwrap();
    assert_eq!(root.host_memory_bytes(), 0);
    assert_eq!(
        calling_budget.host_memory_bytes(),
        storage_bytes() + 2 * future_bytes()
    );
    assert!(poll(&mut watcher).is_pending());
    Probe(ancestor.clone()).mark_terminal();
    assert!(poll(&mut watcher).is_ready());
    drop(watcher);
    assert_eq!(calling_budget.host_memory_bytes(), 0);
    assert_eq!(ancestor.drops.load(Ordering::SeqCst), 1);
    assert_eq!(calling.drops.load(Ordering::SeqCst), 1);
    let _ = child.finish(None, sample.monotonic());
    drop(calling_budget);
    assert_eq!(root.outstanding_reservations(), 0);
}

#[test]
fn full_depth_watches_each_original_ancestor_with_one_parent_charge() {
    let first = Arc::new(State::default());
    let limits = DelegationLimits {
        maximum_depth: 16,
        maximum_live_descendants: 32,
        maximum_live_children: 8,
    };
    let (root, sample) = root_with_limits(1_000_000, Arc::new(Probe(first.clone())), limits);
    let mut current = root.clone();
    let mut owners = Vec::new();
    let mut states = vec![first.clone()];
    for _ in 0..16 {
        let mut requested = current.granted().clone();
        requested.cpu_fuel -= 1;
        requested.memory_bytes -= 100;
        requested.child_calls -= 1;
        let delegation = current
            .delegate_at(&requested, &requested, current.granted(), None, sample)
            .unwrap();
        let grant = delegation.grant();
        let state = Arc::new(State::default());
        let owner = delegation
            .accept(&grant, Arc::new(Probe(state.clone())), sample.monotonic())
            .unwrap();
        current = owner.accounting().clone();
        owners.push(owner);
        states.push(state);
    }
    let mut watcher = current
        .prepare_descendant_cancellation_at(sample.monotonic())
        .unwrap();
    assert_eq!(
        current.host_memory_bytes(),
        storage_bytes() + 17 * future_bytes()
    );
    assert_eq!(root.host_memory_bytes(), 0);
    assert!(states
        .iter()
        .all(|state| state.builds.load(Ordering::SeqCst) == 1));
    assert!(poll(&mut watcher).is_pending());
    Probe(first).mark_terminal();
    assert!(poll(&mut watcher).is_ready());
    drop(watcher);
    assert_eq!(current.host_memory_bytes(), 0);
    assert!(states
        .iter()
        .all(|state| state.drops.load(Ordering::SeqCst) == 1));
    drop(current);
    while let Some(owner) = owners.pop() {
        let _ = owner.finish(None, sample.monotonic());
    }
    assert_eq!(root.outstanding_reservations(), 0);
}

#[test]
fn refusal_precedes_future_builder_and_rolls_back_the_backing() {
    let state = Arc::new(State::default());
    let (budget, sample) = root(10_000, state.clone());
    let occupied = 10_000 - storage_bytes() - future_bytes() + 1;
    let mut padding = budget.reserve_host_memory(occupied).unwrap();
    padding.confirm();
    assert!(budget
        .prepare_descendant_cancellation_at(sample.monotonic())
        .is_err());
    assert_eq!(state.builds.load(Ordering::SeqCst), 0);
    assert_eq!(state.drops.load(Ordering::SeqCst), 0);
    assert_eq!(budget.host_memory_bytes(), occupied);
    drop(padding);
    assert_eq!(budget.host_memory_bytes(), 0);
}

#[test]
fn partial_refusal_retires_the_first_future_and_original_backing() {
    let ancestor = Arc::new(State::default());
    let calling = Arc::new(State::default());
    let (root, sample) = root(20_000, ancestor.clone());
    let child = child(&root, calling.clone(), sample);
    let budget = child.accounting();
    let occupied = budget.granted().memory_bytes - storage_bytes() - 2 * future_bytes() + 1;
    let mut padding = budget.reserve_host_memory(occupied).unwrap();
    padding.confirm();
    assert!(budget
        .prepare_descendant_cancellation_at(sample.monotonic())
        .is_err());
    assert_eq!(calling.builds.load(Ordering::SeqCst), 1);
    assert_eq!(calling.drops.load(Ordering::SeqCst), 1);
    assert_eq!(ancestor.builds.load(Ordering::SeqCst), 0);
    assert_eq!(budget.host_memory_bytes(), occupied);
    assert_eq!(root.host_memory_bytes(), 0);
    drop(padding);
    let _ = child.finish(None, sample.monotonic());
    assert_eq!(root.outstanding_reservations(), 0);
}

#[test]
fn builder_panic_unwinds_prior_storage_and_owner() {
    let ancestor = Arc::new(State::default());
    ancestor.builder_panics.store(true, Ordering::Release);
    let calling = Arc::new(State::default());
    let (root, sample) = root(20_000, ancestor.clone());
    let child = child(&root, calling.clone(), sample);
    let budget = child.accounting();
    let outcome = catch_unwind(AssertUnwindSafe(|| {
        let _ = budget.prepare_descendant_cancellation_at(sample.monotonic());
    }));
    assert!(outcome.is_err());
    assert_eq!(calling.builds.load(Ordering::SeqCst), 1);
    assert_eq!(calling.drops.load(Ordering::SeqCst), 1);
    assert_eq!(ancestor.builds.load(Ordering::SeqCst), 1);
    assert_eq!(budget.host_memory_bytes(), 0);
    let _ = child.finish(None, sample.monotonic());
    assert_eq!(root.outstanding_reservations(), 0);
}

#[test]
fn panicking_future_destruction_retains_both_original_guards() {
    let state = Arc::new(State::default());
    state.drop_panics.store(true, Ordering::Release);
    let (budget, sample) = root(10_000, state.clone());
    let watcher = budget
        .prepare_descendant_cancellation_at(sample.monotonic())
        .unwrap();
    let held = budget.host_memory_bytes();
    let outcome = catch_unwind(AssertUnwindSafe(|| drop(watcher)));
    assert!(outcome.is_err());
    assert_eq!(state.drops.load(Ordering::SeqCst), 1);
    assert_eq!(held, storage_bytes() + future_bytes());
    assert_eq!(budget.host_memory_bytes(), held);
    assert_eq!(budget.outstanding_reservations(), 2);
}

struct LegacyProbe;
impl BudgetCancellationProbe for LegacyProbe {
    fn is_cancelled(&self) -> bool {
        false
    }
    fn cancelled(&self) -> BoxFuture<'_, ()> {
        Box::pin(std::future::ready(()))
    }
    fn mark_terminal(&self) {}
}

#[test]
fn old_probe_contract_compiles_and_the_new_owned_path_fails_closed() {
    let probe: Arc<dyn BudgetCancellationProbe> = Arc::new(LegacyProbe);
    let (budget, sample) = root_with_probe(10_000, probe.clone());
    // The legacy trait implementation stays callable without implementing the
    // added owned method. A missing owned factory cannot authorize a child.
    let mut old = probe.cancelled();
    assert!(old
        .as_mut()
        .poll(&mut Context::from_waker(Waker::noop()))
        .is_ready());
    drop(old);
    assert!(probe.cancelled_owned(&budget).is_err());
    assert!(budget
        .prepare_descendant_cancellation_at(sample.monotonic())
        .is_err());
    assert_eq!(budget.host_memory_bytes(), 0);
    assert_eq!(budget.outstanding_reservations(), 0);
}
struct ForeignProbe {
    foreign: ActivationBudget,
}

impl BudgetCancellationProbe for ForeignProbe {
    fn is_cancelled(&self) -> bool {
        false
    }
    fn cancelled(&self) -> BoxFuture<'_, ()> {
        Box::pin(std::future::pending())
    }
    fn cancelled_owned(
        self: Arc<Self>,
        _budget: &ActivationBudget,
    ) -> Result<OwnedCancellationFuture, PlatformError> {
        let foreign = self.foreign.clone();
        OwnedCancellationFuture::new(&foreign, move || async move {
            std::future::pending::<()>().await;
            drop(self);
        })
    }
    fn mark_terminal(&self) {}
}

#[test]
fn a_foreign_ledger_probe_is_rejected_and_both_ledgers_recover() {
    let (foreign, _) = root(10_000, Arc::new(State::default()));
    let (parent, sample) = root_with_probe(
        10_000,
        Arc::new(ForeignProbe {
            foreign: foreign.clone(),
        }),
    );
    assert!(parent
        .prepare_descendant_cancellation_at(sample.monotonic())
        .is_err());
    assert_eq!(parent.host_memory_bytes(), 0);
    assert_eq!(foreign.host_memory_bytes(), 0);
    assert_eq!(parent.outstanding_reservations(), 0);
    assert_eq!(foreign.outstanding_reservations(), 0);
}
