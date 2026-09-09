use std::sync::Mutex;

use latent_core::{ActivationClock, IncomingDeadline, SystemActivationClock};

use super::*;

struct TestClock {
    sample: ClockSample,
    now: Mutex<Instant>,
    samples: AtomicUsize,
    reads: AtomicUsize,
}

impl TestClock {
    fn new(sample: ClockSample) -> Self {
        Self {
            sample,
            now: Mutex::new(sample.monotonic()),
            samples: AtomicUsize::new(0),
            reads: AtomicUsize::new(0),
        }
    }

    fn advance(&self, amount: Duration) {
        let mut now = self.now.lock().unwrap();
        *now += amount;
    }
}

impl ActivationClock for TestClock {
    fn sample(&self) -> ClockSample {
        self.samples.fetch_add(1, Ordering::Relaxed);
        self.sample
    }

    fn monotonic_now(&self) -> Instant {
        self.reads.fetch_add(1, Ordering::Relaxed);
        *self.now.lock().unwrap()
    }
}

struct AdvancingPolicy {
    source: Arc<Source>,
    clock: Arc<TestClock>,
    work: Duration,
}

impl RevisionPolicySource for AdvancingPolicy {
    fn admission_policy(
        &self,
        supplied: &ResolvedRevision,
    ) -> Result<RevisionAdmissionPolicy, PlatformError> {
        let result = self.source.admission_policy(supplied);
        self.clock.advance(self.work);
        result
    }
}

fn short_budget_harness() -> Harness {
    let mut policy = node_policy();
    policy.deadline.estimated_service_time_millis = 1;
    policy.deadline.minimum_execution_time_millis = 1;
    policy.deadline.safety_margin_millis = 0;
    Harness::new(policy, revision_policy())
}

fn advancing_controller(
    h: &Harness,
    clock: &Arc<TestClock>,
    work: Duration,
) -> LocalAdmissionController {
    LocalAdmissionController::new(
        Arc::new(AdvancingPolicy {
            source: Arc::clone(&h.source),
            clock: Arc::clone(clock),
            work,
        }),
        h.quotas.clone(),
        h.load.clone(),
    )
}

#[test]
fn incoming_precision_survives_a_unix_boundary_without_weakening_the_floor() {
    let h = short_budget_harness();
    let clock = TestClock::new(ClockSample::new(10_001, h.sample.monotonic()));
    let incoming =
        IncomingDeadline::new(h.sample.monotonic() + Duration::from_micros(1600), 10_002);
    let mut request = Harness::request("precise");
    request.requested_budget.wall_time_limit_millis = Some(2);
    request.deadline_unix_millis = Some(10_002);
    let permit = h
        .controller
        .admit_with_clock(request.clone(), Some(&incoming), &clock)
        .unwrap();
    assert_eq!(permit.deadline().monotonic(), Some(incoming.monotonic()));
    assert_eq!(
        permit.deadline().remaining_at(h.sample.monotonic()),
        Some(Duration::from_micros(1600))
    );
    assert_eq!(clock.samples.load(Ordering::Relaxed), 1);
    assert_eq!(clock.reads.load(Ordering::Relaxed), 1);
    drop(permit);
    let legacy = h.controller.admit_at(request, clock.sample).unwrap_err();
    assert_eq!(legacy.code, Code::AdmissionRejected);
    assert_eq!(detail(&legacy, "reason"), "queue-deadline-infeasible");
    h.assert_empty();
}

#[test]
fn trusted_constraint_ignores_the_old_unix_projection_after_a_wall_jump() {
    let h = short_budget_harness();
    let clock = TestClock::new(ClockSample::new(9_000_000, h.sample.monotonic()));
    let incoming = IncomingDeadline::new(h.sample.monotonic() + Duration::from_millis(3), 10_003);
    let mut request = Harness::request("wall-jump");
    request.deadline_unix_millis = Some(10_003);
    request.requested_budget.wall_time_limit_millis = Some(2);
    let permit = h
        .controller
        .admit_with_clock(request, Some(&incoming), &clock)
        .unwrap();
    assert_eq!(
        permit.deadline().monotonic(),
        Some(h.sample.monotonic() + Duration::from_millis(2))
    );
    assert_eq!(permit.deadline().unix_millis(), Some(9_000_002));
    drop(permit);
    h.assert_empty();
}

#[test]
fn policy_work_is_charged_before_reservation_for_exact_and_legacy_input() {
    for exact in [false, true] {
        let h = short_budget_harness();
        let clock = Arc::new(TestClock::new(h.sample));
        let controller = advancing_controller(&h, &clock, Duration::from_millis(2));
        let incoming =
            IncomingDeadline::new(h.sample.monotonic() + Duration::from_millis(2), 10_002);
        let mut request = Harness::request("expired-policy-work");
        request.deadline_unix_millis = Some(10_002);
        let result = controller.admit_with_clock(
            request.clone(),
            exact.then_some(&incoming),
            clock.as_ref(),
        );
        assert_eq!(result.unwrap_err().code, Code::DeadlineExceeded);
        assert_eq!(clock.samples.load(Ordering::Relaxed), 1);
        assert_eq!(clock.reads.load(Ordering::Relaxed), 1);
        assert_eq!(h.source.calls.load(Ordering::Relaxed), 1);
        h.assert_empty();
        // The documented frozen seam remains independent of live clock work.
        drop(controller.admit_at(request, h.sample).unwrap());
        assert_eq!(clock.reads.load(Ordering::Relaxed), 1);
        h.assert_empty();
    }
}

#[test]
fn live_feasibility_retains_strict_one_millisecond_boundary_to_one_nanosecond() {
    for advance in [999_999, 1_000_000] {
        let h = short_budget_harness();
        let clock = Arc::new(TestClock::new(h.sample));
        let controller = advancing_controller(&h, &clock, Duration::from_nanos(advance));
        let incoming =
            IncomingDeadline::new(h.sample.monotonic() + Duration::from_millis(2), 10_002);
        let result = controller.admit_with_clock(
            Harness::request("boundary"),
            Some(&incoming),
            clock.as_ref(),
        );
        if advance == 999_999 {
            drop(result.unwrap());
        } else {
            let error = result.unwrap_err();
            assert_eq!(error.code, Code::AdmissionRejected);
            assert_eq!(detail(&error, "reason"), "queue-deadline-infeasible");
        }
        h.assert_empty();
    }
    let h = short_budget_harness();
    let clock = TestClock::new(h.sample);
    let incoming = IncomingDeadline::new(h.sample.monotonic() + Duration::from_millis(1), 10_001);
    assert_eq!(
        h.controller
            .admit_with_clock(Harness::request("one-ms"), Some(&incoming), &clock)
            .unwrap_err()
            .code,
        Code::AdmissionRejected
    );
    h.assert_empty();
}

#[test]
fn live_clock_rejects_a_load_sample_that_becomes_stale_during_policy_work() {
    let mut policy = node_policy();
    policy.overload.maximum_sample_age_millis = 1;
    let h = Harness::new(policy, revision_policy());
    let clock = Arc::new(TestClock::new(h.sample));
    let controller = advancing_controller(&h, &clock, Duration::from_millis(2));
    let error = controller
        .admit_with_clock(Harness::request("stale"), None, clock.as_ref())
        .unwrap_err();
    assert_eq!(error.code, Code::Unavailable);
    assert_eq!(detail(&error, "reason"), "load-sample-not-current");
    h.assert_empty();
}

#[test]
fn ordinary_custom_clocks_do_not_opt_into_system_deadline_waiting() {
    let clock = TestClock::new(ClockSample::new(1000, Instant::now()));
    assert!(!clock.uses_system_monotonic());
    assert!(clock.deadline_wait_observer().is_none());
    assert!(SystemActivationClock.uses_system_monotonic());
    assert!(SystemActivationClock.deadline_wait_observer().is_none());
}
