use super::*;
use std::sync::atomic::{AtomicBool, AtomicUsize};
mod audit;
mod fixture;
use fixture::*;

#[test]
fn clock_pending_binding_and_work_keep_one_owned_reservation_until_one_commit() {
    for clock in [HostClock::Monotonic, HostClock::Wall] {
        for hold_at in [1, 2] {
            let f = ClockFixture::new(clock, CapabilityBrokerLimits::default(), false);
            let (request, control) = f.request();
            let session = f.base.session(&request, &control);
            let before = f.base.broker.snapshot();
            f.fence.hold_at.store(hold_at, Ordering::SeqCst);
            let timer = Timer::new();
            let mut future = Box::pin(session.begin_host_clock(clock, &timer));
            pending(future.as_mut());
            let retained = f.base.broker.snapshot();
            assert_eq!(retained.handles, before.handles + 1);
            assert_eq!(retained.calls, before.calls + usize::from(hold_at == 2));
            assert_eq!(
                control.budget.outstanding_reservations(),
                u64::from(hold_at == 2)
            );
            assert_eq!(session.observer().live_calls(), 1);
            for _ in 0..3 {
                timer.advance(Duration::from_millis(10));
                pending(future.as_mut());
                assert_eq!(f.base.broker.snapshot(), retained);
                assert_eq!(
                    control.budget.outstanding_reservations(),
                    u64::from(hold_at == 2)
                );
            }
            f.fence.hold_at.store(0, Ordering::SeqCst);
            timer.advance(Duration::from_millis(10));
            let call = ready(future).unwrap();
            assert_eq!(control.budget.outstanding_reservations(), 0);
            assert_eq!(
                control
                    .budget
                    .remaining_at(std::time::Instant::now())
                    .cpu_fuel,
                request.budget.cpu_fuel - 100
            );
            assert_eq!(session.observer().live_calls(), 1);
            assert_eq!(timer.registrations.load(Ordering::SeqCst), 0);
            drop(call);
            f.idle(&session, before);
        }
    }
}

#[test]
fn clock_wait_is_one_window_across_binding_and_work_and_drops_refundable_owners() {
    let f = ClockFixture::new(HostClock::Wall, CapabilityBrokerLimits::default(), false);
    let (request, control) = f.request();
    let session = f.base.session(&request, &control);
    let before = f.base.broker.snapshot();
    f.fence.hold_at.store(1, Ordering::SeqCst);
    let timer = Timer::new();
    let mut future = Box::pin(session.begin_host_clock(f.clock, &timer));
    pending(future.as_mut());
    // Admit the same binding after four seconds, then stop only work admission.
    f.fence.hold_at.store(3, Ordering::SeqCst);
    timer.advance(Duration::from_secs(4));
    pending(future.as_mut());
    assert_eq!(control.budget.outstanding_reservations(), 1);
    timer.advance(Duration::from_secs(1));
    let error = ready(future).err().unwrap();
    assert_eq!(error, busy_error());
    assert_eq!(f.fence.calls.load(Ordering::SeqCst), 3);
    assert_eq!(control.budget.outstanding_reservations(), 0);
    assert_eq!(
        control
            .budget
            .remaining_at(std::time::Instant::now())
            .cpu_fuel,
        request.budget.cpu_fuel
    );
    f.idle(&session, before);
}

#[test]
fn clock_pending_drop_cancellation_and_closure_release_every_owner() {
    for hold_at in [1, 2] {
        for stop in [0, 1, 2] {
            let f = ClockFixture::new(HostClock::Wall, CapabilityBrokerLimits::default(), false);
            let (request, control) = f.request();
            let session = f.base.session(&request, &control);
            let before = f.base.broker.snapshot();
            let timer = Timer::new();
            f.fence.hold_at.store(hold_at, Ordering::SeqCst);
            let mut future = Box::pin(session.begin_host_clock(f.clock, &timer));
            pending(future.as_mut());
            if stop == 0 {
                drop(future);
            } else {
                if stop == 1 {
                    control.probe.0.store(true, Ordering::SeqCst);
                } else {
                    session.close();
                }
                timer.advance(Duration::from_millis(10));
                assert_eq!(
                    ready(future).err().unwrap().code,
                    PlatformErrorCode::Cancelled
                );
            }
            assert_eq!(timer.registrations.load(Ordering::SeqCst), 0);
            assert_eq!(control.budget.outstanding_reservations(), 0);
            f.idle(&session, before);
        }
    }
}

#[test]
fn clock_waiting_capacity_is_bounded_and_non_currentness_busy_is_immediate() {
    let limits = CapabilityBrokerLimits {
        maximum_calls_per_session: 1,
        ..Default::default()
    };
    let f = ClockFixture::new(HostClock::Wall, limits, false);
    let (request, control) = f.request();
    let session = f.base.session(&request, &control);
    let before = f.base.broker.snapshot();
    let timer = Timer::new();
    f.fence.hold_at.store(1, Ordering::SeqCst);
    let mut first = Box::pin(session.begin_host_clock(f.clock, &timer));
    pending(first.as_mut());
    let failure = ready(session.begin_host_clock(f.clock, &timer))
        .err()
        .unwrap();
    assert_eq!(failure.code, PlatformErrorCode::ResourceExhausted);
    assert_eq!(timer.registrations.load(Ordering::SeqCst), 1);
    drop(first);
    f.idle(&session, before);
    *f.fence.failure.lock().unwrap() = Some(busy());
    let waits = timer.waits.load(Ordering::SeqCst);
    assert_eq!(
        ready(session.begin_host_clock(f.clock, &timer))
            .err()
            .unwrap(),
        busy()
    );
    assert_eq!(timer.waits.load(Ordering::SeqCst), waits);
    f.idle(&session, before);
}

#[test]
fn clock_fences_returning_busy_after_callback_are_never_reentered() {
    for hold_at in [1, 2] {
        let f = ClockFixture::new(HostClock::Wall, CapabilityBrokerLimits::default(), false);
        let (request, control) = f.request();
        let session = f.base.session(&request, &control);
        let before = f.base.broker.snapshot();
        let timer = Timer::new();
        f.fence.hold_at.store(hold_at, Ordering::SeqCst);
        f.fence.post_commit.store(true, Ordering::SeqCst);
        assert_eq!(
            ready(session.begin_host_clock(f.clock, &timer))
                .err()
                .unwrap(),
            busy_error()
        );
        assert_eq!(timer.waits.load(Ordering::SeqCst), 0);
        assert_eq!(f.fence.calls.load(Ordering::SeqCst), hold_at);
        assert_eq!(control.budget.outstanding_reservations(), 0);
        assert_eq!(
            control
                .budget
                .remaining_at(std::time::Instant::now())
                .cpu_fuel,
            request.budget.cpu_fuel - if hold_at == 2 { 100 } else { 0 }
        );
        f.idle(&session, before);
    }
}

#[test]
fn clock_wait_does_not_refresh_revoked_policy_or_allow_required_audit() {
    let f = ClockFixture::new(HostClock::Wall, CapabilityBrokerLimits::default(), false);
    let (request, control) = f.request();
    let session = f.base.session(&request, &control);
    let before = f.base.broker.snapshot();
    let timer = Timer::new();
    f.fence.hold_at.store(2, Ordering::SeqCst);
    let mut future = Box::pin(session.begin_host_clock(f.clock, &timer));
    pending(future.as_mut());
    f.revoke();
    f.fence.hold_at.store(0, Ordering::SeqCst);
    timer.advance(Duration::from_millis(10));
    assert_eq!(
        ready(future).err().unwrap().code,
        PlatformErrorCode::PermissionDenied
    );
    assert_eq!(control.budget.outstanding_reservations(), 0);
    f.idle(&session, before);

    let f = ClockFixture::new(HostClock::Wall, CapabilityBrokerLimits::default(), true);
    let (request, control) = f.request();
    let session = f.base.session(&request, &control);
    let before = f.base.broker.snapshot();
    let failure = ready(session.begin_host_clock(f.clock, &timer))
        .err()
        .unwrap();
    assert_eq!(failure.message, "capability-required-audit-path");
    assert_eq!(control.budget.outstanding_reservations(), 0);
    f.idle(&session, before);
}

#[test]
fn clock_wait_counts_elapsed_deadline_once_and_denies_exact_expiry() {
    use latent_core::{ActivationBudget, ClockSample, EffectiveActivationBudget};
    for elapsed in [60, 100] {
        let start = ClockSample::system_now();
        let clock = Arc::new(ManualClock(std::sync::Mutex::new(start)));
        let f = ClockFixture::from_base(
            Fixture::with_activation_clock(clock.clone()),
            HostClock::Wall,
            false,
        );
        let (mut request, mut control) = f.request();
        request.budget.wall_time_limit_millis = Some(100);
        request.activation.budget = request.budget.clone();
        control.budget = ActivationBudget::new(
            EffectiveActivationBudget::admit_at(
                &request.budget,
                &request.budget,
                &request.budget,
                None,
                start,
            )
            .unwrap(),
        );
        request.activation.deadline_unix_millis = control.budget.deadline().unix_millis();
        let session = f.base.session(&request, &control);
        let before = f.base.broker.snapshot();
        let timer = Timer::new();
        *timer.now.lock().unwrap() = start.monotonic();
        f.fence.hold_at.store(1, Ordering::SeqCst);
        let mut future = Box::pin(session.begin_host_clock(f.clock, &timer));
        pending(future.as_mut());
        *clock.0.lock().unwrap() = ClockSample::new(
            start.unix_millis() + elapsed,
            start.monotonic() + Duration::from_millis(elapsed),
        );
        timer.advance(Duration::from_millis(elapsed));
        f.fence.hold_at.store(0, Ordering::SeqCst);
        let result = ready(future);
        if elapsed == 60 {
            let call = result.unwrap();
            assert_eq!(
                call.deadline(),
                start.monotonic() + Duration::from_millis(100)
            );
            assert_eq!(
                control
                    .budget
                    .remaining_at(start.monotonic() + Duration::from_millis(60))
                    .cpu_fuel,
                request.budget.cpu_fuel - 100
            );
            drop(call);
        } else {
            assert_eq!(
                result.err().unwrap().code,
                PlatformErrorCode::DeadlineExceeded
            );
            assert_eq!(f.fence.calls.load(Ordering::SeqCst), 1);
        }
        assert_eq!(control.budget.outstanding_reservations(), 0);
        f.idle(&session, before);
    }
}

#[test]
fn pending_clock_rows_already_consume_the_original_per_session_handle_limit() {
    let f = ClockFixture::new(
        HostClock::Wall,
        CapabilityBrokerLimits {
            maximum_handles_per_session: 1,
            ..Default::default()
        },
        false,
    );
    let (request, control) = f.request();
    let session = f.base.session(&request, &control);
    let before = f.base.broker.snapshot();
    let timer = Timer::new();
    f.fence.hold_at.store(1, Ordering::SeqCst);
    let mut future = Box::pin(session.begin_host_clock(f.clock, &timer));
    pending(future.as_mut());
    assert_eq!(session.observer().retained_handles(), 1);
    let error = session
        .bind(
            f.clock.capability(),
            f.clock.operation(),
            ResourceTarget::Clock,
        )
        .unwrap_err();
    assert_eq!(error.code, PlatformErrorCode::ResourceExhausted);
    assert_eq!(
        ready(session.begin_host_clock(f.clock, &timer))
            .err()
            .unwrap()
            .code,
        PlatformErrorCode::ResourceExhausted
    );
    f.fence.hold_at.store(0, Ordering::SeqCst);
    timer.advance(Duration::from_millis(10));
    drop(ready(future).unwrap());
    f.idle(&session, before);
}

#[test]
fn pending_clock_slot_collision_denies_without_clearing_the_foreign_live_row() {
    let f = ClockFixture::new(HostClock::Wall, CapabilityBrokerLimits::default(), false);
    let (request, control) = f.request();
    let session = f.base.session(&request, &control);
    let before = f.base.broker.snapshot();
    let timer = Timer::new();
    f.fence.hold_at.store(1, Ordering::SeqCst);
    let mut pending_clock = Box::pin(session.begin_host_clock(f.clock, &timer));
    pending(pending_clock.as_mut());
    assert_eq!(session.observer().retained_handles(), 1);
    assert!(session.core.state.lock().unwrap().slots[0].is_none());

    // A separate legacy binding publishes the same previously empty slot.
    // The pending clock owns a different incarnation, never this live row.
    f.fence.hold_at.store(0, Ordering::SeqCst);
    let foreign = session
        .bind(
            f.clock.capability(),
            f.clock.operation(),
            ResourceTarget::Clock,
        )
        .unwrap();
    assert_eq!(foreign.wire_parts().0, 0);
    assert_eq!(session.observer().retained_handles(), 2);
    timer.advance(Duration::from_millis(10));
    assert_eq!(
        ready(pending_clock).err().unwrap().code,
        PlatformErrorCode::PermissionDenied
    );
    assert_eq!(session.observer().retained_handles(), 1);
    assert_eq!(session.observer().live_calls(), 0);
    assert_eq!(timer.registrations.load(Ordering::SeqCst), 0);
    assert_eq!(control.budget.outstanding_reservations(), 0);
    assert_eq!(f.base.broker.snapshot().handles, before.handles + 1);

    let call = session
        .dispatch(
            foreign,
            f.clock.operation(),
            ResourceTarget::Clock,
            b"",
            CapabilityCallCost::new(8)
                .with_charge(latent_core::BudgetDimension::CpuFuel, 100)
                .unwrap(),
            |call| call,
        )
        .unwrap();
    call.require_host_mode().unwrap();
    drop(call);
    session.close_handle(foreign).unwrap();
    f.idle(&session, before);
}
