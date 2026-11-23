use super::*;
use latent_core::{ActivationClock, ClockSample};
use latent_telemetry::{BoundedPhase2CanaryOutcomeWindow, Phase2CanaryOutcomeWindowConfig};
use prost::Message;
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
    let client = proto::audit_service_client::AuditServiceClient::new(channel.clone());
    let query = proto::QueryPhase2AuditRequest {
        scope: Some(proto::AuditQueryScope {
            kind: proto::AuditScopeKind::Tenant as i32,
            tenant: Some("acme".into()),
        }),
        filter: None,
        page: Some(proto::PageRequest {
            page_size: 32,
            page_token: None,
        }),
    };
    let page = observe_audit_query(Instant::now() + Duration::from_secs(2), |remaining| {
        let mut client = client.clone();
        let mut query = request("alice", query.clone());
        query.set_timeout(remaining);
        async move { client.query_phase2_audit(query).await }
    })
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

// Only this read-only observation retries the journal's documented short
// bookkeeping contention. Never repeat the promotion, wait for a missing row,
// or turn other capacity/storage errors into success. All attempts, including
// an in-flight RPC, share one original deadline.
async fn observe_audit_query<T, F, Q>(deadline: Instant, mut query: F) -> Result<T, tonic::Status>
where
    F: FnMut(Duration) -> Q,
    Q: std::future::Future<Output = Result<T, tonic::Status>>,
{
    loop {
        let remaining = deadline
            .checked_duration_since(Instant::now())
            .filter(|remaining| !remaining.is_zero())
            .ok_or_else(|| tonic::Status::deadline_exceeded("audit observation expired"))?;
        let result = tokio::time::timeout(remaining, query(remaining))
            .await
            .map_err(|_| tonic::Status::deadline_exceeded("audit observation expired"))?;
        match result {
            Err(status) if audit_query_busy(&status) => tokio::task::yield_now().await,
            result => return result,
        }
    }
}

fn audit_query_busy(status: &tonic::Status) -> bool {
    if status.code() != Code::ResourceExhausted {
        return false;
    }
    let Ok(error) = proto::PlatformError::decode(status.details()) else {
        return false;
    };
    error.code == "resource-exhausted"
        && error.detail_items.len() == 1
        && error.detail_items[0].kind == "audit-journal"
        && error.detail_items[0].fields.len() == 1
        && error.detail_items[0]
            .fields
            .get("reason")
            .map(String::as_str)
            == Some("audit-busy")
}

fn audit_status(reason: &str) -> tonic::Status {
    let error = proto::PlatformError {
        code: "resource-exhausted".into(),
        message: "management data exceeds an available resource limit".into(),
        retryable: false,
        detail_items: vec![proto::ErrorDetail {
            kind: "audit-journal".into(),
            fields: [("reason".into(), reason.into())].into(),
        }],
    };
    tonic::Status::with_details(
        Code::ResourceExhausted,
        error.message.clone(),
        error.encode_to_vec().into(),
    )
}

#[tokio::test]
async fn audit_observation_retries_only_structured_busy_and_returns_first_page() {
    let mut attempts = 0;
    let mut previous = Duration::from_secs(2);
    let page: Vec<u8> = observe_audit_query(Instant::now() + previous, |remaining| {
        assert!(remaining <= previous);
        previous = remaining;
        attempts += 1;
        std::future::ready(if attempts == 1 {
            Err(audit_status("audit-busy"))
        } else {
            // Even a page missing the sought outcome must be returned at once;
            // the caller's unchanged assertion checks durable acknowledgement.
            Ok(Vec::new())
        })
    })
    .await
    .unwrap();
    assert!(page.is_empty());
    assert_eq!(attempts, 2);
    for status in [
        audit_status("audit-capacity"),
        audit_status("audit-critical-pending"),
        audit_status("audit-unavailable"),
        tonic::Status::resource_exhausted("audit-busy"),
        tonic::Status::with_details(
            Code::PermissionDenied,
            "audit-busy",
            audit_status("audit-busy").details().to_vec().into(),
        ),
        tonic::Status::with_details(Code::ResourceExhausted, "audit-busy", vec![255].into()),
    ] {
        let mut calls = 0;
        let query = |_| {
            calls += 1;
            std::future::ready(Err::<(), _>(status.clone()))
        };
        let error = observe_audit_query(Instant::now() + Duration::from_secs(2), query)
            .await
            .unwrap_err();
        assert_eq!(calls, 1);
        assert_eq!(error.code(), status.code());
        assert_eq!(error.details(), status.details());
    }
}

#[tokio::test]
async fn audit_observation_deadline_prevents_dispatch_and_bounds_inflight_rpc() {
    let mut attempts = 0;
    let expired = observe_audit_query::<(), _, _>(Instant::now(), |_| {
        attempts += 1;
        std::future::ready(Ok(()))
    })
    .await
    .unwrap_err();
    assert_eq!(expired.code(), Code::DeadlineExceeded);
    assert_eq!(attempts, 0);
    let query = |_| {
        attempts += 1;
        std::future::pending::<Result<(), tonic::Status>>()
    };
    let expired = observe_audit_query(Instant::now() + Duration::from_millis(10), query)
        .await
        .unwrap_err();
    assert_eq!(attempts, 1);
    assert_eq!(expired.code(), Code::DeadlineExceeded);
}
