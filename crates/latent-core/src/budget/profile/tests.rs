use super::*;
use crate::ActivationBudget;
use std::time::{Duration, Instant};

fn request() -> ResourceBudget {
    ResourceBudget {
        cpu_fuel: 100,
        memory_bytes: 1024,
        wall_time_limit_millis: Some(500),
        child_calls: 8,
        outbound_requests: 10,
        state_read_bytes: 0,
        state_write_bytes: 0,
        blob_read_bytes: 4096,
        blob_write_bytes: 8192,
        log_bytes: 128,
        effect_count: 0,
    }
}

#[test]
fn phase3_is_explicit_and_intersects_each_enabled_counter_without_enabling_state() {
    let requested = request();
    assert!(BudgetProfile::Phase1
        .effective(&requested, &requested, &requested)
        .is_err());
    let mut ceiling = requested.clone();
    ceiling.child_calls = 3;
    ceiling.outbound_requests = 0;
    ceiling.blob_read_bytes = 12;
    ceiling.blob_write_bytes = 0;
    let actual = BudgetProfile::Phase3
        .effective(&requested, &ceiling, &requested)
        .unwrap();
    assert_eq!(
        (
            actual.child_calls,
            actual.outbound_requests,
            actual.blob_read_bytes,
            actual.blob_write_bytes
        ),
        (3, 0, 12, 0)
    );
    for dimension in [
        BudgetDimension::StateReadBytes,
        BudgetDimension::StateWriteBytes,
        BudgetDimension::EffectCount,
    ] {
        let mut unsupported = requested.clone();
        match dimension {
            BudgetDimension::StateReadBytes => unsupported.state_read_bytes = 1,
            BudgetDimension::StateWriteBytes => unsupported.state_write_bytes = 1,
            _ => unsupported.effect_count = 1,
        }
        assert!(BudgetProfile::Phase3
            .effective(&unsupported, &ceiling, &requested)
            .is_err());
    }
}

#[test]
fn phase3_preserves_incoming_monotonic_time_despite_wall_clock_regression() {
    let now = Instant::now();
    let requested = request();
    let incoming = IncomingDeadline::new(now + Duration::from_millis(100), 999_999);
    let grant = EffectiveActivationBudget::admit_profile_with_deadline_at(
        BudgetProfile::Phase3,
        &requested,
        &requested,
        &requested,
        &incoming,
        ClockSample::new(1, now),
    )
    .unwrap();
    assert_eq!(grant.deadline.monotonic(), Some(incoming.monotonic()));
    assert_eq!(grant.budget, requested);
    let mut zero = requested.clone();
    zero.wall_time_limit_millis = Some(0);
    assert!(EffectiveActivationBudget::admit_profile_with_deadline_at(
        BudgetProfile::Phase3,
        &zero,
        &requested,
        &requested,
        &incoming,
        ClockSample::new(1, now)
    )
    .is_err());
}

#[test]
fn phase3_finalization_keeps_live_reservations_until_the_real_owner_retires() {
    let now = Instant::now();
    let requested = request();
    let grant = EffectiveActivationBudget::admit_profile_at(
        BudgetProfile::Phase3,
        &requested,
        &requested,
        &requested,
        None,
        ClockSample::new(1000, now),
    )
    .unwrap();
    let budget = ActivationBudget::with_profile(grant, BudgetProfile::Phase3).unwrap();
    budget
        .consume(BudgetDimension::OutboundRequests, 2)
        .unwrap();
    let pending = budget
        .reserve_group(&[
            (BudgetDimension::OutboundRequests, 3),
            (BudgetDimension::BlobReadBytes, 100),
        ])
        .unwrap();
    let single = budget
        .reserve(BudgetDimension::BlobWriteBytes, 200)
        .unwrap();
    assert_eq!(budget.remaining_at(now).outbound_requests, 5);
    let finalized = budget.finalize_at(None, now);
    assert_eq!(finalized.consumption().outbound_requests, 5);
    assert_eq!(finalized.consumption().blob_read_bytes, 100);
    assert_eq!(budget.outstanding_reservations(), 2);
    assert_eq!(budget.remaining_at(now).cpu_fuel, 0);
    assert_eq!(budget.remaining_at(now).child_calls, 0);
    assert!(budget
        .consume(BudgetDimension::OutboundRequests, 1)
        .is_err());
    pending.refund().unwrap();
    assert_eq!(budget.outstanding_reservations(), 1);
    single.commit().unwrap();
    assert_eq!(budget.outstanding_reservations(), 0);
    assert_eq!(budget.finalize_at(None, now), finalized);
}

#[test]
fn phase3_reports_cannot_invent_host_owned_io_or_future_state_usage() {
    let requested = request();
    let now = Instant::now();
    let grant = EffectiveActivationBudget::admit_profile_at(
        BudgetProfile::Phase3,
        &requested,
        &requested,
        &requested,
        None,
        ClockSample::new(1000, now),
    )
    .unwrap();
    let budget = ActivationBudget::with_profile(grant, BudgetProfile::Phase3).unwrap();
    let report = BudgetConsumption {
        outbound_requests: 7,
        blob_read_bytes: 100,
        ..BudgetConsumption::default()
    };
    let finalized = budget.finalize_at(Some(&report), now);
    assert!(finalized.violation().is_none());
    assert_eq!(finalized.consumption().outbound_requests, 0);
    assert_eq!(finalized.consumption().blob_read_bytes, 0);
    let invalid = BudgetConsumption {
        state_read_bytes: 1,
        ..BudgetConsumption::default()
    };
    assert!(BudgetProfile::Phase3
        .validate_report(&invalid, &requested)
        .is_err());
}
