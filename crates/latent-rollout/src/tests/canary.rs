mod support;
use super::*;
use latent_control_store::rollouts::{RolloutCommand, RolloutId, RolloutState};
use latent_core::{PlatformErrorCode, TenantId};
use latent_telemetry::CanaryVerdict;
use support::{change, evaluation, start, Clock};

#[test]
fn complete_window_promotes_once_and_replays_without_old_live_evidence() {
    runtime().block_on(async {
        let clock = Arc::new(Clock::new());
        let mut fixture = support::fixture(clock.clone(), 16).await;
        let started = fixture
            .handle
            .submit(start(), expires(), |p| {
                assert!(p.observation.is_some());
                Ok(())
            })
            .unwrap()
            .wait()
            .await
            .unwrap();
        assert_eq!(
            started.value().observation.unwrap().state,
            RolloutObservationState::Collecting
        );
        drop(started);
        assert!(fixture
            .handle
            .submit(
                change("bypass", 1, RolloutCommand::Promote { next_step: 1 }),
                expires(),
                |_| Ok(())
            )
            .is_err());
        support::successes(&fixture, 2);
        clock.set_millis(10);
        let report = fixture
            .handle
            .evaluate(evaluation(1), expires())
            .unwrap()
            .wait()
            .await
            .unwrap();
        assert_eq!(
            report.value().assessment.unwrap().verdict,
            CanaryVerdict::Healthy
        );
        assert_eq!(report.value().revisions.len(), 2);
        drop(report);
        let promoted = fixture
            .handle
            .promote(
                change("promote", 1, RolloutCommand::Promote { next_step: 1 }),
                expires(),
                |p| {
                    assert!(p.failure.is_none());
                    assert!(p.receipt.unwrap().canary_decision.is_some());
                    Ok(())
                },
            )
            .unwrap()
            .wait()
            .await
            .unwrap();
        assert_eq!(promoted.value().receipt.revision, 2);
        assert_eq!(
            promoted
                .value()
                .receipt
                .canary_decision
                .as_ref()
                .unwrap()
                .candidate
                .success,
            2
        );
        let replay = fixture
            .handle
            .promote(
                change("promote", 1, RolloutCommand::Promote { next_step: 1 }),
                expires(),
                |p| {
                    assert!(p.replayed);
                    Ok(())
                },
            )
            .unwrap()
            .wait()
            .await
            .unwrap();
        assert!(replay.value().replayed);
        assert_eq!(replay.value().receipt, promoted.value().receipt);
        let attempt = audit::attempt(&promoted.value().receipt, false).unwrap();
        assert_eq!(attempt.action, latent_audit::AuditControlAction::Promotion);
        assert!(attempt.identities.canary_evidence_digest.is_some());
        support::assert_healthy_audit(&fixture).await;
        drop(replay);
        drop(promoted);
        fixture.shutdown().await;
    });
}

#[test]
fn rejection_preflight_has_no_audit_effect_then_no_data_is_durably_rejected() {
    runtime().block_on(async {
        let clock = Arc::new(Clock::new());
        let mut fixture = support::fixture(clock.clone(), 16).await;
        drop(
            fixture
                .handle
                .submit(start(), expires(), |_| Ok(()))
                .unwrap()
                .wait()
                .await
                .unwrap(),
        );
        clock.set_millis(10);
        // A queued query follows the independent Start observation in the audit
        // FIFO, so this assertion cannot race its delayed journal append.
        drop(
            fixture
                .audit
                .query(
                    latent_audit::AuditQueryRequest {
                        scope: latent_audit::AuditScope::Tenant(TenantId("alice".into())),
                        filter: latent_audit::AuditFilter::default(),
                        cursor: None,
                        limit: 1,
                        maximum_bytes: 32768,
                    },
                    expires(),
                )
                .unwrap()
                .wait()
                .await
                .unwrap(),
        );
        let before = fixture.audit.snapshot().retained_records;
        let result = fixture
            .handle
            .promote(
                change("too-small", 1, RolloutCommand::Promote { next_step: 1 }),
                expires(),
                |p| {
                    assert!(p.receipt.is_none());
                    assert!(p.failure.is_some());
                    assert_eq!(
                        p.decision.unwrap().assessment.unwrap().verdict,
                        CanaryVerdict::NoData
                    );
                    Err(capacity("tiny-wire-budget"))
                },
            )
            .unwrap()
            .wait()
            .await;
        assert_eq!(
            result.err().unwrap().error.code,
            PlatformErrorCode::ResourceExhausted
        );
        assert_eq!(fixture.audit.snapshot().retained_records, before);
        let failed = fixture
            .handle
            .promote(
                change("no-data", 1, RolloutCommand::Promote { next_step: 1 }),
                expires(),
                |_| Ok(()),
            )
            .unwrap()
            .wait()
            .await
            .err()
            .unwrap();
        assert_eq!(failed.error.message, "rollout-canary-no-data");
        assert_eq!(
            failed.audit_ack.status,
            latent_artifacts::ReleaseAuditStatus::Durable
        );
        let summaries = support::summaries(&fixture).await;
        let decision = summaries
            .iter()
            .find(|value| value.verdict == latent_audit::AuditCanaryVerdict::NoData)
            .unwrap();
        assert_eq!(
            (
                decision.selected,
                decision.minimum_candidate_samples,
                decision.observation_millis
            ),
            (0, 2, 10)
        );
        assert_eq!(
            fixture
                .repository
                .get_rollout(&TenantId("alice".into()), &RolloutId("rollout".into()))
                .unwrap()
                .unwrap()
                .revision,
            1
        );
        fixture.shutdown().await;
    });
}

#[test]
fn early_and_insufficient_windows_never_advance_and_evaluation_keeps_response_lease() {
    runtime().block_on(async {
        let clock = Arc::new(Clock::new());
        let mut fixture = support::fixture(clock.clone(), 16).await;
        drop(
            fixture
                .handle
                .submit(start(), expires(), |_| Ok(()))
                .unwrap()
                .wait()
                .await
                .unwrap(),
        );
        support::successes(&fixture, 1);
        let failed = fixture
            .handle
            .promote(
                change("early", 1, RolloutCommand::Promote { next_step: 1 }),
                expires(),
                |_| Ok(()),
            )
            .unwrap()
            .wait()
            .await
            .err()
            .unwrap();
        assert_eq!(failed.error.message, "rollout-canary-collecting");
        clock.set_millis(10);
        let failed = fixture
            .handle
            .promote(
                change("insufficient", 1, RolloutCommand::Promote { next_step: 1 }),
                expires(),
                |_| Ok(()),
            )
            .unwrap()
            .wait()
            .await
            .err()
            .unwrap();
        assert_eq!(failed.error.message, "rollout-canary-insufficient");
        let report = fixture
            .handle
            .evaluate(evaluation(1), expires())
            .unwrap()
            .wait()
            .await
            .unwrap();
        assert_eq!(
            report.value().assessment.unwrap().verdict,
            CanaryVerdict::Insufficient
        );
        fixture.shutdown().await;
        assert_eq!(fixture.handle.snapshot().response_owners, 1);
        assert_eq!(fixture.handle.snapshot().canary_windows, 0);
        drop(report);
        assert_eq!(fixture.handle.snapshot().response_bytes, 0);
    });
}

#[test]
fn paused_live_sample_keeps_slot_charged_and_resume_survives_registration_pressure() {
    runtime().block_on(async {
        let clock = Arc::new(Clock::new());
        let mut fixture = support::fixture(clock, 1).await;
        drop(
            fixture
                .handle
                .submit(start(), expires(), |_| Ok(()))
                .unwrap()
                .wait()
                .await
                .unwrap(),
        );
        let sample = support::sample(&fixture, 1);
        let paused = fixture
            .handle
            .submit(change("pause", 1, RolloutCommand::Pause), expires(), |_| {
                Ok(())
            })
            .unwrap()
            .wait()
            .await
            .unwrap();
        assert_eq!(paused.value().receipt.state, RolloutState::Paused);
        drop(paused);
        assert_eq!(
            fixture
                .handle
                .canary_snapshot()
                .unwrap()
                .unwrap()
                .tracked_series,
            1
        );
        let resumed = fixture
            .handle
            .submit(
                change("resume", 2, RolloutCommand::Resume),
                expires(),
                |_| Ok(()),
            )
            .unwrap()
            .wait()
            .await
            .unwrap();
        assert_eq!(resumed.value().receipt.state, RolloutState::Running);
        assert_eq!(
            resumed.value().observation.unwrap().state,
            RolloutObservationState::Unavailable
        );
        drop(resumed);
        drop(sample);
        let report = fixture
            .handle
            .evaluate(evaluation(3), expires())
            .unwrap()
            .wait()
            .await
            .unwrap();
        assert_eq!(
            report.value().assessment.unwrap().verdict,
            CanaryVerdict::Collecting
        );
        drop(report);
        fixture.shutdown().await;
    });
}

#[test]
fn failed_candidate_is_in_denominator_and_worker_restart_requires_a_fresh_window() {
    runtime().block_on(async {
        let clock = Arc::new(Clock::new());
        let mut fixture = support::fixture(clock.clone(), 16).await;
        drop(
            fixture
                .handle
                .submit(start(), expires(), |_| Ok(()))
                .unwrap()
                .wait()
                .await
                .unwrap(),
        );
        support::successes(&fixture, 1);
        support::sample(&fixture, 2).finish(
            &latent_telemetry::ActivationTerminalObservation {
                class: latent_telemetry::ActivationOutcomeClass::PlatformFailure,
                terminal_state: latent_core::ActivationTerminalState::DeadlineExceeded,
                platform_code: Some(PlatformErrorCode::DeadlineExceeded),
                consumption: latent_core::BudgetConsumption::default(),
                last_phase: latent_core::ActivationPhase::Running,
                sequence: 2,
            },
            Duration::from_micros(100),
        );
        clock.set_millis(10);
        let failed = fixture
            .handle
            .promote(
                change("failed", 1, RolloutCommand::Promote { next_step: 1 }),
                expires(),
                |p| {
                    let counters = p.decision.unwrap().assessment.unwrap();
                    assert_eq!(
                        (counters.selected, counters.successes, counters.failures),
                        (2, 1, 1)
                    );
                    Ok(())
                },
            )
            .unwrap()
            .wait()
            .await
            .err()
            .unwrap();
        assert_eq!(failed.error.message, "rollout-canary-failed");
        assert!(fixture.worker.join_until(expires()).await.unwrap());
        let (handle, mut worker) = RolloutCoordinator::start(
            fixture.repository.clone(),
            fixture.audit.clone(),
            CoordinatorLimits::default(),
            &tokio::runtime::Handle::current(),
        )
        .unwrap();
        worker.wait_started(expires()).await.unwrap();
        fixture.worker = worker;
        fixture.handle = handle;
        let report = fixture
            .handle
            .evaluate(evaluation(1), expires())
            .unwrap()
            .wait()
            .await
            .unwrap();
        assert_eq!(
            report.value().assessment.unwrap().verdict,
            CanaryVerdict::Collecting
        );
        assert_eq!(report.value().starts, 0);
        assert!(report.value().window_epoch.unwrap() > 1);
        drop(report);
        fixture.shutdown().await;
    });
}
