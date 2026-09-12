use super::support::{artifact, deployment, request, Harness};
use latent_artifacts::ArtifactRepository;
use latent_audit::{AuditLimits, DirectoryPhase2AuditJournal};
use latent_control_store::DeploymentStore;
use latent_core::TenantId;
use latent_wire::management::{deployment_manifest_from_proto, proto, ManagementLimits};
use std::time::{Duration, Instant};
use tempfile::TempDir;
use tonic::Code;

#[path = "rollouts/canary.rs"]
mod canary;

async fn start_input(harness: &Harness) -> proto::StartRolloutRequest {
    let base = harness
        .artifacts
        .publish(artifact("acme", "echo", "base"))
        .await
        .unwrap();
    let candidate = harness
        .artifacts
        .publish(artifact("acme", "echo", "candidate"))
        .await
        .unwrap();
    let base = deployment("base", "acme", "echo", &base.release_digest);
    let receipt = harness
        .deployments
        .apply_versioned(
            &TenantId("acme".into()),
            deployment_manifest_from_proto(base).unwrap(),
            Some(0),
        )
        .await
        .unwrap();
    let mut candidate = deployment("candidate", "acme", "echo", &candidate.release_digest);
    candidate.route_weight = 1000;
    proto::StartRolloutRequest {
        id: "rollout".into(),
        base_deployment_id: "base".into(),
        expected_base_generation: Some(receipt.deployment.generation),
        candidate: Some(candidate),
        candidate_weights: vec![1000, 10_000],
        canary_policy: None,
        operation: Some(proto::RolloutOperationPrecondition {
            operation_id: "start".into(),
            expected_revision: Some(0),
        }),
    }
}

#[tokio::test]
async fn manual_rpc_receipts_replay_exactly_and_queries_never_cross_tenants() {
    let directory = TempDir::new().unwrap();
    let (audit, mut journal) =
        DirectoryPhase2AuditJournal::open(directory.path().join("audit"), AuditLimits::default())
            .unwrap();
    let harness = Harness::with_rollouts(ManagementLimits::default(), audit.clone()).await;
    let input = start_input(&harness).await;
    let mut client =
        proto::rollout_service_client::RolloutServiceClient::new(harness.channel.clone());
    assert_eq!(
        client
            .start_rollout(request("caller", input.clone()))
            .await
            .unwrap_err()
            .code(),
        Code::PermissionDenied
    );
    assert_eq!(
        client
            .start_rollout(request("bob", input.clone()))
            .await
            .unwrap_err()
            .code(),
        Code::PermissionDenied
    );
    let started = client
        .start_rollout(request("alice", input.clone()))
        .await
        .unwrap()
        .into_inner();
    assert_eq!(
        started.durability,
        proto::RolloutDurability::Confirmed as i32
    );
    assert_eq!(
        started.audit_ack.as_ref().unwrap().status,
        proto::AuditAckStatus::Durable as i32
    );
    assert!(!started.replayed);
    let replay = client
        .start_rollout(request("alice", input))
        .await
        .unwrap()
        .into_inner();
    assert!(replay.replayed);
    assert_eq!(replay.receipt, started.receipt);
    let first = started.receipt.unwrap();
    assert!(client
        .get_rollout(request(
            "bob",
            proto::GetRolloutRequest {
                id: "rollout".into()
            }
        ))
        .await
        .unwrap()
        .into_inner()
        .status
        .is_none());
    let hidden = client
        .get_rollout_operation(request(
            "bob",
            proto::GetRolloutOperationRequest {
                id: "rollout".into(),
                operation_id: "start".into(),
            },
        ))
        .await
        .unwrap()
        .into_inner();
    assert_eq!(
        hidden.disposition,
        proto::RolloutOperationLookupDisposition::Unknown as i32
    );
    let paused = client
        .change_rollout(request(
            "alice",
            proto::ChangeRolloutRequest {
                id: "rollout".into(),
                operation: Some(proto::RolloutOperationPrecondition {
                    operation_id: "pause".into(),
                    expected_revision: Some(first.revision),
                }),
                command: Some(proto::change_rollout_request::Command::Pause(
                    proto::Empty {},
                )),
            },
        ))
        .await
        .unwrap()
        .into_inner()
        .receipt
        .unwrap();
    assert_eq!(paused.state, proto::RolloutState::Paused as i32);
    assert_eq!(paused.route_generation, first.route_generation);
    assert!(paused.state_version > first.state_version);
    assert_eq!(
        client
            .change_rollout(request(
                "alice",
                proto::ChangeRolloutRequest {
                    id: "rollout".into(),
                    operation: Some(proto::RolloutOperationPrecondition {
                        operation_id: "stale".into(),
                        expected_revision: Some(first.revision)
                    }),
                    command: Some(proto::change_rollout_request::Command::Abort(
                        proto::Empty {}
                    )),
                }
            ))
            .await
            .unwrap_err()
            .code(),
        Code::Aborted
    );
    drop(client);
    harness.shutdown().await;
    audit.close();
    assert!(journal
        .join_until(Instant::now() + Duration::from_secs(5))
        .unwrap());
}

#[tokio::test]
async fn insufficient_receipt_budget_fails_before_catalog_or_audit_acceptance() {
    let directory = TempDir::new().unwrap();
    let (audit, mut journal) =
        DirectoryPhase2AuditJournal::open(directory.path().join("audit"), AuditLimits::default())
            .unwrap();
    let harness = Harness::with_rollouts(
        ManagementLimits {
            max_response_bytes: 512,
            max_metadata_bytes: 512,
            max_string_bytes: 512,
            max_page_token_bytes: 512,
            max_collection_entries: 512,
            max_route_services: 512,
            max_route_revisions: 512,
            ..ManagementLimits::default()
        },
        audit.clone(),
    )
    .await;
    let input = start_input(&harness).await;
    let before = audit.snapshot();
    let mut client =
        proto::rollout_service_client::RolloutServiceClient::new(harness.channel.clone());
    assert_eq!(
        client
            .start_rollout(request("alice", input))
            .await
            .unwrap_err()
            .code(),
        Code::ResourceExhausted
    );
    assert!(harness
        .deployments
        .get_rollout(
            &TenantId("acme".into()),
            &latent_control_store::rollouts::RolloutId("rollout".into())
        )
        .unwrap()
        .is_none());
    assert_eq!(audit.snapshot().pending_attempts, before.pending_attempts);
    assert_eq!(audit.snapshot().next_sequence, before.next_sequence);
    drop(client);
    harness.shutdown().await;
    audit.close();
    assert!(journal
        .join_until(Instant::now() + Duration::from_secs(5))
        .unwrap());
}

#[tokio::test]
async fn disabled_rollouts_still_authenticate_before_unimplemented() {
    let harness = Harness::new(ManagementLimits::default()).await;
    let mut client =
        proto::rollout_service_client::RolloutServiceClient::new(harness.channel.clone());
    for (identity, code) in [
        ("caller", Code::PermissionDenied),
        ("alice", Code::Unimplemented),
    ] {
        assert_eq!(
            client
                .get_rollout(request(
                    identity,
                    proto::GetRolloutRequest {
                        id: "rollout".into()
                    }
                ))
                .await
                .unwrap_err()
                .code(),
            code
        );
    }
    drop(client);
    harness.shutdown().await;
}
