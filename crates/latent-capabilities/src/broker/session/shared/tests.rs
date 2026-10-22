use super::*;
use latent_core::{BudgetProfile, ClockSample, EffectiveActivationBudget, ResourceBudget};
use std::sync::atomic::{AtomicBool, Ordering};

fn budget(profile: BudgetProfile) -> ActivationBudget {
    let limits = ResourceBudget {
        cpu_fuel: 1000,
        memory_bytes: 1024 * 1024,
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

struct Payload {
    budget: ActivationBudget,
    dropped: Arc<AtomicBool>,
    expected: u64,
}
impl Drop for Payload {
    fn drop(&mut self) {
        assert_eq!(self.budget.host_memory_bytes(), self.expected);
        self.dropped.store(true, Ordering::Release);
        panic!("selected payload unwind");
    }
}

#[test]
fn original_session_native_optional_billing_and_unwind_keep_actual_weak_storage_paid() {
    for profile in [BudgetProfile::Phase1, BudgetProfile::Phase3] {
        let budget = budget(profile);
        let dropped = Arc::new(AtomicBool::new(false));
        let expected = if profile.supports_descendants() {
            Shared::<Payload>::allocation_bytes().unwrap()
        } else {
            0
        };
        let shared = Shared::<Payload>::reserve(&budget)
            .unwrap()
            .allocate(Payload {
                budget: budget.clone(),
                dropped: dropped.clone(),
                expected,
            });
        // Legacy mode creates no auxiliary billing Arc, including its clones.
        assert_eq!(shared.billing.0.is_some(), profile.supports_descendants());
        let weak = shared.downgrade();
        let second = weak.clone();
        assert_eq!(weak.billing.0.is_some(), profile.supports_descendants());
        let outcome = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| drop(shared)));
        assert!(outcome.is_err());
        assert!(dropped.load(Ordering::Acquire));
        assert!(weak.upgrade().is_none());
        assert!(second.upgrade().is_none());
        assert_eq!(budget.host_memory_bytes(), expected);
        drop(weak);
        assert_eq!(budget.host_memory_bytes(), expected);
        std::thread::spawn(move || drop(second)).join().unwrap();
        assert_eq!(budget.host_memory_bytes(), 0);
        assert_eq!(budget.outstanding_reservations(), 0);
    }
}
