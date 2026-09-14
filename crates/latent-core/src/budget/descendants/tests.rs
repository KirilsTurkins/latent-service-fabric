use super::*;
use std::sync::{atomic::AtomicBool, Barrier};

#[derive(Default)]
struct Signal(
    AtomicBool,
    std::sync::Mutex<Option<std::task::Waker>>,
    AtomicBool,
);
impl BudgetCancellationProbe for Signal {
    fn is_cancelled(&self) -> bool {
        self.0.load(Ordering::Acquire)
    }
    fn cancelled(&self) -> crate::BoxFuture<'_, ()> {
        Box::pin(std::future::poll_fn(|context| {
            let mut waiter = self.1.lock().unwrap();
            if self.is_cancelled() || self.2.load(Ordering::Acquire) {
                std::task::Poll::Ready(())
            } else {
                *waiter = Some(context.waker().clone());
                std::task::Poll::Pending
            }
        }))
    }
    fn mark_terminal(&self) {
        self.2.store(true, Ordering::Release);
        let waiter = self.1.lock().unwrap().take();
        if let Some(waiter) = waiter {
            waiter.wake();
        }
    }
}
fn request(fuel: u64, memory: u64, calls: u32) -> ResourceBudget {
    ResourceBudget {
        cpu_fuel: fuel,
        memory_bytes: memory,
        wall_time_limit_millis: Some(1000),
        child_calls: calls,
        outbound_requests: 8,
        state_read_bytes: 0,
        state_write_bytes: 0,
        blob_read_bytes: 100,
        blob_write_bytes: 100,
        log_bytes: 100,
        effect_count: 0,
    }
}
fn root(limits: DelegationLimits) -> (ActivationBudget, Arc<Signal>, ClockSample) {
    let sample = ClockSample::new(1000, Instant::now());
    let requested = request(1000, 1000, 32);
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
    let signal = Arc::new(Signal::default());
    budget.enable_descendants(limits, signal.clone()).unwrap();
    (budget, signal, sample)
}
fn reserve(
    parent: &ActivationBudget,
    requested: &ResourceBudget,
    sample: ClockSample,
) -> Result<ChildBudgetDelegation, PlatformError> {
    parent.delegate_at(requested, requested, parent.granted(), None, sample)
}
fn accept(pending: ChildBudgetDelegation, sample: ClockSample) -> ChildBudgetOwner {
    let grant = pending.grant();
    pending
        .accept(&grant, Arc::new(Signal::default()), sample.monotonic())
        .unwrap()
}

#[test]
fn child_reservations_retire_only_after_execution_and_retained_provider_owners() {
    let (parent, _, sample) = root(DelegationLimits::default());
    parent.observe_peak_memory(100).unwrap();
    let child = accept(
        reserve(&parent, &request(100, 400, 0), sample).unwrap(),
        sample,
    );
    assert_eq!(parent.remaining_at(sample.monotonic()).cpu_fuel, 900);
    assert_eq!(parent.remaining_at(sample.monotonic()).memory_bytes, 500);
    child.accounting().observe_runtime_usage(17, 200).unwrap();
    child
        .accounting()
        .consume(BudgetDimension::BlobReadBytes, 23)
        .unwrap();
    assert_eq!(
        parent.snapshot_at(sample.monotonic()).peak_memory_bytes,
        300
    );
    let provider = child.accounting().clone();
    let done = child.finish(None, sample.monotonic());
    assert_eq!(done.consumption().cpu_fuel, 17);
    assert_eq!(parent.descendant_snapshot().unwrap().live_descendants, 1);
    assert_eq!(parent.remaining_at(sample.monotonic()).cpu_fuel, 900);
    drop(provider);
    let usage = parent.snapshot_at(sample.monotonic());
    assert_eq!(
        (usage.cpu_fuel, usage.child_calls, usage.blob_read_bytes),
        (17, 1, 23)
    );
    assert_eq!(parent.remaining_at(sample.monotonic()).memory_bytes, 900);
    assert_eq!(parent.remaining_at(sample.monotonic()).cpu_fuel, 983);
    assert_eq!(parent.outstanding_reservations(), 0);
    assert_eq!(parent.descendant_snapshot().unwrap().live_descendants, 0);
}

#[test]
fn failed_admission_and_invalid_deadline_refund_once_without_spending_child_call() {
    let (parent, _, sample) = root(DelegationLimits::default());
    let original = parent.remaining_at(sample.monotonic());
    let pending = reserve(&parent, &request(100, 100, 1), sample).unwrap();
    let mut wrong = pending.grant();
    wrong.budget.cpu_fuel += 1;
    assert!(pending
        .accept(&wrong, Arc::new(Signal::default()), sample.monotonic())
        .is_err());
    assert_eq!(parent.remaining_at(sample.monotonic()), original);
    assert_eq!(parent.descendant_snapshot().unwrap().live_descendants, 0);
    drop(reserve(&parent, &request(100, 100, 1), sample).unwrap());
    assert_eq!(parent.snapshot_at(sample.monotonic()).child_calls, 0);
    assert_eq!(parent.outstanding_reservations(), 0);
}

#[test]
fn admission_cannot_restart_the_parents_absolute_child_deadline() {
    let (parent, _, sample) = root(DelegationLimits::default());
    let requested = request(100, 100, 0);
    let pending = reserve(&parent, &requested, sample).unwrap();
    let later = ClockSample::new(1, sample.monotonic() + std::time::Duration::from_millis(10));
    let restarted = EffectiveActivationBudget::admit_profile_at(
        BudgetProfile::Phase3,
        &requested,
        &requested,
        &requested,
        None,
        later,
    )
    .unwrap();
    assert!(pending
        .accept(&restarted, Arc::new(Signal::default()), later.monotonic())
        .is_err());
    assert_eq!(parent.outstanding_reservations(), 0);
    let pending = reserve(&parent, &requested, sample).unwrap();
    let incoming = crate::IncomingDeadline::new(parent.deadline().monotonic().unwrap(), 1);
    let bounded = EffectiveActivationBudget::admit_profile_with_deadline_at(
        BudgetProfile::Phase3,
        &requested,
        &requested,
        &requested,
        &incoming,
        later,
    )
    .unwrap();
    let child = pending
        .accept(&bounded, Arc::new(Signal::default()), later.monotonic())
        .unwrap();
    assert_eq!(
        child.accounting().deadline().monotonic(),
        parent.deadline().monotonic()
    );
    let _ = child.finish(None, later.monotonic());
}

#[test]
fn parent_cancellation_and_terminal_state_cancel_children_without_early_refunds() {
    let (parent, signal, sample) = root(DelegationLimits::default());
    let child = accept(
        reserve(&parent, &request(100, 100, 1), sample).unwrap(),
        sample,
    );
    signal.0.store(true, Ordering::Release);
    assert!(child.accounting().descendant_is_cancelled());
    assert!(reserve(&parent, &request(1, 1, 0), sample).is_err());
    let frozen = parent.finalize_at(None, sample.monotonic());
    assert_eq!(parent.outstanding_reservations(), 1);
    let late = child.accounting().clone();
    child.accounting().consume_cpu_fuel(3).unwrap();
    let _ = child.finish(None, sample.monotonic());
    assert_eq!(parent.outstanding_reservations(), 1);
    drop(late);
    assert_eq!(parent.outstanding_reservations(), 0);
    assert_eq!(parent.finalize_at(None, sample.monotonic()), frozen);
}

#[test]
fn retained_ancestry_stays_charged_through_late_grandchild_completion() {
    let (parent, _, sample) = root(DelegationLimits::default());
    let child = accept(
        reserve(&parent, &request(100, 400, 4), sample).unwrap(),
        sample,
    );
    child.accounting().observe_runtime_usage(10, 100).unwrap();
    let grandchild = accept(
        reserve(child.accounting(), &request(20, 200, 0), sample).unwrap(),
        sample,
    );
    grandchild
        .accounting()
        .observe_runtime_usage(5, 50)
        .unwrap();
    assert_eq!(
        parent.snapshot_at(sample.monotonic()).peak_memory_bytes,
        150
    );
    let _ = child.finish(None, sample.monotonic());
    assert_eq!(parent.descendant_snapshot().unwrap().live_descendants, 2);
    assert!(grandchild.accounting().descendant_is_cancelled());
    let _ = grandchild.finish(None, sample.monotonic());
    let usage = parent.snapshot_at(sample.monotonic());
    assert_eq!((usage.cpu_fuel, usage.child_calls), (15, 2));
    assert_eq!(parent.descendant_snapshot().unwrap().live_descendants, 0);
    assert_eq!(parent.outstanding_reservations(), 0);
}

#[test]
fn independent_memory_reservations_and_observed_peaks_stay_within_parent_grant() {
    let (parent, _, sample) = root(DelegationLimits::default());
    parent.observe_peak_memory(800).unwrap();
    assert!(reserve(&parent, &request(100, 300, 0), sample).is_ok());
    // Parent remaining memory narrows the requested child to 200, never 300.
    let pending = reserve(&parent, &request(100, 300, 0), sample).unwrap();
    assert_eq!(pending.grant().budget.memory_bytes, 200);
    let child = accept(pending, sample);
    assert!(parent.observe_peak_memory(801).is_err());
    assert!(child.accounting().observe_runtime_usage(1, 201).is_err());
    assert_eq!(
        child.accounting().snapshot_at(sample.monotonic()).cpu_fuel,
        0
    );
    child.accounting().observe_runtime_usage(3, 200).unwrap();
    assert_eq!(
        parent.snapshot_at(sample.monotonic()).peak_memory_bytes,
        1000
    );
    let _ = child.finish(None, sample.monotonic());
    assert_eq!(parent.remaining_at(sample.monotonic()).memory_bytes, 200);
}

#[test]
fn depth_fanout_and_global_retained_frames_are_finite() {
    let (parent, _, sample) = root(DelegationLimits {
        maximum_depth: 2,
        maximum_live_children: 1,
        maximum_live_descendants: 2,
    });
    let child = accept(
        reserve(&parent, &request(100, 400, 4), sample).unwrap(),
        sample,
    );
    assert!(reserve(&parent, &request(1, 1, 0), sample).is_err());
    assert!(child
        .accounting()
        .enable_descendants(DelegationLimits::default(), Arc::new(Signal::default()))
        .is_err());
    let grandchild = accept(
        reserve(child.accounting(), &request(20, 200, 1), sample).unwrap(),
        sample,
    );
    assert!(reserve(grandchild.accounting(), &request(1, 1, 0), sample).is_err());
    let _ = grandchild.finish(None, sample.monotonic());
    let _ = child.finish(None, sample.monotonic());
    assert_eq!(parent.descendant_snapshot().unwrap().live_descendants, 0);
}

#[test]
fn simultaneous_delegation_never_exceeds_the_original_ledger() {
    let (parent, _, sample) = root(DelegationLimits {
        maximum_live_children: 16,
        ..DelegationLimits::default()
    });
    let barrier = Arc::new(Barrier::new(16));
    let workers: Vec<_> = (0..16)
        .map(|_| {
            let parent = parent.clone();
            let barrier = barrier.clone();
            std::thread::spawn(move || {
                barrier.wait();
                reserve(&parent, &request(250, 1, 0), sample).ok()
            })
        })
        .collect();
    let held: Vec<_> = workers
        .into_iter()
        .filter_map(|w| w.join().unwrap())
        .collect();
    let reserved: u64 = held.iter().map(|d| d.grant().budget.cpu_fuel).sum();
    assert!(reserved <= 1000);
    assert_eq!(
        parent.remaining_at(sample.monotonic()).cpu_fuel + reserved,
        1000
    );
    drop(held);
    assert_eq!(parent.remaining_at(sample.monotonic()).cpu_fuel, 1000);
    assert_eq!(parent.snapshot_at(sample.monotonic()).child_calls, 0);
    assert_eq!(parent.descendant_snapshot().unwrap().live_descendants, 0);
}

#[test]
fn abandoned_accepted_child_consumes_its_grant_without_a_completion_claim() {
    let (parent, _, sample) = root(DelegationLimits::default());
    let child = accept(
        reserve(&parent, &request(100, 100, 0), sample).unwrap(),
        sample,
    );
    drop(child);
    assert_eq!(parent.snapshot_at(sample.monotonic()).cpu_fuel, 100);
    assert_eq!(parent.snapshot_at(sample.monotonic()).child_calls, 1);
    assert_eq!(parent.outstanding_reservations(), 0);
}

#[test]
fn own_backend_totals_are_reconciled_separately_from_settled_children() {
    let (parent, _, sample) = root(DelegationLimits::default());
    let child = accept(
        reserve(&parent, &request(100, 400, 4), sample).unwrap(),
        sample,
    );
    child.accounting().consume_cpu_fuel(7).unwrap();
    let grandchild = accept(
        reserve(child.accounting(), &request(20, 200, 0), sample).unwrap(),
        sample,
    );
    grandchild
        .accounting()
        .observe_runtime_usage(5, 50)
        .unwrap();
    let _ = grandchild.finish(None, sample.monotonic());
    let report = BudgetConsumption {
        cpu_fuel: 9,
        peak_memory_bytes: 100,
        ..BudgetConsumption::default()
    };
    let done = child.finish(Some(&report), sample.monotonic());
    assert!(done.violation().is_none());
    assert_eq!(done.consumption().cpu_fuel, 14);
    let usage = parent.snapshot_at(sample.monotonic());
    assert_eq!(usage.cpu_fuel, 14);
    assert_eq!(usage.peak_memory_bytes, 100);
    assert_eq!(usage.child_calls, 2);
}

#[test]
fn invalid_child_report_cannot_refund_an_unproven_unused_grant() {
    let (parent, _, sample) = root(DelegationLimits::default());
    let child = accept(
        reserve(&parent, &request(100, 100, 0), sample).unwrap(),
        sample,
    );
    let report = BudgetConsumption {
        cpu_fuel: 101,
        ..BudgetConsumption::default()
    };
    let done = child.finish(Some(&report), sample.monotonic());
    assert!(done.violation().is_some());
    assert_eq!(parent.snapshot_at(sample.monotonic()).cpu_fuel, 100);
    assert_eq!(parent.outstanding_reservations(), 0);
}

#[test]
fn global_tree_limit_is_independent_of_depth_and_fanout() {
    let (parent, _, sample) = root(DelegationLimits {
        maximum_depth: 8,
        maximum_live_children: 2,
        maximum_live_descendants: 2,
    });
    let child = accept(
        reserve(&parent, &request(100, 100, 4), sample).unwrap(),
        sample,
    );
    let grandchild = accept(
        reserve(child.accounting(), &request(10, 10, 1), sample).unwrap(),
        sample,
    );
    assert_eq!(parent.descendant_snapshot().unwrap().live_children, 1);
    assert_eq!(
        grandchild.accounting().descendant_snapshot().unwrap().depth,
        2
    );
    assert!(reserve(&parent, &request(10, 10, 0), sample).is_err());
    assert!(reserve(grandchild.accounting(), &request(1, 1, 0), sample).is_err());
    let _ = child.finish(None, sample.monotonic());
    assert_eq!(parent.descendant_snapshot().unwrap().live_descendants, 2);
    let _ = grandchild.finish(None, sample.monotonic());
    assert_eq!(parent.descendant_snapshot().unwrap().live_descendants, 0);
}

#[test]
fn parent_finalization_races_delegation_without_early_refund_or_reopening() {
    for _ in 0..32 {
        let (parent, signal, sample) = root(DelegationLimits::default());
        let barrier = Arc::new(Barrier::new(3));
        let delegator = parent.clone();
        let start = barrier.clone();
        let worker = std::thread::spawn(move || {
            start.wait();
            reserve(&delegator, &request(50, 50, 0), sample)
                .and_then(|pending| {
                    let grant = pending.grant();
                    pending.accept(&grant, Arc::new(Signal::default()), sample.monotonic())
                })
                .ok()
        });
        let start = barrier.clone();
        let canceller = std::thread::spawn(move || {
            start.wait();
            signal.0.store(true, Ordering::Release);
            signal.mark_terminal();
        });
        barrier.wait();
        let frozen = parent.finalize_at(None, sample.monotonic());
        let owner = worker.join().unwrap();
        canceller.join().unwrap();
        if let Some(owner) = owner {
            assert!(owner.accounting().descendant_is_cancelled());
            assert_eq!(parent.outstanding_reservations(), 1);
            let _ = owner.finish(None, sample.monotonic());
        }
        assert_eq!(parent.outstanding_reservations(), 0);
        assert_eq!(parent.descendant_snapshot().unwrap().live_descendants, 0);
        assert_eq!(parent.finalization().unwrap(), frozen);
        assert!(reserve(&parent, &request(1, 1, 0), sample).is_err());
    }
}

#[test]
fn terminal_notification_wakes_waiting_descendant_without_releasing_ownership() {
    use std::{
        future::Future,
        task::{Context, Wake, Waker},
    };
    #[derive(Default)]
    struct Wakes(AtomicUsize);
    impl Wake for Wakes {
        fn wake(self: Arc<Self>) {
            self.0.fetch_add(1, Ordering::Relaxed);
        }
    }
    let (parent, _, sample) = root(DelegationLimits::default());
    let child = accept(
        reserve(&parent, &request(100, 100, 0), sample).unwrap(),
        sample,
    );
    let ledger = child.accounting().clone();
    let mut waiting = Box::pin(ledger.descendant_cancelled());
    let notifications = Arc::new(Wakes::default());
    let waker = Waker::from(notifications.clone());
    let mut context = Context::from_waker(&waker);
    assert!(waiting.as_mut().poll(&mut context).is_pending());
    let _ = parent.finalize_at(None, sample.monotonic());
    assert_eq!(notifications.0.load(Ordering::Relaxed), 1);
    assert!(waiting.as_mut().poll(&mut context).is_ready());
    let _ = child.finish(None, sample.monotonic());
    assert_eq!(parent.outstanding_reservations(), 1);
    drop(waiting);
    drop(ledger);
    assert_eq!(parent.outstanding_reservations(), 0);
}
