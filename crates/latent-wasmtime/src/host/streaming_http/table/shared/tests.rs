//! Shipping Shared/Arc and original ledger; no replacement allocator/ledger.
use super::*;
use latent_core::{ActivationBudget, BudgetDimension, BudgetError};
use std::sync::{
    atomic::{AtomicU64, Ordering},
    Barrier,
};
fn budget(bytes: u64) -> ActivationBudget {
    crate::host::native_table_tests::budget(bytes)
}
fn selected<T>(value: T, budget: &ActivationBudget) -> Result<Shared<T>, BudgetError> {
    let bytes = Shared::<T>::allocation_bytes().unwrap();
    let memory = budget.reserve_host_memory(bytes)?;
    Ok(Shared::new(value, Some(memory)).unwrap())
}
fn peak(budget: &ActivationBudget) -> u64 {
    budget
        .snapshot_at(std::time::Instant::now())
        .peak_memory_bytes
}

#[test]
fn native_streaming_shared_arc_clones_hold_original_backing_and_phase1_stays_unbound() {
    let bytes = Shared::<AtomicU64>::allocation_bytes().unwrap();
    let budget = budget(1024 * 1024);
    let first = selected(AtomicU64::new(42), &budget).unwrap();
    assert_eq!(budget.host_memory_bytes(), bytes);
    assert_eq!(budget.outstanding_reservations(), 1);
    assert_eq!(peak(&budget), bytes);
    let last = first.clone();
    first.store(62, Ordering::SeqCst);
    drop(first);
    assert_eq!(last.load(Ordering::SeqCst), 62);
    assert_eq!(budget.host_memory_bytes(), bytes);
    drop(last);
    assert_eq!(budget.host_memory_bytes(), 0);
    assert_eq!(budget.outstanding_reservations(), 0);
    let legacy = Shared::new(AtomicU64::new(42), None).unwrap();
    let clone = legacy.clone();
    drop(legacy);
    assert_eq!(clone.load(Ordering::SeqCst), 42);
    assert_eq!(budget.host_memory_bytes(), 0);
    drop(clone);
}

#[test]
fn native_streaming_shared_arc_refusal_preserves_exact_budget_and_fresh_same_grant() {
    let bytes = Shared::<AtomicU64>::allocation_bytes().unwrap();
    let limit = bytes * 4;
    let budget = budget(limit);
    let first = selected(AtomicU64::new(42), &budget).unwrap();
    let padding_bytes = limit - 2 * bytes + 1;
    let mut guard = budget.reserve_host_memory(padding_bytes).unwrap();
    let padding = vec![0u8; padding_bytes as usize].into_boxed_slice();
    guard.confirm();
    let error = match selected(AtomicU64::new(0), &budget) {
        Ok(_) => panic!("original memory admission must precede the Arc"),
        Err(error) => error,
    };
    assert!(matches!(error, BudgetError::Exhausted {
        dimension: BudgetDimension::MemoryBytes, limit: l, consumed: c, requested: r,
    } if (l,c,r) == (limit, bytes + padding_bytes, bytes)));
    assert_eq!(budget.host_memory_bytes(), bytes + padding_bytes);
    assert_eq!(peak(&budget), bytes + padding_bytes);
    assert_eq!(first.load(Ordering::SeqCst), 42);
    drop(padding);
    drop(guard);
    let fresh = selected(AtomicU64::new(62), &budget).unwrap();
    assert_eq!(fresh.load(Ordering::SeqCst), 62);
    assert_eq!(budget.host_memory_bytes(), 2 * bytes);
    drop(first);
    assert_eq!(budget.host_memory_bytes(), bytes);
    drop(fresh);
    assert_eq!(budget.host_memory_bytes(), 0);
    assert_eq!(budget.outstanding_reservations(), 0);
}

struct Witness {
    budget: ActivationBudget,
    drops: Arc<AtomicU64>,
    observed: Arc<AtomicU64>,
    panic_on_drop: bool,
}
impl Drop for Witness {
    fn drop(&mut self) {
        self.observed
            .store(self.budget.host_memory_bytes(), Ordering::SeqCst);
        self.drops.fetch_add(1, Ordering::SeqCst);
        assert!(self.budget.host_memory_bytes() >= Shared::<Self>::allocation_bytes().unwrap());
        assert!(!self.panic_on_drop, "streaming-shared-payload-drop");
    }
}
#[test]
fn native_streaming_shared_arc_concurrent_last_clones_drop_payload_once_before_refund() {
    let budget = budget(1024 * 1024);
    let other_budget = self::budget(1024 * 1024);
    let drops = Arc::new(AtomicU64::new(0));
    let observed = Arc::new(AtomicU64::new(0));
    let value = selected(
        Witness {
            budget: budget.clone(),
            drops: drops.clone(),
            observed: observed.clone(),
            panic_on_drop: false,
        },
        &budget,
    )
    .unwrap();
    let bytes = Shared::<Witness>::allocation_bytes().unwrap();
    let other = selected(AtomicU64::new(62), &other_budget).unwrap();
    let other_bytes = other_budget.host_memory_bytes();
    let clone = value.clone();
    let barrier = Arc::new(Barrier::new(3));
    let a = barrier.clone();
    let first = std::thread::spawn(move || {
        a.wait();
        drop(value);
    });
    let b = barrier.clone();
    let last = std::thread::spawn(move || {
        b.wait();
        drop(clone);
    });
    barrier.wait();
    first.join().unwrap();
    last.join().unwrap();
    assert_eq!(drops.load(Ordering::SeqCst), 1);
    assert_eq!(observed.load(Ordering::SeqCst), bytes);
    assert_eq!(budget.host_memory_bytes(), 0);
    assert_eq!(budget.outstanding_reservations(), 0);
    assert_eq!(other_budget.host_memory_bytes(), other_bytes);
    assert_eq!(other.load(Ordering::SeqCst), 62);
    drop(other);
    assert_eq!(other_budget.host_memory_bytes(), 0);
}

#[test]
fn native_streaming_shared_arc_payload_unwind_still_retires_its_original_owner() {
    let budget = budget(1024 * 1024);
    let drops = Arc::new(AtomicU64::new(0));
    let observed = Arc::new(AtomicU64::new(0));
    let value = selected(
        Witness {
            budget: budget.clone(),
            drops: drops.clone(),
            observed: observed.clone(),
            panic_on_drop: true,
        },
        &budget,
    )
    .unwrap();
    let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| drop(value)));
    assert!(result.is_err());
    assert_eq!(drops.load(Ordering::SeqCst), 1);
    assert_eq!(
        observed.load(Ordering::SeqCst),
        Shared::<Witness>::allocation_bytes().unwrap()
    );
    assert_eq!(budget.host_memory_bytes(), 0);
    assert_eq!(budget.outstanding_reservations(), 0);
}
