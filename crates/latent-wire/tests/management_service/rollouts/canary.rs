use super::*;
use latent_core::{ActivationClock, ClockSample};
use latent_telemetry::{BoundedPhase2CanaryOutcomeWindow, Phase2CanaryOutcomeWindowConfig};
use std::sync::{
    atomic::{AtomicU64, Ordering},
    Arc,
};

struct Clock {
    base: Instant,
    millis: AtomicU64,
}
impl ActivationClock for Clock {
    fn sample(&self) -> ClockSample {
        ClockSample::new(1, self.monotonic_now())
    }
    fn monotonic_now(&self) -> Instant {
        self.base + Duration::from_millis(self.millis.load(Ordering::Acquire))
    }
}
fn policy() -> proto::RolloutCanaryPolicy {
    proto::RolloutCanaryPolicy {
        format_version: 1,
        observation_millis: 1,
        minimum_candidate_samples: 1,
        maximum_failure_basis_points: Some(0),
        latency_threshold_micros: 100,
        maximum_slow_basis_points: Some(0),
    }
}

#[tokio::test]
#[allow(
    clippy::too_many_lines,
    reason = "one RPC schedule proves rejection, durable audit acknowledgement and unchanged routes"
)]
async fn empty_candidate_interval_rejects_promotion_with_audit_and_keeps_weights() {
    let directory = TempDir::new().unwrap();
    let (audit, mut journal) =
        DirectoryPhase2AuditJournal::open(directory.path().join("audit"), AuditLimits::default())
            .unwrap();
    let clock = Arc::new(Clock {
        base: Instant::now(),
        millis: AtomicU64::new(0),
    });
    let hub = BoundedPhase2CanaryOutcomeWindow::with_clock(
        Phase2CanaryOutcomeWindowConfig::default(),
        clock.clone(),
    )
    .unwrap();
    let harness = Harness::with_canary(ManagementLimits::default(), audit.clone(), hub).await;
    let mut input = start_input(&harness).await;
    input.canary_policy = Some(policy());
    let mut client =
        proto::rollout_service_client::RolloutServiceClient::new(harness.channel.clone());
    let started = client
        .start_rollout(request("alice", input))
        .await
        .unwrap()
        .into_inner()
        .receipt
        .unwrap();
    for revision in [None, Some(0)] {
        assert_eq!(
            client
                .evaluate_rollout(request(
                    "alice",
                    proto::EvaluateRolloutRequest {
                        id: "rollout".into(),
                        expected_revision: revision
                    }
                ))
                .await
                .unwrap_err()
                .code(),
            Code::InvalidArgument
        );
    }
    assert_eq!(
        client
            .evaluate_rollout(request(
                "caller",
                proto::EvaluateRolloutRequest {
                    id: "rollout".into(),
                    expected_revision: Some(1)
                }
            ))
            .await
            .unwrap_err()
            .code(),
        Code::PermissionDenied
    );
    assert!(client
        .evaluate_rollout(request(
            "bob",
            proto::EvaluateRolloutRequest {
                id: "rollout".into(),
                expected_revision: Some(1)
            }
        ))
        .await
        .is_err());
    clock.millis.store(1, Ordering::Release);
    let evaluated = client
        .evaluate_rollout(request(
            "alice",
            proto::EvaluateRolloutRequest {
                id: "rollout".into(),
                expected_revision: Some(1),
            },
        ))
        .await
        .unwrap()
        .into_inner()
        .report
        .unwrap();
    assert_eq!(
        evaluated.assessment.unwrap().verdict,
        proto::CanaryVerdict::NoData as i32
    );
    assert_eq!(evaluated.terminal, 0);
    let failed = client
        .change_rollout(request(
            "alice",
            proto::ChangeRolloutRequest {
                id: "rollout".into(),
                operation: Some(proto::RolloutOperationPrecondition {
                    operation_id: "no-data".into(),
                    expected_revision: Some(1),
                }),
                command: Some(proto::change_rollout_request::Command::Promote(
                    proto::PromoteRollout { next_step: 1 },
                )),
            },
        ))
        .await
        .unwrap_err();
    let attempt_sequence = failed
        .metadata()
        .get("latent-audit-attempt")
        .unwrap()
        .to_str()
        .unwrap()
        .parse::<u64>()
        .unwrap();
    check_rejected_decision(&harness.channel, attempt_sequence).await;
    let status = client
        .get_rollout(request(
            "alice",
            proto::GetRolloutRequest {
                id: "rollout".into(),
            },
        ))
        .await
        .unwrap()
        .into_inner()
        .status
        .unwrap();
    assert_eq!(status.current_step, 0);
    assert_eq!(status.route_generation, started.route_generation);
    let lookup = client
        .get_rollout_operation(request(
            "alice",
            proto::GetRolloutOperationRequest {
                id: "rollout".into(),
                operation_id: "no-data".into(),
            },
        ))
        .await
        .unwrap()
        .into_inner();
    assert_eq!(
        lookup.disposition,
        proto::RolloutOperationLookupDisposition::Unknown as i32
    );
    drop(client);
    harness.shutdown().await;
    audit.close();
    assert!(journal
        .join_until(Instant::now() + Duration::from_secs(5))
        .unwrap());
}

async fn check_rejected_decision(channel: &tonic::transport::Channel, attempt_sequence: u64) {
    let mut client = proto::audit_service_client::AuditServiceClient::new(channel.clone());
    let page = client
        .query_phase2_audit(request(
            "alice",
            proto::QueryPhase2AuditRequest {
                scope: Some(proto::AuditQueryScope {
                    kind: proto::AuditScopeKind::Tenant as i32,
                    tenant: Some("acme".into()),
                }),
                filter: None,
                page: Some(proto::PageRequest {
                    page_size: 32,
                    page_token: None,
                }),
            },
        ))
        .await
        .unwrap()
        .into_inner();
    let outcome = page
        .records
        .into_iter()
        .find_map(|record| match record.data {
            Some(proto::phase2_audit_record::Data::Outcome(value))
                if value.attempt_sequence == attempt_sequence =>
            {
                Some(value)
            }
            _ => None,
        })
        .expect("the promotion acknowledgement identifies a durable audit outcome");
    assert_eq!(outcome.result, proto::AuditOperationResult::Rejected as i32);
    let decision = outcome.canary_decision.unwrap();
    assert_eq!(decision.verdict, proto::AuditCanaryVerdict::NoData as i32);
    assert_eq!(
        decision.reason,
        proto::AuditCanaryReason::NoCandidateSamples as i32
    );
    assert_eq!(decision.observation_millis, 1);
    assert_eq!(decision.minimum_candidate_samples, 1);
    assert_eq!(decision.maximum_failure_basis_points, 0);
    assert_eq!(decision.latency_threshold_micros, 100);
    assert_eq!(decision.maximum_slow_basis_points, 0);
    assert_eq!(decision.selected, 0);
    assert_eq!(decision.admitted_terminal, 0);
    assert_eq!(decision.successes, 0);
    assert_eq!(decision.failures, 0);
    assert_eq!(decision.slow, 0);
}

#[tokio::test]
async fn canary_start_never_falls_back_to_manual_without_configured_observations() {
    let directory = TempDir::new().unwrap();
    let (audit, mut journal) =
        DirectoryPhase2AuditJournal::open(directory.path().join("audit"), AuditLimits::default())
            .unwrap();
    let harness = Harness::with_rollouts(ManagementLimits::default(), audit.clone()).await;
    let mut input = start_input(&harness).await;
    input.canary_policy = Some(policy());
    let mut client =
        proto::rollout_service_client::RolloutServiceClient::new(harness.channel.clone());
    assert!(client.start_rollout(request("alice", input)).await.is_err());
    assert!(client
        .get_rollout(request(
            "alice",
            proto::GetRolloutRequest {
                id: "rollout".into()
            }
        ))
        .await
        .unwrap()
        .into_inner()
        .status
        .is_none());
    drop(client);
    harness.shutdown().await;
    audit.close();
    assert!(journal
        .join_until(Instant::now() + Duration::from_secs(5))
        .unwrap());
}
