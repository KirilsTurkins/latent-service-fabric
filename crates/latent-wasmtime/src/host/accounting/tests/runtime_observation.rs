use super::*;

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
