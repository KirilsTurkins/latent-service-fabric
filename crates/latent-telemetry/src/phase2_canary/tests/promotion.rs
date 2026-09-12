use super::*;

fn thresholds() -> CanaryThresholds {
    CanaryThresholds {
        minimum_candidate_samples: 2,
        maximum_failure_basis_points: 5_000,
        latency_threshold_micros: 100,
        maximum_slow_basis_points: 5_000,
    }
}

fn fixture() -> (
    Arc<Clock>,
    BoundedPhase2CanaryOutcomeWindow,
    CanaryWindowSpec,
    CanaryWindow,
) {
    let clock = Arc::new(Clock::new());
    let hub = BoundedPhase2CanaryOutcomeWindow::with_clock(
        Phase2CanaryOutcomeWindowConfig::default(),
        clock.clone(),
    )
    .unwrap();
    let mut input = spec();
    input.revisions.push(CanaryRevisionBinding {
        revision: RevisionId("candidate".into()),
        component: ReleaseDigest(format!("sha256:{}", "b".repeat(64))),
        package: None,
    });
    input.control_digest = Some(format!("sha256:{}", "c".repeat(64)).parse().unwrap());
    let window = hub.register(&input).unwrap();
    (clock, hub, input, window)
}

fn selected(
    hub: &BoundedPhase2CanaryOutcomeWindow,
    input: &CanaryWindowSpec,
    index: usize,
    sequence: u64,
    admitted: bool,
) -> CanarySample {
    let mut sample = begin(hub, input, sequence);
    sample.bind_selected(SelectedOutcomeRevision {
        tenant: &input.identity.tenant,
        service: &input.identity.service,
        revision: &input.revisions[index].revision,
        component: &input.revisions[index].component,
        generation: input.identity.generation,
    });
    if admitted {
        sample.admitted();
    }
    sample
}

fn complete(clock: &Clock) {
    clock.micros.store(10_000_000, Ordering::Release);
}

#[test]
fn full_window_has_exact_candidate_rates_and_inclusive_nanosecond_boundary() {
    let (clock, hub, input, window) = fixture();
    selected(&hub, &input, 1, 1, true).finish(&success(), Duration::from_micros(100));
    selected(&hub, &input, 1, 2, true).finish(
        &terminal(
            ActivationOutcomeClass::GuestDomainError,
            ActivationTerminalState::Completed,
        ),
        Duration::from_micros(100) + Duration::from_nanos(1),
    );
    let candidate = &input.revisions[1].revision;
    assert_eq!(
        window
            .snapshot(1)
            .unwrap()
            .assess_candidate(candidate, thresholds())
            .unwrap()
            .verdict,
        CanaryVerdict::Collecting
    );
    assert_eq!(window.try_seal().unwrap_err().message, "canary-window-open");
    complete(&clock);
    let proof = window.try_seal().unwrap();
    assert!(hub.owns_sealed(&proof));
    let other =
        BoundedPhase2CanaryOutcomeWindow::new(Phase2CanaryOutcomeWindowConfig::default()).unwrap();
    assert!(!other.owns_sealed(&proof));
    assert_eq!(proof.control_digest(), input.control_digest.as_ref());
    assert_eq!(proof.revisions(), &input.revisions);
    let result = proof.assess_candidate(candidate, thresholds()).unwrap();
    assert_eq!(
        (
            result.selected,
            result.admitted_terminal,
            result.successes,
            result.failures,
            result.slow
        ),
        (2, 2, 1, 1, 1)
    );
    assert_eq!(result.verdict, CanaryVerdict::Healthy);
    assert_eq!(proof.revision_outcomes()[1].latency_buckets[..2], [1, 1]);
    for (failure, slow, reason) in [
        (4999, 5000, CanaryDecisionReason::FailureRateExceeded),
        (5000, 4999, CanaryDecisionReason::SlowRateExceeded),
    ] {
        let stricter = CanaryThresholds {
            maximum_failure_basis_points: failure,
            maximum_slow_basis_points: slow,
            ..thresholds()
        };
        assert_eq!(
            proof.assess_candidate(candidate, stricter).unwrap().reason,
            reason
        );
    }
    assert_eq!(
        proof
            .assess_candidate(&RevisionId("foreign".into()), thresholds())
            .unwrap()
            .verdict,
        CanaryVerdict::Incomplete
    );
}

#[test]
fn baseline_success_never_satisfies_candidate_minimum() {
    for candidate_count in 0..=2 {
        let (clock, hub, input, window) = fixture();
        for index in 0..5 {
            selected(&hub, &input, 0, index, true).finish(&success(), Duration::ZERO);
        }
        for index in 0..candidate_count {
            selected(&hub, &input, 1, index + 10, true).finish(&success(), Duration::ZERO);
        }
        complete(&clock);
        let proof = window.try_seal().unwrap();
        let result = proof
            .assess_candidate(&input.revisions[1].revision, thresholds())
            .unwrap();
        assert_eq!(result.selected, candidate_count);
        assert_eq!(
            result.verdict,
            [
                CanaryVerdict::NoData,
                CanaryVerdict::Insufficient,
                CanaryVerdict::Healthy
            ][usize::try_from(candidate_count).unwrap()]
        );
    }
}

#[test]
fn failed_cancelled_deadline_and_selected_admission_rejections_stay_in_denominator() {
    let (clock, hub, input, window) = fixture();
    selected(&hub, &input, 1, 0, true).finish(&success(), Duration::ZERO);
    for (sequence, class, state, admitted) in [
        (
            1,
            ActivationOutcomeClass::GuestDomainError,
            ActivationTerminalState::Completed,
            true,
        ),
        (
            2,
            ActivationOutcomeClass::PlatformFailure,
            ActivationTerminalState::PlatformFailed,
            true,
        ),
        (
            3,
            ActivationOutcomeClass::PlatformFailure,
            ActivationTerminalState::DeadlineExceeded,
            true,
        ),
        (
            4,
            ActivationOutcomeClass::PlatformFailure,
            ActivationTerminalState::Cancelled,
            true,
        ),
        (
            5,
            ActivationOutcomeClass::PlatformFailure,
            ActivationTerminalState::Rejected,
            false,
        ),
    ] {
        selected(&hub, &input, 1, sequence, admitted)
            .finish(&terminal(class, state), Duration::ZERO);
    }
    complete(&clock);
    let proof = window.try_seal().unwrap();
    let result = proof
        .assess_candidate(&input.revisions[1].revision, thresholds())
        .unwrap();
    assert_eq!(
        (
            result.selected,
            result.admitted_terminal,
            result.successes,
            result.failures
        ),
        (6, 5, 1, 5)
    );
    assert_eq!(result.reason, CanaryDecisionReason::FailureRateExceeded);
    assert_eq!(
        proof.revision_outcomes()[1].outcomes,
        Phase2CanaryOutcomeCounters {
            success: 1,
            domain_error: 1,
            platform_error: 2,
            deadline_exceeded: 1,
            cancelled: 1,
        }
    );
}

#[test]
fn early_close_and_live_or_abandoned_samples_cannot_seal() {
    let (clock, hub, input, window) = fixture();
    selected(&hub, &input, 1, 1, true).finish(&success(), Duration::ZERO);
    window.close().unwrap();
    complete(&clock);
    assert_eq!(
        window.try_seal().unwrap_err().message,
        "canary-window-incomplete"
    );
    assert_eq!(
        window
            .snapshot(1)
            .unwrap()
            .assess_candidate(&input.revisions[1].revision, thresholds())
            .unwrap()
            .reason,
        CanaryDecisionReason::WindowClosedEarly
    );
    for abandon in [false, true] {
        let (clock, hub, input, window) = fixture();
        let sample = selected(&hub, &input, 1, 1, true);
        complete(&clock);
        assert_eq!(
            window.try_seal().unwrap_err().message,
            "canary-window-draining"
        );
        if abandon {
            drop(sample);
            assert_eq!(
                window.try_seal().unwrap_err().message,
                "canary-window-incomplete"
            );
        } else {
            sample.finish(&success(), Duration::from_secs(12));
            let proof = window.try_seal().unwrap();
            assert_eq!(proof.revision_outcomes()[1].latency_buckets[8], 1);
        }
    }
}

#[test]
fn delayed_failed_capture_is_inside_frontier_until_loss_publication_finishes() {
    let (clock, hub, input, window) = fixture();
    selected(&hub, &input, 1, 1, true).finish(&success(), Duration::ZERO);
    let registry = hub.0.registry.lock().unwrap();
    let (entered, receive_entered) = std::sync::mpsc::sync_channel(0);
    let (release, receive_release) = std::sync::mpsc::sync_channel(0);
    let producer_hub = hub.clone();
    let producer = std::thread::spawn(move || {
        let _attempt = super::super::capture::CaptureFrontier::enter(&producer_hub.0);
        assert!(producer_hub.0.registry.try_lock().is_err());
        entered.send(()).unwrap();
        receive_release
            .recv_timeout(Duration::from_secs(5))
            .unwrap();
        producer_hub.0.lose_unattributed();
    });
    receive_entered
        .recv_timeout(Duration::from_secs(5))
        .unwrap();
    drop(registry);
    complete(&clock);
    assert_eq!(
        window.try_seal().unwrap_err().message,
        "canary-window-draining"
    );
    release.send(()).unwrap();
    producer.join().unwrap();
    assert_eq!(
        window.try_seal().unwrap_err().message,
        "canary-window-incomplete"
    );
}

#[test]
fn sealed_frontier_remains_fixed_and_retains_real_snapshot_and_window_allowances() {
    let (clock, hub, input, window) = fixture();
    for index in 0..2 {
        selected(&hub, &input, 1, index, true).finish(&success(), Duration::ZERO);
    }
    complete(&clock);
    let diagnostic = window.snapshot(1).unwrap();
    let proof = window.try_seal().unwrap();
    hub.0.lose_unattributed();
    assert_eq!(diagnostic.coverage(), CanaryCoverage::Incomplete);
    assert_eq!(
        proof
            .assess_candidate(&input.revisions[1].revision, thresholds())
            .unwrap()
            .verdict,
        CanaryVerdict::Healthy
    );
    drop(diagnostic);
    drop(window);
    assert_eq!(
        (
            hub.snapshot().unwrap().tracked_series,
            hub.snapshot().unwrap().snapshot_owners
        ),
        (1, 1)
    );
    drop(proof);
    assert_eq!(
        (
            hub.snapshot().unwrap().tracked_series,
            hub.snapshot().unwrap().snapshot_owners
        ),
        (0, 0)
    );
}

#[test]
fn policy_rejects_unsupported_boundaries_and_counter_overflow() {
    for policy in [
        CanaryThresholds {
            minimum_candidate_samples: 0,
            ..thresholds()
        },
        CanaryThresholds {
            minimum_candidate_samples: 1_000_001,
            ..thresholds()
        },
        CanaryThresholds {
            maximum_failure_basis_points: 10_000,
            ..thresholds()
        },
        CanaryThresholds {
            maximum_slow_basis_points: 10_001,
            ..thresholds()
        },
        CanaryThresholds {
            latency_threshold_micros: 101,
            ..thresholds()
        },
    ] {
        assert!(policy.validate().is_err());
    }
    let input = spec();
    let impossible = CanaryRevisionSnapshot {
        selected: u64::MAX,
        admitted: u64::MAX,
        admitted_terminal: u64::MAX,
        outcomes: Phase2CanaryOutcomeCounters {
            success: u64::MAX,
            platform_error: 1,
            ..Default::default()
        },
        latency_buckets: [u64::MAX; 9],
    };
    let result = super::super::policy::assess(
        &input.revisions,
        &[impossible],
        &input.revisions[0].revision,
        thresholds(),
        CanaryCoverage::CompleteData,
        false,
    )
    .unwrap();
    assert_eq!(result.verdict, CanaryVerdict::Incomplete);
}

#[test]
fn registration_loss_cannot_be_hidden_by_a_baseline_sampled_after_start() {
    struct RegistrationClock {
        clock: Clock,
        lose_on_read: std::sync::Mutex<Option<std::sync::Weak<super::super::window::Hub>>>,
    }
    impl ActivationClock for RegistrationClock {
        fn sample(&self) -> ClockSample {
            ClockSample::new(1, self.monotonic_now())
        }
        fn monotonic_now(&self) -> Instant {
            if let Some(hub) = self
                .lose_on_read
                .lock()
                .unwrap()
                .take()
                .and_then(|hub| hub.upgrade())
            {
                hub.lose_unattributed();
            }
            self.clock.monotonic_now()
        }
    }
    let clock = Arc::new(RegistrationClock {
        clock: Clock::new(),
        lose_on_read: std::sync::Mutex::new(None),
    });
    let hub = BoundedPhase2CanaryOutcomeWindow::with_clock(
        Phase2CanaryOutcomeWindowConfig::default(),
        clock.clone(),
    )
    .unwrap();
    *clock.lose_on_read.lock().unwrap() = Some(Arc::downgrade(&hub.0));
    let input = spec();
    let window = hub.register(&input).unwrap();
    selected(&hub, &input, 0, 1, true).finish(&success(), Duration::ZERO);
    complete(&clock.clock);
    assert_eq!(
        window.try_seal().unwrap_err().message,
        "canary-window-incomplete"
    );
}

#[test]
fn sealed_proofs_do_not_refund_window_or_read_capacity_while_retained() {
    let clock = Arc::new(Clock::new());
    let hub = BoundedPhase2CanaryOutcomeWindow::with_clock(
        Phase2CanaryOutcomeWindowConfig {
            maximum_series: 1,
            maximum_snapshot_owners: 1,
            ..Default::default()
        },
        clock.clone(),
    )
    .unwrap();
    let input = spec();
    let window = hub.register(&input).unwrap();
    selected(&hub, &input, 0, 1, true).finish(&success(), Duration::ZERO);
    complete(&clock);
    let proof = window.try_seal().unwrap();
    assert_eq!(
        window.try_seal().unwrap_err().code,
        PlatformErrorCode::ResourceExhausted
    );
    drop(window);
    assert!(hub.register(&input).is_err());
    drop(proof);
    assert!(hub.register(&input).is_ok());
}

#[test]
fn permissive_rates_never_turn_zero_guest_success_into_health() {
    for admitted in [false, true] {
        let (clock, hub, input, window) = fixture();
        selected(&hub, &input, 1, 1, admitted).finish(
            &terminal(
                ActivationOutcomeClass::PlatformFailure,
                ActivationTerminalState::Rejected,
            ),
            Duration::ZERO,
        );
        complete(&clock);
        let proof = window.try_seal().unwrap();
        let assessment = proof
            .assess_candidate(
                &input.revisions[1].revision,
                CanaryThresholds {
                    minimum_candidate_samples: 1,
                    maximum_failure_basis_points: 9999,
                    maximum_slow_basis_points: 10000,
                    ..thresholds()
                },
            )
            .unwrap();
        assert_eq!(
            assessment.reason,
            if admitted {
                CanaryDecisionReason::NoSuccessfulCandidate
            } else {
                CanaryDecisionReason::NoAdmittedCandidate
            }
        );
        assert_eq!(assessment.verdict, CanaryVerdict::Failed);
    }
}
