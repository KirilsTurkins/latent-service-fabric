use super::*;
use std::sync::{atomic::AtomicBool, Barrier};

struct Payload {
    budget: ActivationBudget,
    dropped: Arc<AtomicBool>,
    charged: u64,
    panic: bool,
}
impl Drop for Payload {
    fn drop(&mut self) {
        // The original allocation and its implicit Weak still exist here.
        assert_eq!(self.budget.host_memory_bytes(), self.charged);
        self.dropped
            .store(true, std::sync::atomic::Ordering::Release);
        assert!(!self.panic, "selected payload unwind");
    }
}

#[test]
fn preparation_prepays_both_padded_headers_and_rolls_back_without_observation() {
    #[repr(align(128))]
    struct Aligned([u8; 129]);
    let runtime = super::super::tests::runtime();
    let budget = runtime.inner.budget.clone();
    drop(runtime);
    let bytes = Shared::<Aligned>::allocation_bytes().unwrap();
    let expected = 384
        + ALLOCATION_BOOKKEEPING
        + Layout::new::<[AtomicUsize; 2]>()
            .extend(Layout::new::<Charge>())
            .unwrap()
            .0
            .pad_to_align()
            .size()
        + ALLOCATION_BOOKKEEPING;
    assert_eq!(bytes, expected as u64);
    let observed_at = std::time::Instant::now();
    let before = budget.snapshot_at(observed_at);
    let count = budget.outstanding_reservations();
    let prepared = Shared::<Aligned>::reserve(&budget).unwrap();
    assert_eq!(budget.host_memory_bytes(), bytes);
    assert_eq!(budget.outstanding_reservations(), count + 1);
    assert_eq!(budget.snapshot_at(observed_at), before);
    drop(prepared);
    assert_eq!(budget.host_memory_bytes(), 0);
    assert_eq!(budget.outstanding_reservations(), count);
    assert_eq!(budget.snapshot_at(observed_at), before);
    let value = Shared::<Aligned>::reserve(&budget)
        .unwrap()
        .allocate(Aligned([7; 129]));
    assert_eq!(value.0[128], 7);
    assert_eq!(budget.host_memory_bytes(), bytes);
    drop(value);
    assert_eq!(budget.host_memory_bytes(), 0);
}

#[test]
fn concurrent_last_strong_and_weak_drop_keep_both_headers_paid() {
    let runtime = super::super::tests::runtime();
    let budget = runtime.inner.budget.clone();
    drop(runtime);
    let charged = Shared::<Payload>::allocation_bytes().unwrap();
    let dropped = Arc::new(AtomicBool::new(false));
    let shared = Shared::<Payload>::reserve(&budget)
        .unwrap()
        .allocate(Payload {
            budget: budget.clone(),
            dropped: dropped.clone(),
            charged,
            panic: false,
        });
    let second = shared.clone();
    let weak = shared.downgrade();
    let last_weak = weak.clone();
    let barrier = Arc::new(Barrier::new(3));
    std::thread::scope(|scope| {
        for owner in [shared, second] {
            let barrier = barrier.clone();
            scope.spawn(move || {
                barrier.wait();
                drop(owner);
            });
        }
        barrier.wait();
        drop(weak);
    });
    assert!(dropped.load(std::sync::atomic::Ordering::Acquire));
    assert!(last_weak.upgrade().is_none());
    assert_eq!(budget.host_memory_bytes(), charged);
    assert_eq!(budget.outstanding_reservations(), 1);
    std::thread::spawn(move || drop(last_weak)).join().unwrap();
    assert_eq!(budget.host_memory_bytes(), 0);
    assert_eq!(budget.outstanding_reservations(), 0);
    assert!(
        budget
            .snapshot_at(std::time::Instant::now())
            .peak_memory_bytes
            >= charged
    );
}

#[test]
fn payload_unwind_still_retires_both_headers_before_refund() {
    let runtime = super::super::tests::runtime();
    let budget = runtime.inner.budget.clone();
    drop(runtime);
    let charged = Shared::<Payload>::allocation_bytes().unwrap();
    let dropped = Arc::new(AtomicBool::new(false));
    let shared = Shared::<Payload>::reserve(&budget)
        .unwrap()
        .allocate(Payload {
            budget: budget.clone(),
            dropped: dropped.clone(),
            charged,
            panic: true,
        });
    let weak = shared.downgrade();
    let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| drop(shared)));
    assert!(result.is_err());
    assert!(dropped.load(std::sync::atomic::Ordering::Acquire));
    assert!(weak.upgrade().is_none());
    assert_eq!(budget.host_memory_bytes(), charged);
    drop(weak);
    assert_eq!(budget.host_memory_bytes(), 0);
    assert_eq!(budget.outstanding_reservations(), 0);
}

#[test]
fn concurrent_last_strong_and_last_weak_refund_exactly_once() {
    let runtime = super::super::tests::runtime();
    let budget = runtime.inner.budget.clone();
    drop(runtime);
    let charged = Shared::<Payload>::allocation_bytes().unwrap();
    let dropped = Arc::new(AtomicBool::new(false));
    let shared = Shared::<Payload>::reserve(&budget)
        .unwrap()
        .allocate(Payload {
            budget: budget.clone(),
            dropped: dropped.clone(),
            charged,
            panic: false,
        });
    let weak = shared.downgrade();
    let barrier = Arc::new(Barrier::new(3));
    std::thread::scope(|scope| {
        let strong_barrier = barrier.clone();
        scope.spawn(move || {
            strong_barrier.wait();
            drop(shared);
        });
        let weak_barrier = barrier.clone();
        scope.spawn(move || {
            weak_barrier.wait();
            drop(weak);
        });
        barrier.wait();
    });
    assert!(dropped.load(std::sync::atomic::Ordering::Acquire));
    assert_eq!(budget.host_memory_bytes(), 0);
    assert_eq!(budget.outstanding_reservations(), 0);
}
