use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

use latent_core::{
    ActivationClock, ActivationPhase, ActivationTerminalState, BudgetConsumption, ClockSample,
    PlatformErrorCode, ReleaseDigest, RevisionId, RouteGeneration, ServiceId, TenantId,
};

use super::*;
use crate::{ActivationObservationToken, ActivationOutcomeClass, ActivationTerminalObservation};

mod boundaries;

struct Clock {
    base: Instant,
    micros: AtomicU64,
}
impl Clock {
    fn new() -> Self {
        Self {
            base: Instant::now(),
            micros: AtomicU64::new(0),
        }
    }
}
impl ActivationClock for Clock {
    fn sample(&self) -> ClockSample {
        ClockSample::new(1, self.monotonic_now())
    }
    fn monotonic_now(&self) -> Instant {
        self.base + Duration::from_micros(self.micros.load(Ordering::Acquire))
    }
}

fn spec() -> CanaryWindowSpec {
    CanaryWindowSpec {
        identity: CanaryWindowIdentity {
            tenant: TenantId("tenant-a".into()),
            service: ServiceId("echo".into()),
            deployment: "deployment-a".into(),
            rollout_id: "rollout-a".into(),
            step: 1,
            generation: RouteGeneration(17),
        },
        revisions: vec![CanaryRevisionBinding {
            revision: RevisionId("revision-a".into()),
            component: ReleaseDigest(format!("sha256:{}", "a".repeat(64))),
            package: None,
        }],
        duration: Duration::from_secs(10),
    }
}

fn begin(
    hub: &BoundedPhase2CanaryOutcomeWindow,
    input: &CanaryWindowSpec,
    sequence: u64,
) -> CanarySample {
    hub.capture_handle()
        .try_begin(
            ActivationObservationToken {
                manager: 1,
                sequence,
            },
            &input.identity.tenant,
            &input.identity.service,
        )
        .into_sample()
        .expect("captured")
}

fn select(sample: &mut CanarySample, input: &CanaryWindowSpec) {
    sample.bind_selected(SelectedOutcomeRevision {
        tenant: &input.identity.tenant,
        service: &input.identity.service,
        revision: &input.revisions[0].revision,
        component: &input.revisions[0].component,
        generation: input.identity.generation,
    });
}

fn terminal(
    class: ActivationOutcomeClass,
    state: ActivationTerminalState,
) -> ActivationTerminalObservation {
    ActivationTerminalObservation {
        class,
        terminal_state: state,
        platform_code: None,
        consumption: BudgetConsumption::default(),
        last_phase: ActivationPhase::Running,
        sequence: 7,
    }
}

fn success() -> ActivationTerminalObservation {
    terminal(
        ActivationOutcomeClass::GuestSuccess,
        ActivationTerminalState::Completed,
    )
}

#[test]
fn missing_insufficient_and_complete_data_remain_distinct() {
    let hub =
        BoundedPhase2CanaryOutcomeWindow::new(Phase2CanaryOutcomeWindowConfig::default()).unwrap();
    let input = spec();
    let empty = hub.register(&input).unwrap();
    empty.close().unwrap();
    assert_eq!(
        empty.snapshot(1).unwrap().coverage(),
        CanaryCoverage::NoSamples
    );
    drop(empty);
    let window = hub.register(&input).unwrap();
    let mut sample = begin(&hub, &input, 1);
    select(&mut sample, &input);
    sample.admitted();
    sample.finish(&success(), Duration::from_micros(100));
    assert_eq!(window.snapshot(1).unwrap().coverage(), CanaryCoverage::Open);
    window.close().unwrap();
    assert_eq!(
        window.snapshot(2).unwrap().coverage(),
        CanaryCoverage::Insufficient
    );
    let snapshot = window.snapshot(1).unwrap();
    assert_eq!(snapshot.coverage(), CanaryCoverage::CompleteData);
    assert_eq!(
        (
            snapshot.starts(),
            snapshot.selected(),
            snapshot.admitted(),
            snapshot.terminal(),
            snapshot.live()
        ),
        (1, 1, 1, 1, 0)
    );
    assert_eq!(snapshot.revision_outcomes()[0].latency_buckets[0], 1);
}

#[test]
fn outcomes_count_final_result_and_bounded_latency_edges() {
    let hub =
        BoundedPhase2CanaryOutcomeWindow::new(Phase2CanaryOutcomeWindowConfig::default()).unwrap();
    let input = spec();
    let window = hub.register(&input).unwrap();
    for (index, (class, state)) in [
        (
            ActivationOutcomeClass::GuestSuccess,
            ActivationTerminalState::Completed,
        ),
        (
            ActivationOutcomeClass::GuestDomainError,
            ActivationTerminalState::Completed,
        ),
        (
            ActivationOutcomeClass::PlatformFailure,
            ActivationTerminalState::GuestTrap,
        ),
        (
            ActivationOutcomeClass::PlatformFailure,
            ActivationTerminalState::DeadlineExceeded,
        ),
        (
            ActivationOutcomeClass::PlatformFailure,
            ActivationTerminalState::Cancelled,
        ),
    ]
    .into_iter()
    .enumerate()
    {
        let mut sample = begin(&hub, &input, index as u64);
        select(&mut sample, &input);
        select(&mut sample, &input);
        sample.admitted();
        sample.admitted();
        sample.finish(&terminal(class, state), Duration::from_micros(101));
    }
    window.close().unwrap();
    let snapshot = window.snapshot(5).unwrap();
    assert_eq!(snapshot.coverage(), CanaryCoverage::CompleteData);
    let counts = snapshot.revision_outcomes()[0];
    assert_eq!(
        counts.outcomes,
        Phase2CanaryOutcomeCounters {
            success: 1,
            domain_error: 1,
            platform_error: 1,
            deadline_exceeded: 1,
            cancelled: 1
        }
    );
    assert_eq!(
        (
            counts.selected,
            counts.admitted,
            counts.admitted_terminal,
            counts.latency_buckets[1]
        ),
        (5, 5, 5, 5)
    );
}

#[test]
fn samples_rejected_after_success_capacity_never_leave_healthy_data() {
    let hub = BoundedPhase2CanaryOutcomeWindow::new(Phase2CanaryOutcomeWindowConfig {
        maximum_samples_per_series: 1,
        ..Phase2CanaryOutcomeWindowConfig::default()
    })
    .unwrap();
    let input = spec();
    let window = hub.register(&input).unwrap();
    let mut sample = begin(&hub, &input, 1);
    select(&mut sample, &input);
    sample.finish(&success(), Duration::ZERO);
    assert!(matches!(
        hub.capture_handle().try_begin(
            ActivationObservationToken {
                manager: 1,
                sequence: 2
            },
            &input.identity.tenant,
            &input.identity.service
        ),
        CanaryCaptureAttempt::Lost
    ));
    window.close().unwrap();
    let snapshot = window.snapshot(1).unwrap();
    assert_eq!(snapshot.revision_outcomes()[0].outcomes.success, 1);
    assert_eq!(snapshot.coverage(), CanaryCoverage::Incomplete);
}

#[test]
fn close_retains_live_owners_and_old_epoch_cannot_enter_new_window() {
    let hub =
        BoundedPhase2CanaryOutcomeWindow::new(Phase2CanaryOutcomeWindowConfig::default()).unwrap();
    let input = spec();
    let old = hub.register(&input).unwrap();
    let mut sample = begin(&hub, &input, 1);
    select(&mut sample, &input);
    old.close().unwrap();
    assert_eq!(
        old.snapshot(1).unwrap().coverage(),
        CanaryCoverage::Draining
    );
    let new = hub.register(&input).unwrap();
    sample.finish(&success(), Duration::from_secs(11));
    let before = old.snapshot(1).unwrap();
    let after = new.snapshot(1).unwrap();
    assert_ne!(before.epoch(), after.epoch());
    assert_eq!(before.terminal(), 1);
    assert_eq!(after.terminal(), 0);
    assert_eq!(before.coverage(), CanaryCoverage::CompleteData);
    assert_eq!(before.revision_outcomes()[0].latency_buckets[8], 1);
    assert_eq!(hub.snapshot().unwrap().live_samples, 0);
}

#[test]
fn missing_resolution_drop_and_changed_selected_revision_are_incomplete() {
    for mode in 0..3 {
        let hub = BoundedPhase2CanaryOutcomeWindow::new(Phase2CanaryOutcomeWindowConfig::default())
            .unwrap();
        let input = spec();
        let window = hub.register(&input).unwrap();
        let mut sample = begin(&hub, &input, 1);
        if mode == 0 {
            sample.finish(&success(), Duration::ZERO);
        } else if mode == 1 {
            drop(sample);
        } else {
            select(&mut sample, &input);
            let mut foreign = input.clone();
            foreign.identity.generation = RouteGeneration(18);
            select(&mut sample, &foreign);
            sample.finish(&success(), Duration::ZERO);
        }
        window.close().unwrap();
        let snapshot = window.snapshot(1).unwrap();
        assert_eq!(snapshot.coverage(), CanaryCoverage::Incomplete);
        assert_eq!(snapshot.live(), 0);
        if mode == 0 {
            assert_eq!(snapshot.unattributed(), 1);
        }
        if mode == 1 {
            assert_eq!(snapshot.abandoned(), 1);
        }
    }
}

#[test]
fn clock_membership_is_half_open_and_late_completion_drains_original_cohort() {
    let clock = Arc::new(Clock::new());
    let hub = BoundedPhase2CanaryOutcomeWindow::with_clock(
        Phase2CanaryOutcomeWindowConfig::default(),
        clock.clone(),
    )
    .unwrap();
    let input = spec();
    let window = hub.register(&input).unwrap();
    let mut sample = begin(&hub, &input, 1);
    select(&mut sample, &input);
    clock.micros.store(10_000_000, Ordering::Release);
    assert!(matches!(
        hub.capture_handle().try_begin(
            ActivationObservationToken {
                manager: 1,
                sequence: 2
            },
            &input.identity.tenant,
            &input.identity.service
        ),
        CanaryCaptureAttempt::NotObserved
    ));
    assert_eq!(
        window.snapshot(1).unwrap().coverage(),
        CanaryCoverage::Draining
    );
    sample.finish(&success(), Duration::from_secs(12));
    assert_eq!(
        window.snapshot(1).unwrap().coverage(),
        CanaryCoverage::CompleteData
    );
}
