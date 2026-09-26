use super::*;

#[test]
fn native_fuel_adjustments_do_not_double_charge_child_work_or_refunds() {
    struct Open;
    impl latent_core::BudgetCancellationProbe for Open {
        fn is_cancelled(&self) -> bool {
            false
        }
        fn cancelled(&self) -> latent_core::BoxFuture<'_, ()> {
            Box::pin(std::future::pending())
        }
        fn mark_terminal(&self) {}
    }
    let mut request = request();
    request.budget.child_calls = 4;
    request.activation.budget = request.budget.clone();
    let clock = Clock::new();
    let sample = ClockSample::new(1000, clock.admitted);
    let grant = EffectiveActivationBudget::admit_profile_at(
        BudgetProfile::Phase3,
        &request.budget,
        &request.budget,
        &request.budget,
        Some(1050),
        sample,
    )
    .unwrap();
    let budget = ActivationBudget::with_profile(grant, BudgetProfile::Phase3).unwrap();
    budget
        .enable_descendants(
            latent_core::DelegationLimits::default(),
            std::sync::Arc::new(Open),
        )
        .unwrap();
    let cancellation = Cancellation {
        id: request.activation.activation_id.clone(),
        budget: Some(budget.clone()),
        deadline: None,
    };
    let mut accounting = InvocationAccounting::new(&request, &cancellation, &clock).unwrap();
    accounting.observe_runtime(90, 32).unwrap();
    let mut child_grant = request.budget.clone();
    child_grant.cpu_fuel = 30;
    child_grant.memory_bytes = 256;
    child_grant.child_calls = 0;
    child_grant.log_bytes = 0;
    let child = budget
        .delegate_at(&child_grant, &child_grant, &child_grant, None, sample)
        .unwrap();
    let child_grant = child.grant();
    let child = child
        .accept(&child_grant, std::sync::Arc::new(Open), sample.monotonic())
        .unwrap();
    assert_eq!(budget.remaining_at(sample.monotonic()).cpu_fuel, 60);
    accounting.reset_fuel_watermark(60);
    accounting.observe_runtime(55, 64).unwrap();
    child.accounting().observe_runtime_usage(10, 128).unwrap();
    let _ = child.finish(None, sample.monotonic());
    assert_eq!(budget.remaining_at(sample.monotonic()).cpu_fuel, 75);
    accounting.reset_fuel_watermark(75);
    accounting.observe_runtime(70, 64).unwrap();
    assert_eq!(accounting.native_fuel_consumed(70), 20);
    let final_report = budget.finalize_at(
        Some(&BudgetConsumption {
            cpu_fuel: 20,
            peak_memory_bytes: 64,
            ..Default::default()
        }),
        sample.monotonic(),
    );
    assert_eq!(final_report.consumption().cpu_fuel, 30);
    assert_eq!(final_report.consumption().child_calls, 1);
}

#[test]
fn invalid_native_observations_leave_both_watermarks_and_ledger_unchanged() {
    let request = request();
    let clock = Clock::new();
    let cancellation = cancellation(&request, &clock);
    let mut accounting = InvocationAccounting::new(&request, &cancellation, &clock).unwrap();
    accounting.observe_runtime(90, 32).unwrap();
    let before = accounting.budget.snapshot_at(clock.admitted);
    for (fuel, peak, expected) in [
        (91, 2048, PlatformErrorCode::InvalidArgument),
        (80, 2048, PlatformErrorCode::ResourceExhausted),
    ] {
        assert_eq!(
            accounting.observe_runtime(fuel, peak).unwrap_err().code,
            expected
        );
        assert_eq!(accounting.last_remaining_fuel, 90);
        assert_eq!(accounting.confirmed_peak_memory, 32);
        assert_eq!(accounting.budget.snapshot_at(clock.admitted), before);
    }
    accounting.observe_runtime(80, 64).unwrap();
    accounting.observe_runtime(80, 64).unwrap();
    let after = accounting.budget.snapshot_at(clock.admitted);
    assert_eq!((after.cpu_fuel, after.peak_memory_bytes), (20, 64));
}

#[test]
fn competing_fuel_charge_cannot_publish_the_failed_observations_memory_peak() {
    let request = request();
    let clock = Clock::new();
    let cancellation = cancellation(&request, &clock);
    let mut accounting = InvocationAccounting::new(&request, &cancellation, &clock).unwrap();
    accounting.observe_runtime(90, 32).unwrap();
    accounting.budget.consume_cpu_fuel(85).unwrap();
    let before = accounting.budget.snapshot_at(clock.admitted);
    assert_eq!(
        accounting.observe_runtime(80, 64).unwrap_err().code,
        PlatformErrorCode::ResourceExhausted
    );
    assert_eq!(accounting.budget.snapshot_at(clock.admitted), before);
    assert_eq!(accounting.last_remaining_fuel, 90);
    assert_eq!(accounting.confirmed_peak_memory, 32);
    // A smaller confirmed delta still fits and charges once; the failed
    // observation did not falsely advance the local fuel watermark.
    accounting.observe_runtime(85, 48).unwrap();
    let after = accounting.budget.snapshot_at(clock.admitted);
    assert_eq!((after.cpu_fuel, after.peak_memory_bytes), (100, 48));
}

#[test]
fn finalized_ledger_cannot_advance_either_local_watermark_even_for_zero_fuel() {
    let request = request();
    let clock = Clock::new();
    let cancellation = cancellation(&request, &clock);
    let mut accounting = InvocationAccounting::new(&request, &cancellation, &clock).unwrap();
    accounting.observe_runtime(90, 32).unwrap();
    let finalized = accounting.budget.finalize_at(None, clock.admitted);
    for (fuel, peak) in [(80, 64), (90, 64), (90, 0)] {
        assert!(accounting.observe_runtime(fuel, peak).is_err());
        assert_eq!(accounting.last_remaining_fuel, 90);
        assert_eq!(accounting.confirmed_peak_memory, 32);
        assert_eq!(accounting.budget.finalization().unwrap(), finalized);
    }
}

#[test]
fn repeated_lower_memory_observations_keep_the_confirmed_peak_and_log_reservation() {
    let request = request();
    let clock = Clock::new();
    let cancellation = cancellation(&request, &clock);
    let mut accounting = InvocationAccounting::new(&request, &cancellation, &clock).unwrap();
    let reservation = accounting.budget.reserve_log_bytes(11).unwrap();
    accounting.observe_runtime(90, 64).unwrap();
    accounting.observe_runtime(90, 32).unwrap();
    assert_eq!(accounting.confirmed_peak_memory, 64);
    assert_eq!(accounting.budget.outstanding_reservations(), 1);
    assert_eq!(accounting.budget.remaining_at(clock.admitted).log_bytes, 89);
    drop(reservation);
    assert_eq!(accounting.budget.outstanding_reservations(), 0);
    let finalization = accounting.budget.finalize_at(None, clock.admitted);
    assert_eq!(finalization.consumption().cpu_fuel, 10);
    assert_eq!(finalization.consumption().peak_memory_bytes, 64);
    assert_eq!(finalization.consumption().log_bytes, 0);
}
