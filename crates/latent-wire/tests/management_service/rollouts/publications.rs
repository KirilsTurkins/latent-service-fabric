use super::super::support::publish_variant;
use super::*;
use latent_core::ReleaseDigest;
use latent_routing::RouteResolver;

fn exact(
    id: &str,
    publication: &proto::PublicationRef,
    _digest: &ReleaseDigest,
    weight: u32,
) -> proto::Deployment {
    let mut value = deployment(id, "acme", "echo", publication);
    value.route_weight = weight;
    value
}
fn change(
    id: &str,
    revision: u64,
    command: proto::change_rollout_request::Command,
) -> proto::ChangeRolloutRequest {
    proto::ChangeRolloutRequest {
        id: "coexist".into(),
        operation: Some(proto::RolloutOperationPrecondition {
            operation_id: id.into(),
            expected_revision: Some(revision),
        }),
        command: Some(command),
    }
}

#[tokio::test]
#[allow(
    clippy::too_many_lines,
    reason = "one bounded RPC history keeps exact selection, rollback and replay assertions together"
)]
async fn same_component_rollout_exposes_captured_pair_and_rolls_back_after_candidate_revocation() {
    let directory = TempDir::new().unwrap();
    let (audit, mut journal) =
        DirectoryPhase2AuditJournal::open(directory.path().join("audit"), AuditLimits::default())
            .unwrap();
    let harness = Harness::with_rollouts(ManagementLimits::default(), audit.clone()).await;
    let (first, component) = publish_variant(&harness, "acme", "1.0.0").await;
    let (second, shared) = publish_variant(&harness, "acme", "1.0.1").await;
    assert_eq!(component, shared);
    let base = harness
        .deployments_client()
        .apply_deployment(request(
            "alice",
            proto::ApplyDeploymentRequest {
                deployment: Some(exact("base", &first, &component, 10000)),
                expected_generation: Some(0),
                expected_component_digest: Some(component.0.clone()),
                operation: None,
            },
        ))
        .await
        .unwrap()
        .into_inner()
        .deployment
        .unwrap();
    let input = proto::StartRolloutRequest {
        id: "coexist".into(),
        base_deployment_id: "base".into(),
        expected_base_generation: Some(base.generation),
        candidate: Some(exact("candidate", &second, &component, 5000)),
        expected_candidate_component_digest: Some(component.0.clone()),
        candidate_weights: vec![5000, 10000],
        canary_policy: None,
        operation: Some(proto::RolloutOperationPrecondition {
            operation_id: "start".into(),
            expected_revision: Some(0),
        }),
    };
    let mut client =
        proto::rollout_service_client::RolloutServiceClient::new(harness.channel.clone());
    let before = audit.snapshot().next_sequence;
    for mutation in 0..4 {
        let mut changed = input.clone();
        let candidate = changed.candidate.as_mut().unwrap();
        match mutation {
            0 => candidate.release_digest = component.0.clone(),
            1 => candidate.requested_publication = candidate.publication.clone(),
            2 => {
                changed.expected_candidate_component_digest =
                    Some(format!("sha256:{}", "0".repeat(64)))
            }
            3 => candidate.publication.as_mut().unwrap().tenant = "other".into(),
            _ => unreachable!(),
        }
        assert_eq!(
            client
                .start_rollout(request("alice", changed))
                .await
                .unwrap_err()
                .code(),
            Code::InvalidArgument
        );
    }
    assert_eq!(harness.deployments.generation().0, base.generation);
    assert_eq!(audit.snapshot().next_sequence, before);
    let started = client
        .start_rollout(request("alice", input.clone()))
        .await
        .unwrap()
        .into_inner();
    let original = started.receipt.unwrap();
    assert_eq!(original.base_publication_id.as_ref(), Some(&first.id));
    assert_eq!(original.candidate_publication_id.as_ref(), Some(&second.id));
    let status = client
        .get_rollout(request(
            "alice",
            proto::GetRolloutRequest {
                id: "coexist".into(),
            },
        ))
        .await
        .unwrap()
        .into_inner()
        .status
        .unwrap();
    assert_eq!(status.base.as_ref().unwrap().component_digest, component.0);
    assert_eq!(
        status.candidate.as_ref().unwrap().component_digest,
        component.0
    );
    assert_eq!(
        status.base.as_ref().unwrap().publication_id.as_ref(),
        Some(&first.id)
    );
    assert_eq!(
        status.candidate.as_ref().unwrap().publication_id.as_ref(),
        Some(&second.id)
    );
    let completed = client
        .change_rollout(request(
            "alice",
            change(
                "finish",
                original.revision,
                proto::change_rollout_request::Command::Advance(proto::AdvanceRollout {
                    next_step: 1,
                }),
            ),
        ))
        .await
        .unwrap()
        .into_inner()
        .receipt
        .unwrap();
    harness
        .releases_client()
        .change_release_lifecycle(request(
            "alice",
            proto::ChangeReleaseLifecycleRequest {
                publication: Some(second.clone()),
                action: proto::ReleaseLifecycleAction::Revoke as i32,
                reason: proto::ReleaseLifecycleReason::OperatorRevocation as i32,
                operation: Some(proto::ReleaseOperationPrecondition {
                    operation_id: "revoke-candidate".into(),
                    expected_generation: Some(1),
                }),
            },
        ))
        .await
        .unwrap();
    let rolled_back = client
        .change_rollout(request(
            "alice",
            change(
                "rollback",
                completed.revision,
                proto::change_rollout_request::Command::Rollback(proto::RollbackRollout {
                    target_generation: base.generation,
                }),
            ),
        ))
        .await
        .unwrap()
        .into_inner();
    let receipt = rolled_back.receipt.unwrap();
    assert_eq!(receipt.state, proto::RolloutState::RolledBack as i32);
    assert_eq!(receipt.base_publication_id.as_ref(), Some(&first.id));
    assert_eq!(receipt.candidate_publication_id.as_ref(), Some(&second.id));
    let replay = client
        .start_rollout(request("alice", input))
        .await
        .unwrap()
        .into_inner();
    assert!(replay.replayed);
    assert_eq!(replay.receipt.as_ref(), Some(&original));
    let restored = harness
        .deployments_client()
        .get_deployment(request(
            "alice",
            proto::GetDeploymentRequest {
                id: "base".into(),
                include_operation_snapshot: false,
            },
        ))
        .await
        .unwrap()
        .into_inner()
        .deployment
        .unwrap();
    assert_eq!(restored.publication, Some(first.clone()));
    assert!(restored.generation > base.generation);
    let page = proto::audit_service_client::AuditServiceClient::new(harness.channel.clone())
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
    let mut rollout_records = 0;
    for record in page.records {
        let identities = match record.data {
            Some(proto::phase2_audit_record::Data::Attempt(value)) => value.identities,
            Some(proto::phase2_audit_record::Data::Outcome(value)) => value.identities,
            _ => None,
        };
        if let Some(identities) =
            identities.filter(|value| value.rollout.as_deref() == Some("coexist"))
        {
            assert_eq!(identities.base_publication_id.as_ref(), Some(&first.id));
            assert_eq!(
                identities.candidate_publication_id.as_ref(),
                Some(&second.id)
            );
            rollout_records += 1;
        }
    }
    assert_eq!(rollout_records, 8);
    drop(client);
    harness.shutdown().await;
    audit.close();
    assert!(journal
        .join_until(Instant::now() + Duration::from_secs(5))
        .unwrap());
}
