use super::*;

fn budget(wall_time_limit_millis: Option<u64>) -> ResourceBudget {
    ResourceBudget {
        cpu_fuel: 100,
        memory_bytes: 200,
        wall_time_limit_millis,
        child_calls: 0,
        outbound_requests: 0,
        state_read_bytes: 0,
        state_write_bytes: 0,
        blob_read_bytes: 0,
        blob_write_bytes: 0,
        log_bytes: 16,
        effect_count: 0,
    }
}

#[test]
fn exact_incoming_survives_millisecond_boundary_and_wall_clock_changes() {
    let ingress = Instant::now();
    let expires = ingress + Duration::from_micros(1800);
    let incoming = IncomingDeadline::new(expires, 10_002);
    let admitted = ingress + Duration::from_micros(200);
    for unix in [0, 10_000, 10_001, 10_003, u64::MAX] {
        let grant = EffectiveActivationBudget::admit_with_deadline_at(
            &budget(Some(2)),
            &budget(None),
            &budget(None),
            &incoming,
            ClockSample::new(unix, admitted),
        )
        .unwrap();
        assert_eq!(grant.deadline.monotonic(), Some(expires));
        assert_eq!(grant.deadline.unix_millis(), Some(10_002));
        assert_eq!(
            grant.deadline.remaining_at(admitted),
            Some(Duration::from_micros(1600))
        );
        assert!(!grant
            .deadline
            .is_expired_at(expires.checked_sub(Duration::from_nanos(1)).unwrap()));
        assert!(grant.deadline.is_expired_at(expires));
    }
    let legacy = EffectiveActivationBudget::admit_at(
        &budget(Some(2)),
        &budget(None),
        &budget(None),
        Some(10_002),
        ClockSample::new(10_001, admitted),
    )
    .unwrap();
    assert_eq!(
        legacy.deadline.remaining_at(admitted),
        Some(Duration::from_millis(1))
    );
}

#[test]
fn each_relative_ceiling_is_anchored_to_this_admission_and_intersected_exactly() {
    let admitted = Instant::now();
    let incoming = IncomingDeadline::new(admitted + Duration::from_micros(1500), 999_999);
    for selected in 0..3 {
        let mut limits = [budget(None), budget(None), budget(None)];
        limits[selected].wall_time_limit_millis = Some(1);
        let grant = EffectiveActivationBudget::admit_with_deadline_at(
            &limits[0],
            &limits[1],
            &limits[2],
            &incoming,
            ClockSample::new(1000, admitted),
        )
        .unwrap();
        assert_eq!(
            grant.deadline.monotonic(),
            Some(admitted + Duration::from_millis(1))
        );
        assert_eq!(grant.deadline.unix_millis(), Some(1001));
        assert_eq!(grant.budget.wall_time_limit_millis, Some(1));
    }
}

#[test]
fn diagnostic_saturation_and_irrelevant_huge_ceiling_do_not_rewrite_timing() {
    let admitted = Instant::now();
    let incoming = IncomingDeadline::new(admitted + Duration::from_millis(2), 1);
    let large = EffectiveActivationBudget::admit_with_deadline_at(
        &budget(Some(u64::MAX)),
        &budget(None),
        &budget(None),
        &incoming,
        ClockSample::new(u64::MAX, admitted),
    )
    .unwrap();
    assert_eq!(large.deadline.monotonic(), Some(incoming.monotonic()));
    assert_eq!(large.deadline.unix_millis(), Some(1));
    let short = EffectiveActivationBudget::admit_with_deadline_at(
        &budget(Some(1)),
        &budget(None),
        &budget(None),
        &incoming,
        ClockSample::new(u64::MAX, admitted),
    )
    .unwrap();
    assert_eq!(
        short.deadline.monotonic(),
        Some(admitted + Duration::from_millis(1))
    );
    assert_eq!(short.deadline.unix_millis(), Some(u64::MAX));
}

#[test]
fn zero_relative_budget_and_expired_exact_deadline_remain_rejected() {
    let admitted = Instant::now();
    for expires in [
        admitted,
        admitted.checked_sub(Duration::from_nanos(1)).unwrap(),
    ] {
        assert!(matches!(
            EffectiveActivationBudget::admit_with_deadline_at(
                &budget(None),
                &budget(None),
                &budget(None),
                &IncomingDeadline::new(expires, u64::MAX),
                ClockSample::new(0, admitted),
            ),
            Err(BudgetError::DeadlineExceeded { .. })
        ));
    }
    assert!(matches!(
        EffectiveActivationBudget::admit_with_deadline_at(
            &budget(Some(0)),
            &budget(None),
            &budget(None),
            &IncomingDeadline::new(admitted + Duration::from_secs(1), 2000),
            ClockSample::new(1000, admitted),
        ),
        Err(BudgetError::DeadlineExceeded { .. })
    ));
}

#[test]
fn exact_deadline_does_not_bypass_budget_intersection_or_unsupported_dimensions() {
    let admitted = Instant::now();
    let incoming = IncomingDeadline::new(admitted + Duration::from_secs(1), 2000);
    let request = budget(None);
    let mut deployment = budget(None);
    deployment.cpu_fuel = 50;
    let mut node = budget(None);
    node.memory_bytes = 80;
    let grant = EffectiveActivationBudget::admit_with_deadline_at(
        &request,
        &deployment,
        &node,
        &incoming,
        ClockSample::new(1000, admitted),
    )
    .unwrap();
    assert_eq!(grant.budget.cpu_fuel, 50);
    assert_eq!(grant.budget.memory_bytes, 80);
    let mut unsupported = request;
    unsupported.child_calls = 1;
    assert!(matches!(
        EffectiveActivationBudget::admit_with_deadline_at(
            &unsupported,
            &deployment,
            &node,
            &incoming,
            ClockSample::new(1000, admitted),
        ),
        Err(BudgetError::UnsupportedRequestDimension { .. })
    ));
}
