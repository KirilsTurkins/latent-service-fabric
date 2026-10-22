//! Actual physical owners keep memory, not unused cumulative execution grants.
use super::tests::{accept, request, reserve, root};
use super::*;
use crate::{BudgetConsumption, HostMemoryReservation};

struct Native {
    // Physical allocation destruction precedes its original accounting guard.
    _bytes: Box<[u8]>,
    _memory: HostMemoryReservation,
}
fn native(child: &ChildBudgetOwner) -> Native {
    let mut memory = child.accounting().reserve_host_memory(64).unwrap();
    let bytes = vec![0; 64].into_boxed_slice();
    memory.confirm();
    assert!(memory.is_from_budget(child.accounting()));
    Native {
        _bytes: bytes,
        _memory: memory,
    }
}

#[test]
fn native_only_owner_settles_actual_work_without_refunding_physical_child_capacity() {
    let (parent, _, sample) = root(DelegationLimits::default());
    let child = accept(
        reserve(&parent, &request(100, 300, 7), sample).unwrap(),
        sample,
    );
    let native = native(&child);
    child.accounting().consume_cpu_fuel(17).unwrap();
    child.accounting().consume_log_bytes(4).unwrap();
    let report = child.finish(None, sample.monotonic());
    assert!(report.violation().is_none());
    let used = parent.snapshot_at(sample.monotonic());
    assert_eq!(
        (used.cpu_fuel, used.log_bytes, used.child_calls),
        (17, 4, 1)
    );
    assert_eq!(parent.outstanding_reservations(), 0);
    let physical = parent.descendant_snapshot().unwrap();
    assert_eq!((physical.live_children, physical.live_descendants), (1, 1));
    assert_eq!(physical.reserved_memory_bytes, 300);
    assert_eq!(physical.live_observed_child_memory_bytes, 64);
    assert_eq!(parent.remaining_at(sample.monotonic()).memory_bytes, 700);
    assert!(
        reserve(&parent, &request(1, 701, 0), sample)
            .unwrap()
            .grant()
            .budget
            .memory_bytes
            <= 700
    );
    drop(native);
    let physical = parent.descendant_snapshot().unwrap();
    assert_eq!((physical.live_children, physical.live_descendants), (0, 0));
    assert_eq!(physical.reserved_memory_bytes, 0);
    assert_eq!(physical.live_observed_child_memory_bytes, 0);
    assert_eq!(parent.remaining_at(sample.monotonic()).memory_bytes, 1000);
    assert_eq!(parent.snapshot_at(sample.monotonic()), used);
}

#[test]
fn ordinary_retained_accounting_owner_still_holds_the_whole_accepted_grant() {
    let (parent, _, sample) = root(DelegationLimits::default());
    let child = accept(
        reserve(&parent, &request(100, 300, 7), sample).unwrap(),
        sample,
    );
    let retained = child.accounting().clone();
    let native = native(&child);
    child.accounting().consume_cpu_fuel(17).unwrap();
    let report = child.finish(None, sample.monotonic());
    assert!(report.violation().is_none());
    assert_eq!(parent.snapshot_at(sample.monotonic()).cpu_fuel, 100);
    assert_eq!(parent.snapshot_at(sample.monotonic()).child_calls, 8);
    assert_eq!(parent.outstanding_reservations(), 1);
    assert_eq!(retained.host_memory_bytes(), 64);
    assert_eq!(retained.outstanding_reservations(), 1);
    assert!(retained.reserve_host_memory(1).is_err());
    drop(retained);
    assert_eq!(parent.snapshot_at(sample.monotonic()).cpu_fuel, 17);
    assert_eq!(parent.snapshot_at(sample.monotonic()).child_calls, 1);
    assert_eq!(parent.outstanding_reservations(), 0);
    assert_eq!(
        parent.descendant_snapshot().unwrap().reserved_memory_bytes,
        300
    );
    drop(native);
    assert_eq!(parent.descendant_snapshot().unwrap().live_descendants, 0);
    assert_eq!(parent.remaining_at(sample.monotonic()).memory_bytes, 1000);
}

#[test]
fn missing_or_invalid_completion_remains_conservative_with_native_only_owners() {
    for invalid in [false, true] {
        let (parent, _, sample) = root(DelegationLimits::default());
        let child = accept(
            reserve(&parent, &request(100, 300, 7), sample).unwrap(),
            sample,
        );
        let native = native(&child);
        child.accounting().consume_cpu_fuel(5).unwrap();
        if invalid {
            let report = child.finish(
                Some(&BudgetConsumption {
                    cpu_fuel: 101,
                    ..BudgetConsumption::default()
                }),
                sample.monotonic(),
            );
            assert!(report.violation().is_some());
        } else {
            // Dropping the actual execution owner without finalizing is not
            // evidence that the unconsumed ceiling can be returned.
            drop(child);
        }
        let used = parent.snapshot_at(sample.monotonic());
        assert_eq!((used.cpu_fuel, used.child_calls), (100, 8));
        assert_eq!(parent.outstanding_reservations(), 0);
        assert_eq!(
            parent.descendant_snapshot().unwrap().reserved_memory_bytes,
            300
        );
        assert_eq!(parent.descendant_snapshot().unwrap().live_descendants, 1);
        drop(native);
        assert_eq!(parent.snapshot_at(sample.monotonic()), used);
        assert_eq!(parent.remaining_at(sample.monotonic()).memory_bytes, 1000);
        assert_eq!(parent.descendant_snapshot().unwrap().live_descendants, 0);
    }
}

#[test]
fn transitive_native_ancestry_never_pins_an_ordinary_ancestor_cumulative_grant() {
    let (parent, _, sample) = root(DelegationLimits::default());
    let child = accept(
        reserve(&parent, &request(400, 700, 8), sample).unwrap(),
        sample,
    );
    let grandchild = accept(
        reserve(child.accounting(), &request(100, 200, 2), sample).unwrap(),
        sample,
    );
    let native = native(&grandchild);
    grandchild.accounting().consume_cpu_fuel(7).unwrap();
    assert!(grandchild
        .finish(None, sample.monotonic())
        .violation()
        .is_none());
    assert_eq!(
        child.accounting().snapshot_at(sample.monotonic()).cpu_fuel,
        7
    );
    assert_eq!(
        child
            .accounting()
            .snapshot_at(sample.monotonic())
            .child_calls,
        1
    );
    assert!(child.finish(None, sample.monotonic()).violation().is_none());
    let used = parent.snapshot_at(sample.monotonic());
    assert_eq!((used.cpu_fuel, used.child_calls), (7, 2));
    assert_eq!(parent.outstanding_reservations(), 0);
    let physical = parent.descendant_snapshot().unwrap();
    assert_eq!((physical.live_children, physical.live_descendants), (1, 2));
    assert_eq!(physical.reserved_memory_bytes, 700);
    assert_eq!(physical.live_observed_child_memory_bytes, 64);
    drop(native);
    let physical = parent.descendant_snapshot().unwrap();
    assert_eq!((physical.live_children, physical.live_descendants), (0, 0));
    assert_eq!(physical.reserved_memory_bytes, 0);
    assert_eq!(physical.live_observed_child_memory_bytes, 0);
    assert_eq!(parent.remaining_at(sample.monotonic()).memory_bytes, 1000);
    assert_eq!(parent.snapshot_at(sample.monotonic()), used);
}

#[test]
fn concurrent_last_ordinary_and_physical_owners_settle_each_original_counter_once() {
    for _ in 0..8 {
        let (parent, _, sample) = root(DelegationLimits::default());
        let child = accept(
            reserve(&parent, &request(100, 300, 7), sample).unwrap(),
            sample,
        );
        let first = child.accounting().clone();
        let second = child.accounting().clone();
        let native = native(&child);
        child.accounting().consume_cpu_fuel(17).unwrap();
        assert!(child.finish(None, sample.monotonic()).violation().is_none());
        assert_eq!(parent.outstanding_reservations(), 1);
        let barrier = Arc::new(std::sync::Barrier::new(4));
        std::thread::scope(|scope| {
            for retained in [first, second] {
                let barrier = barrier.clone();
                scope.spawn(move || {
                    barrier.wait();
                    drop(retained);
                });
            }
            let physical_barrier = barrier.clone();
            scope.spawn(move || {
                physical_barrier.wait();
                drop(native);
            });
            barrier.wait();
        });
        let used = parent.snapshot_at(sample.monotonic());
        assert_eq!(
            (used.cpu_fuel, used.child_calls, used.peak_memory_bytes),
            (17, 1, 64)
        );
        assert_eq!(parent.outstanding_reservations(), 0);
        let physical = parent.descendant_snapshot().unwrap();
        assert_eq!((physical.live_children, physical.live_descendants), (0, 0));
        assert_eq!(physical.reserved_memory_bytes, 0);
        assert_eq!(physical.live_observed_child_memory_bytes, 0);
        assert_eq!(parent.remaining_at(sample.monotonic()).memory_bytes, 1000);
    }
}
