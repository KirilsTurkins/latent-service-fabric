use super::*;

#[test]
fn every_retained_identity_is_bounded_fresh_and_component_digest_is_exact() {
    let hub = BoundedPhase2CanaryOutcomeWindow::new(Phase2CanaryOutcomeWindowConfig {
        maximum_identity_bytes: 16,
        ..Phase2CanaryOutcomeWindowConfig::default()
    })
    .unwrap();
    for field in 0..5 {
        let mut input = spec();
        match field {
            0 => input.identity.tenant.0 = "x".repeat(17),
            1 => input.identity.service.0 = "x".repeat(17),
            2 => input.identity.rollout_id = "x".repeat(17),
            3 => input.identity.deployment = "x".repeat(17),
            _ => input.revisions[0].revision.0 = "x".repeat(17),
        }
        assert_eq!(
            hub.register(&input).err().unwrap().code,
            PlatformErrorCode::InvalidArgument
        );
    }
    let mut input = spec();
    input.identity.rollout_id = String::with_capacity(16_384);
    input.identity.rollout_id.push_str("rollout-a");
    input.revisions.reserve(100);
    let window = hub.register(&input).unwrap();
    let snapshot = window.snapshot(1).unwrap();
    assert!(snapshot.identity().rollout_id.capacity() <= 16);
    assert_eq!(snapshot.revisions().len(), 1);
    drop(snapshot);
    drop(window);
    for digest in [
        "sha256:component".to_owned(),
        format!("sha256:{}", "A".repeat(64)),
    ] {
        input.revisions[0].component = ReleaseDigest(digest);
        assert_eq!(
            hub.register(&input).err().unwrap().code,
            PlatformErrorCode::InvalidArgument
        );
    }
}

#[test]
fn slots_live_samples_and_snapshots_remain_charged_until_actual_drop() {
    let hub = BoundedPhase2CanaryOutcomeWindow::new(Phase2CanaryOutcomeWindowConfig {
        maximum_series: 1,
        maximum_live_samples: 1,
        maximum_snapshot_owners: 1,
        ..Phase2CanaryOutcomeWindowConfig::default()
    })
    .unwrap();
    let input = spec();
    let window = hub.register(&input).unwrap();
    let sample = begin(&hub, &input, 1);
    let snapshot = window.snapshot(1).unwrap();
    assert_eq!(
        window.snapshot(1).err().unwrap().code,
        PlatformErrorCode::ResourceExhausted
    );
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
    drop(window);
    assert_eq!(
        hub.register(&input).err().unwrap().code,
        PlatformErrorCode::ResourceExhausted
    );
    drop(sample);
    assert_eq!(hub.snapshot().unwrap().live_samples, 0);
    assert_eq!(
        hub.register(&input).err().unwrap().code,
        PlatformErrorCode::ResourceExhausted
    );
    drop(snapshot);
    assert_eq!(hub.snapshot().unwrap().total_samples, 0);
    assert!(hub.register(&input).is_ok());
}

#[test]
fn registry_or_terminal_contention_is_visible_without_waiting_for_gate() {
    let hub =
        BoundedPhase2CanaryOutcomeWindow::new(Phase2CanaryOutcomeWindowConfig::default()).unwrap();
    let input = spec();
    let window = hub.register(&input).unwrap();
    let mut sample = begin(&hub, &input, 1);
    select(&mut sample, &input);
    let guard = window.0.stats.lock().unwrap();
    sample.finish(&success(), Duration::ZERO);
    drop(guard);
    assert_eq!(hub.snapshot().unwrap().live_samples, 0);
    assert_eq!(
        window.snapshot(1).unwrap().coverage(),
        CanaryCoverage::Incomplete
    );
    let registry = hub.0.registry.lock().unwrap();
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
    drop(registry);
    assert_eq!(hub.snapshot().unwrap().unattributed_loss_epoch, 1);
}

#[test]
fn unassigned_loss_downgrades_retained_readout_and_exhaustion_never_wraps() {
    let hub =
        BoundedPhase2CanaryOutcomeWindow::new(Phase2CanaryOutcomeWindowConfig::default()).unwrap();
    let input = spec();
    let window = hub.register(&input).unwrap();
    let mut sample = begin(&hub, &input, 1);
    select(&mut sample, &input);
    sample.finish(&success(), Duration::ZERO);
    window.close().unwrap();
    let snapshot = window.snapshot(1).unwrap();
    assert_eq!(snapshot.coverage(), CanaryCoverage::CompleteData);
    hub.0.lose_unattributed();
    assert_eq!(snapshot.coverage(), CanaryCoverage::Incomplete);
    hub.0.loss_epoch.store(u64::MAX, Ordering::Release);
    hub.0.lose_unattributed();
    assert!(hub.snapshot().unwrap().loss_epoch_exhausted);
    assert_eq!(hub.snapshot().unwrap().unattributed_loss_epoch, u64::MAX);
}

#[test]
fn foreign_tenant_is_not_captured_and_overlap_is_rejected() {
    let hub =
        BoundedPhase2CanaryOutcomeWindow::new(Phase2CanaryOutcomeWindowConfig::default()).unwrap();
    let input = spec();
    let window = hub.register(&input).unwrap();
    assert_eq!(
        hub.register(&input).err().unwrap().code,
        PlatformErrorCode::AlreadyExists
    );
    assert!(matches!(
        hub.capture_handle().try_begin(
            ActivationObservationToken {
                manager: 1,
                sequence: 1
            },
            &TenantId("tenant-b".into()),
            &input.identity.service
        ),
        CanaryCaptureAttempt::NotObserved
    ));
    window.close().unwrap();
    assert_eq!(
        window.snapshot(1).unwrap().coverage(),
        CanaryCoverage::NoSamples
    );
    for required in [0, 1_000_001] {
        assert_eq!(
            window.snapshot(required).err().unwrap().code,
            PlatformErrorCode::InvalidArgument
        );
    }
}

#[test]
fn global_sample_cap_and_invalid_configuration_are_bounded() {
    let hub = BoundedPhase2CanaryOutcomeWindow::new(Phase2CanaryOutcomeWindowConfig {
        maximum_total_samples: 1,
        ..Phase2CanaryOutcomeWindowConfig::default()
    })
    .unwrap();
    let input = spec();
    let first = hub.register(&input).unwrap();
    let mut sample = begin(&hub, &input, 1);
    select(&mut sample, &input);
    sample.finish(&success(), Duration::ZERO);
    first.close().unwrap();
    let second = hub.register(&input).unwrap();
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
    assert_eq!(
        second.snapshot(1).unwrap().coverage(),
        CanaryCoverage::Incomplete
    );
    for config in [
        Phase2CanaryOutcomeWindowConfig {
            maximum_series: usize::MAX,
            ..Phase2CanaryOutcomeWindowConfig::default()
        },
        Phase2CanaryOutcomeWindowConfig {
            maximum_live_samples: 0,
            ..Phase2CanaryOutcomeWindowConfig::default()
        },
        Phase2CanaryOutcomeWindowConfig {
            maximum_snapshot_owners: 17,
            ..Phase2CanaryOutcomeWindowConfig::default()
        },
    ] {
        assert!(BoundedPhase2CanaryOutcomeWindow::new(config).is_err());
    }
    assert_eq!(
        Phase2CanaryOutcomeCounters {
            success: u64::MAX,
            domain_error: 1,
            ..Phase2CanaryOutcomeCounters::default()
        }
        .total(),
        u64::MAX
    );
    assert_eq!(
        Phase2CanaryOutcomeClass::PlatformError.metric_label(),
        "platform_error"
    );
    assert_eq!(CanaryCoverage::Incomplete.metric_label(), "incomplete");
}
