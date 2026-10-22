//! These controls use the shipping retained directory and original ledger.
use super::*;
use latent_core::{
    BudgetDimension, BudgetError, ClockSample, EffectiveActivationBudget, ResourceBudget,
};
use std::sync::{
    atomic::{AtomicU64, Ordering},
    Arc,
};

fn budget(memory: u64, profile: BudgetProfile) -> ActivationBudget {
    let limits = ResourceBudget {
        cpu_fuel: 1_000_000_000,
        memory_bytes: memory,
        wall_time_limit_millis: Some(5000),
        child_calls: 0,
        outbound_requests: 0,
        state_read_bytes: 0,
        state_write_bytes: 0,
        blob_read_bytes: 0,
        blob_write_bytes: 0,
        log_bytes: 0,
        effect_count: 0,
    };
    let grant = EffectiveActivationBudget::admit_profile_at(
        profile,
        &limits,
        &limits,
        &limits,
        None,
        ClockSample::system_now(),
    )
    .unwrap();
    ActivationBudget::with_profile(grant, profile).unwrap()
}
fn bytes<T>(capacity: usize) -> u64 {
    (Layout::array::<T>(capacity).unwrap().size() + ALLOCATION_BOOKKEEPING) as u64
}
fn peak(budget: &ActivationBudget) -> u64 {
    budget
        .snapshot_at(std::time::Instant::now())
        .peak_memory_bytes
}

#[test]
fn retained_capability_directory_growth_pays_exact_old_new_overlap_and_unused_capacity() {
    for profile in [BudgetProfile::Phase3, BudgetProfile::Phase4] {
        let budget = budget(1024, profile);
        let mut values = Retained::<u64>::new(&budget);
        assert_eq!(budget.host_memory_bytes(), 0);
        for value in 0..3 {
            values.prepare_one().unwrap();
            values.push_prepared(value);
        }
        assert_eq!(values.values, [0, 1, 2]);
        assert_eq!(values.values.capacity(), 4);
        assert_eq!(budget.host_memory_bytes(), bytes::<u64>(4));
        assert_eq!(budget.outstanding_reservations(), 1);
        assert_eq!(peak(&budget), bytes::<u64>(2) + bytes::<u64>(4));
        let address = values.values.as_ptr();
        values.prepare_one().unwrap();
        assert_eq!(values.values.as_ptr(), address);
        assert_eq!(budget.host_memory_bytes(), bytes::<u64>(4));
        // The unused fourth slot stays paid until the real backing is dropped.
        drop(values);
        assert_eq!(budget.host_memory_bytes(), 0);
        assert_eq!(budget.outstanding_reservations(), 0);
    }
}

#[test]
fn retained_capability_directory_refusal_keeps_original_error_contents_and_fresh_grant() {
    let limit = bytes::<u64>(1) + bytes::<u64>(2) - 1;
    let budget = budget(limit, BudgetProfile::Phase3);
    let mut values = Retained::<u64>::new(&budget);
    values.prepare_one().unwrap();
    values.push_prepared(42);
    let address = values.values.as_ptr();
    let error = values.prepare_one().unwrap_err();
    assert!(
        matches!(error.downcast_ref::<BudgetError>(), Some(BudgetError::Exhausted {
        dimension: BudgetDimension::MemoryBytes, limit: l, consumed: c, requested: r,
    }) if (*l, *c, *r) == (limit, bytes::<u64>(1), bytes::<u64>(2)))
    );
    assert_eq!(values.values, [42]);
    assert_eq!(values.values.as_ptr(), address);
    assert_eq!(values.values.capacity(), 1);
    assert_eq!(budget.host_memory_bytes(), bytes::<u64>(1));
    assert_eq!(peak(&budget), bytes::<u64>(1));
    drop(error);
    drop(values);
    let mut fresh = Retained::<u64>::new(&budget);
    fresh.prepare_one().unwrap();
    fresh.push_prepared(62);
    assert_eq!(fresh.values, [62]);
    drop(fresh);
    assert_eq!(budget.host_memory_bytes(), 0);
    assert_eq!(budget.outstanding_reservations(), 0);
}

struct Witness {
    budget: ActivationBudget,
    observed: Arc<AtomicU64>,
    panic_on_drop: bool,
}
impl Drop for Witness {
    fn drop(&mut self) {
        self.observed
            .store(self.budget.host_memory_bytes(), Ordering::SeqCst);
        assert!(self.budget.host_memory_bytes() >= bytes::<Self>(1));
        assert!(!self.panic_on_drop, "retained-directory-drop-witness");
    }
}
#[test]
fn retained_capability_directory_elements_die_before_refund_even_during_unwind() {
    for panic_on_drop in [false, true] {
        let budget = budget(4096, BudgetProfile::Phase3);
        let observed = Arc::new(AtomicU64::new(0));
        let mut values = Retained::<Witness>::new(&budget);
        values.prepare_one().unwrap();
        values.push_prepared(Witness {
            budget: budget.clone(),
            observed: observed.clone(),
            panic_on_drop,
        });
        let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| drop(values)));
        assert_eq!(result.is_err(), panic_on_drop);
        assert_eq!(observed.load(Ordering::SeqCst), bytes::<Witness>(1));
        assert_eq!(budget.host_memory_bytes(), 0);
        assert_eq!(budget.outstanding_reservations(), 0);
    }
}

#[test]
fn retained_capability_all_three_real_directories_bind_original_budget_across_replacement() {
    use crate::host::capabilities::HostCapabilities;
    let original = budget(1024 * 1024, BudgetProfile::Phase3);
    let other = budget(1024 * 1024, BudgetProfile::Phase3);
    let mut capabilities = HostCapabilities::new(None, &original);
    assert_eq!(original.host_memory_bytes(), 0);
    capabilities.prepare_lowering().unwrap();
    capabilities.prepare_secret_lowering().unwrap();
    capabilities.prepare_pool_lowering().unwrap();
    let retained = bytes::<latent_capabilities::broker::ProviderCall>(1)
        + bytes::<latent_capabilities::broker::secrets::SecretLowering>(1)
        + bytes::<latent_capabilities::broker::pools::PoolCall>(1);
    assert_eq!(original.host_memory_bytes(), retained);
    assert_eq!(original.outstanding_reservations(), 3);
    assert_eq!(other.host_memory_bytes(), 0);
    let mut replacement = HostCapabilities::new(None, &other);
    replacement.prepare_lowering().unwrap();
    let other_retained = other.host_memory_bytes();
    let old = std::mem::replace(&mut capabilities, replacement);
    assert_eq!(original.host_memory_bytes(), retained);
    drop(old);
    assert_eq!(original.host_memory_bytes(), 0);
    assert_eq!(other.host_memory_bytes(), other_retained);
    drop(capabilities);
    assert_eq!(other.host_memory_bytes(), 0);
    assert_eq!(other.outstanding_reservations(), 0);
}

#[test]
fn retained_capability_empty_zst_and_phase1_paths_preserve_lazy_behavior() {
    let selected = budget(1, BudgetProfile::Phase3);
    let mut zero = Retained::<()>::new(&selected);
    for _ in 0..16 {
        zero.prepare_one().unwrap();
        zero.push_prepared(());
    }
    assert_eq!(zero.values.len(), 16);
    assert_eq!(selected.host_memory_bytes(), 0);
    assert_eq!(selected.outstanding_reservations(), 0);
    let legacy = budget(1, BudgetProfile::Phase1);
    let mut values = Retained::<u64>::new(&legacy);
    for value in 0..16 {
        values.prepare_one().unwrap();
        values.push_prepared(value);
    }
    assert_eq!(values.values.len(), 16);
    assert_eq!(legacy.host_memory_bytes(), 0);
    assert_eq!(legacy.outstanding_reservations(), 0);
}
