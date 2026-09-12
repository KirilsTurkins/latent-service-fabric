use super::super::support::{artifact, deployment, request, Harness};
use latent_artifacts::ArtifactRepository;
use latent_audit::{AuditLimits, DirectoryPhase2AuditJournal};
use latent_wire::management::{proto, ManagementLimits};
use std::time::{Duration, Instant};
use tempfile::TempDir;
use tonic::Code;

fn operation(id: &str, state: u64) -> Option<proto::DeploymentOperationPrecondition> {
    Some(proto::DeploymentOperationPrecondition {
        operation_id: id.into(),
        expected_state_version: Some(state),
    })
}
async fn snapshot(harness: &Harness, tenant: &str) -> proto::GetDeploymentResponse {
    harness
        .deployments_client()
        .get_deployment(request(
            tenant,
            proto::GetDeploymentRequest {
                id: "ship".into(),
                include_operation_snapshot: true,
            },
        ))
        .await
        .unwrap()
        .into_inner()
}

#[tokio::test]
#[allow(
    clippy::too_many_lines,
    reason = "one RPC schedule keeps historical replay, removal and receipt identity assertions together"
)]
async fn managed_apply_delete_and_exact_replay_preserve_original_receipts() {
    let directory = TempDir::new().unwrap();
    let (audit, mut journal) =
        DirectoryPhase2AuditJournal::open(directory.path().join("audit"), AuditLimits::default())
            .unwrap();
    let harness = Harness::with_audit(ManagementLimits::default(), None, Some(audit.clone())).await;
    let release = harness
        .artifacts
        .publish(artifact("acme", "echo", "managed"))
        .await
        .unwrap();
    let before = snapshot(&harness, "alice").await;
    assert!(before.deployment.is_none());
    assert_eq!(before.state_version, Some(0));
    assert_eq!(before.route_generation, Some(0));
    assert_eq!(
        before.durability,
        Some(proto::DeploymentDurability::Confirmed as i32)
    );
    let input = proto::ApplyDeploymentRequest {
        deployment: Some(deployment("ship", "acme", "echo", &release.release_digest)),
        expected_generation: Some(0),
        operation: operation("create", 0),
    };
    for identity in ["bob", "caller"] {
        assert_eq!(
            harness
                .deployments_client()
                .apply_deployment(request(identity, input.clone()))
                .await
                .unwrap_err()
                .code(),
            Code::PermissionDenied
        );
    }
    let applied = harness
        .deployments_client()
        .apply_deployment(request("alice", input.clone()))
        .await
        .unwrap()
        .into_inner();
    assert!(!applied.replayed);
    assert_eq!(
        applied.durability,
        proto::DeploymentDurability::Confirmed as i32
    );
    assert!(applied
        .audit_ack
        .as_ref()
        .unwrap()
        .attempt_sequence
        .is_some());
    let receipt = applied.receipt.as_ref().unwrap();
    assert_eq!(receipt.actor.as_ref().unwrap().subject, "alice");
    assert_eq!(receipt.expected_state_version, 0);
    assert_eq!(receipt.expected_generation, 0);
    assert_eq!(
        receipt.object_generation,
        applied.deployment.as_ref().unwrap().generation
    );
    let current = snapshot(&harness, "alice").await;
    assert_eq!(current.state_version, Some(receipt.state_version));
    // An unrelated writer makes the global precondition stale even for a new ID.
    let mut stale = input.clone();
    stale.operation = operation("stale", 0);
    assert_eq!(
        harness
            .deployments_client()
            .apply_deployment(request("alice", stale))
            .await
            .unwrap_err()
            .code(),
        Code::Aborted
    );
    let delete_id = "delete-é";
    let deleted = harness
        .deployments_client()
        .delete_deployment(request(
            "alice",
            proto::DeleteDeploymentRequest {
                id: "ship".into(),
                expected_generation: Some(receipt.object_generation),
                operation: operation(delete_id, receipt.state_version),
            },
        ))
        .await
        .unwrap();
    assert_eq!(
        deleted
            .metadata()
            .get_bin("latent-deployment-operation-bin")
            .unwrap()
            .to_bytes()
            .unwrap()
            .as_ref(),
        delete_id.as_bytes()
    );
    assert_eq!(
        deleted
            .metadata()
            .get("latent-deployment-durability")
            .unwrap(),
        "confirmed"
    );
    let after = snapshot(&harness, "alice").await;
    assert!(after.deployment.is_none());
    assert!(after.state_version.unwrap() > receipt.state_version);
    let replay = harness
        .deployments_client()
        .apply_deployment(request("alice", input))
        .await
        .unwrap()
        .into_inner();
    assert!(replay.replayed);
    assert_eq!(replay.receipt, applied.receipt);
    assert_eq!(replay.deployment, applied.deployment);
    assert!(snapshot(&harness, "alice").await.deployment.is_none());
    for (identity, id, found) in [
        ("alice", "create", true),
        ("alice", delete_id, true),
        ("bob", "create", false),
    ] {
        let lookup = harness
            .deployments_client()
            .get_deployment_operation(request(
                identity,
                proto::GetDeploymentOperationRequest {
                    operation_id: id.into(),
                },
            ))
            .await
            .unwrap()
            .into_inner();
        assert_eq!(
            lookup.disposition,
            if found {
                proto::DeploymentOperationLookupDisposition::Found
            } else {
                proto::DeploymentOperationLookupDisposition::Unknown
            } as i32
        );
        if found {
            assert_eq!(lookup.receipt.unwrap().operation_id, id);
        } else {
            assert!(lookup.receipt.is_none());
        }
    }
    harness.shutdown().await;
    audit.close();
    assert!(journal
        .join_until(Instant::now() + Duration::from_secs(5))
        .unwrap());
}

#[tokio::test]
async fn managed_requires_audit_and_response_capacity_before_any_catalog_effect() {
    for (audited, maximum) in [
        (false, ManagementLimits::default().max_response_bytes),
        (true, 256 * 1024),
    ] {
        let directory = TempDir::new().unwrap();
        let (audit, mut journal) = DirectoryPhase2AuditJournal::open(
            directory.path().join("audit"),
            AuditLimits::default(),
        )
        .unwrap();
        let harness = Harness::with_audit(
            ManagementLimits {
                max_response_bytes: maximum,
                ..ManagementLimits::default()
            },
            None,
            audited.then(|| audit.clone()),
        )
        .await;
        let release = harness
            .artifacts
            .publish(artifact("acme", "echo", "preflight"))
            .await
            .unwrap();
        let denied = harness
            .deployments_client()
            .apply_deployment(request(
                "alice",
                proto::ApplyDeploymentRequest {
                    deployment: Some(deployment("ship", "acme", "echo", &release.release_digest)),
                    expected_generation: Some(0),
                    operation: operation("blocked", 0),
                },
            ))
            .await
            .unwrap_err();
        assert_eq!(
            denied.code(),
            if audited {
                Code::ResourceExhausted
            } else {
                Code::Unimplemented
            }
        );
        assert_eq!(snapshot(&harness, "alice").await.state_version, Some(0));
        assert_eq!(audit.snapshot().next_sequence, 1);
        harness.shutdown().await;
        audit.close();
        assert!(journal
            .join_until(Instant::now() + Duration::from_secs(5))
            .unwrap());
    }
}
