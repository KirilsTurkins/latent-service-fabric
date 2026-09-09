use std::sync::{Arc, Barrier};
use std::time::Instant;

use super::*;
use crate::{ClockSample, EffectiveActivationBudget, ResourceBudget};

fn accounting(fuel: u64, memory: u64) -> (ActivationBudget, Instant) {
    let now = Instant::now();
    let budget = ResourceBudget {
        cpu_fuel: fuel,
        memory_bytes: memory,
        wall_time_limit_millis: None,
        child_calls: 0,
        outbound_requests: 0,
        state_read_bytes: 0,
        state_write_bytes: 0,
        blob_read_bytes: 0,
        blob_write_bytes: 0,
        log_bytes: 100,
        effect_count: 0,
    };
    let grant = EffectiveActivationBudget::admit_at(
        &budget,
        &budget,
        &budget,
        None,
        ClockSample::new(1000, now),
    )
    .unwrap();
    (ActivationBudget::new(grant), now)
}

#[test]
fn failed_memory_or_fuel_observation_changes_neither_counter() {
    let (budget, now) = accounting(10, 20);
    budget.observe_runtime_usage(3, 4).unwrap();
    let before = budget.snapshot_at(now);
    assert!(matches!(
        budget.observe_runtime_usage(1, 21),
        Err(BudgetError::Exhausted {
            dimension: BudgetDimension::MemoryBytes,
            consumed: 4,
            requested: 21,
            ..
        })
    ));
    assert_eq!(budget.snapshot_at(now), before);
    assert!(matches!(
        budget.observe_runtime_usage(8, 19),
        Err(BudgetError::Exhausted {
            dimension: BudgetDimension::CpuFuel,
            consumed: 3,
            requested: 8,
            ..
        })
    ));
    assert_eq!(budget.snapshot_at(now), before);
    budget.observe_runtime_usage(7, 2).unwrap();
    assert_eq!(budget.snapshot_at(now).cpu_fuel, 10);
    assert_eq!(budget.snapshot_at(now).peak_memory_bytes, 4);
    budget.observe_runtime_usage(0, 20).unwrap();
    assert_eq!(budget.snapshot_at(now).peak_memory_bytes, 20);
}

#[test]
fn overflow_and_finalized_state_leave_the_transaction_unchanged() {
    let (budget, now) = accounting(u64::MAX, 20);
    budget.observe_runtime_usage(u64::MAX, 4).unwrap();
    let before = budget.snapshot_at(now);
    assert_eq!(
        budget.observe_runtime_usage(1, 19),
        Err(BudgetError::ArithmeticOverflow {
            dimension: BudgetDimension::CpuFuel,
        })
    );
    assert_eq!(budget.snapshot_at(now), before);
    let finalization = budget.finalize_at(None, now);
    for (fuel, memory) in [(0, 0), (1, 19), (u64::MAX, u64::MAX)] {
        assert_eq!(
            budget.observe_runtime_usage(fuel, memory),
            Err(BudgetError::AccountingFinalized)
        );
        assert_eq!(budget.snapshot_at(now), *finalization.consumption());
    }
}

#[test]
fn provisional_fuel_and_logs_keep_commit_refund_and_finalization_semantics() {
    let (budget, now) = accounting(10, 20);
    let fuel = budget.reserve(BudgetDimension::CpuFuel, 5).unwrap();
    let logs = budget.reserve_log_bytes(7).unwrap();
    budget.consume_log_bytes(2).unwrap();
    budget.observe_runtime_usage(3, 4).unwrap();
    assert_eq!(budget.remaining_at(now).cpu_fuel, 2);
    assert_eq!(budget.remaining_at(now).log_bytes, 91);
    assert_eq!(budget.snapshot_at(now).cpu_fuel, 3);
    assert_eq!(budget.snapshot_at(now).log_bytes, 2);
    assert!(budget.observe_runtime_usage(3, 8).is_err());
    assert_eq!(budget.snapshot_at(now).peak_memory_bytes, 4);
    drop(fuel);
    assert_eq!(budget.remaining_at(now).cpu_fuel, 7);
    let finalized = budget.finalize_at(None, now);
    assert_eq!(finalized.consumption().cpu_fuel, 3);
    assert_eq!(finalized.consumption().peak_memory_bytes, 4);
    assert_eq!(finalized.consumption().log_bytes, 2);
    drop(logs);
    assert_eq!(budget.snapshot_at(now), *finalized.consumption());
    assert_eq!(budget.outstanding_reservations(), 0);
}

#[test]
fn finalization_racing_an_observation_never_freezes_half_a_transaction() {
    for _ in 0..16 {
        let (budget, now) = accounting(1, 2);
        let start = Arc::new(Barrier::new(2));
        let writer = budget.clone();
        let ready = Arc::clone(&start);
        let task = std::thread::spawn(move || {
            ready.wait();
            writer.observe_runtime_usage(1, 2)
        });
        start.wait();
        let finalized = budget.finalize_at(None, now);
        let result = task.join().unwrap();
        let observed = (
            finalized.consumption().cpu_fuel,
            finalized.consumption().peak_memory_bytes,
        );
        match result {
            Ok(()) => assert_eq!(observed, (1, 2)),
            Err(BudgetError::AccountingFinalized) => assert_eq!(observed, (0, 0)),
            other => panic!("unexpected observation result: {other:?}"),
        }
    }
}
