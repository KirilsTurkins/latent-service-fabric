//! Actual original-ledger reservations for the activation runtime's backings.
use super::*;
use latent_core::{ActivationBudget, BudgetCancellationProbe, DelegationLimits};

struct Signal;
impl BudgetCancellationProbe for Signal {
    fn is_cancelled(&self) -> bool {
        false
    }
    fn cancelled(&self) -> latent_core::BoxFuture<'_, ()> {
        Box::pin(std::future::pending())
    }
    fn mark_terminal(&self) {}
}

fn budget(bytes: u64) -> ActivationBudget {
    let budget = crate::host::native_table_tests::budget(bytes);
    budget
        .enable_descendants(DelegationLimits::default(), Arc::new(Signal))
        .unwrap();
    budget
}

fn limits(timers: u32) -> RuntimeLimits {
    RuntimeLimits {
        tasks: 1,
        executors: 0,
        queued_work: 0,
        waits: 0,
        timers,
        results: 0,
        native_owners: 0,
    }
}

fn table_bytes(limits: RuntimeLimits) -> u64 {
    (std::mem::size_of::<Table>()
        + std::mem::size_of::<RuntimeOwner>() * limits.total()
        + BACKING_ALLOCATION_BOOKKEEPING
        + if limits.timers == 0 {
            0
        } else {
            std::mem::size_of::<RuntimeTimer>() * limits.timers as usize
                + BACKING_ALLOCATION_BOOKKEEPING
        }) as u64
}

#[test]
fn runtime_table_prepays_each_real_backing_and_no_empty_timer_allocation() {
    for count in [0, 2] {
        let limits = limits(count);
        let expected = table_bytes(limits);
        let budget = budget(1_000_000);
        let runtime = ActivationRuntime::new(budget.clone(), limits).unwrap();
        let header = budget.host_memory_bytes();
        assert!(header > 0);
        drop(runtime);
        assert_eq!(budget.host_memory_bytes(), 0);
        let table = Table::new(budget.clone(), limits, None).unwrap();
        assert_eq!(table.owners.capacity(), limits.total());
        assert_eq!(table.timers.capacity(), count as usize);
        assert_eq!(budget.host_memory_bytes(), expected + header);
        drop(table);
        assert_eq!(budget.host_memory_bytes(), 0);
        assert_eq!(budget.outstanding_reservations(), 0);
    }
}

#[test]
fn runtime_table_refusals_release_original_reservation_before_publication() {
    let limits = limits(2);
    let bytes = table_bytes(limits);
    // This fails before either backing allocation.
    let too_small = budget(bytes - 1);
    assert!(matches!(Table::new(too_small.clone(), limits, None),
        Err(error) if error.code == PlatformErrorCode::ResourceExhausted));
    assert_eq!(too_small.host_memory_bytes(), 0);
    assert_eq!(too_small.outstanding_reservations(), 0);
    assert_eq!(too_small.snapshot_at(Instant::now()).peak_memory_bytes, 0);

    // The table backings fit, but the separately charged runtime header does
    // not. The constructor must drop both backings and its pending guard.
    let no_header = budget(bytes);
    assert!(matches!(Table::new(no_header.clone(), limits, None),
        Err(error) if error.code == PlatformErrorCode::ResourceExhausted));
    assert_eq!(no_header.host_memory_bytes(), 0);
    assert_eq!(no_header.outstanding_reservations(), 0);
    assert_eq!(
        no_header.snapshot_at(Instant::now()).peak_memory_bytes,
        bytes - std::mem::size_of::<Table>() as u64
    );
}
