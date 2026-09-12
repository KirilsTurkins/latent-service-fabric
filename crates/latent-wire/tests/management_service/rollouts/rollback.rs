use super::*;
use latent_routing::RouteResolver;

type Client = proto::rollout_service_client::RolloutServiceClient<tonic::transport::Channel>;

fn change(operation: &str, revision: u64, target_generation: u64) -> proto::ChangeRolloutRequest {
    proto::ChangeRolloutRequest {
        id: "rollout".into(),
        operation: Some(proto::RolloutOperationPrecondition {
            operation_id: operation.into(),
            expected_revision: Some(revision),
        }),
        command: Some(proto::change_rollout_request::Command::Rollback(
            proto::RollbackRollout { target_generation },
        )),
    }
}

async fn status(client: &mut Client) -> proto::RolloutStatus {
    client
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
        .unwrap()
}

#[tokio::test]
#[allow(
    clippy::too_many_lines,
    reason = "one bounded RPC schedule binds authorization, target comparison, receipt and exact replay"
)]
async fn rollback_uses_the_stored_target_and_replays_without_a_canary_owner() {
    let directory = TempDir::new().unwrap();
    let (audit, mut journal) =
        DirectoryPhase2AuditJournal::open(directory.path().join("audit"), AuditLimits::default())
            .unwrap();
    let harness = Harness::with_rollouts(ManagementLimits::default(), audit.clone()).await;
    let input = start_input(&harness).await;
    let original_generation = harness.deployments.generation();
    let mut client = Client::new(harness.channel.clone());
    let started = client
        .start_rollout(request("alice", input))
        .await
        .unwrap()
        .into_inner();
    let started = started.receipt.unwrap();
    assert!(started.rollback_target.is_none());
    let before = status(&mut client).await;
    let target = before.rollback_target.clone().unwrap();
    assert_eq!(target.format_version, 1);
    assert_eq!(target.historical_route_generation, original_generation.0);
    let rollback = change(
        "rollback",
        before.revision,
        target.historical_route_generation,
    );
    for identity in ["caller", "bob"] {
        assert!(client
            .change_rollout(request(identity, rollback.clone()))
            .await
            .is_err());
    }
    let sequence = audit.snapshot().next_sequence;
    assert_eq!(
        client
            .change_rollout(request("alice", change("zero", before.revision, 0)))
            .await
            .unwrap_err()
            .code(),
        Code::InvalidArgument,
    );
    assert_eq!(audit.snapshot().next_sequence, sequence);
    let wrong = client
        .change_rollout(request(
            "alice",
            change(
                "wrong-target",
                before.revision,
                target.historical_route_generation + 1,
            ),
        ))
        .await
        .unwrap_err();
    assert!(wrong.metadata().contains_key("latent-audit-attempt"));
    assert_eq!(
        status(&mut client).await.route_generation,
        before.route_generation
    );
    let applied = client
        .change_rollout(request("alice", rollback.clone()))
        .await
        .unwrap()
        .into_inner();
    assert!(!applied.replayed);
    assert_eq!(
        applied.durability,
        proto::RolloutDurability::Confirmed as i32
    );
    let ack = applied.audit_ack.unwrap();
    assert_eq!(ack.status, proto::AuditAckStatus::Durable as i32);
    let receipt = applied.receipt.unwrap();
    assert_eq!(receipt.rollback_target.as_ref(), Some(&target));
    assert_eq!(receipt.state, proto::RolloutState::RolledBack as i32);
    assert_eq!(receipt.action, proto::RolloutAction::Rollback as i32);
    assert_eq!(receipt.reason, proto::RolloutReason::RollbackApplied as i32);
    assert!(receipt.canary_decision.is_none());
    assert!(receipt.route_generation > before.route_generation);
    assert_eq!(receipt.step, before.current_step);
    let current = status(&mut client).await;
    assert_eq!(current.rollback_target.as_ref(), Some(&target));
    assert_eq!(current.objects.len(), 1);
    assert_eq!(current.objects[0].deployment_id, "base");
    assert_eq!(current.route_generation, receipt.route_generation);
    let repeated = client
        .change_rollout(request("alice", rollback))
        .await
        .unwrap()
        .into_inner();
    assert!(repeated.replayed);
    assert_eq!(repeated.receipt.as_ref(), Some(&receipt));
    assert_eq!(
        status(&mut client).await.route_generation,
        current.route_generation
    );
    check_lookup_and_filter(&mut client, &receipt).await;
    check_audit(
        &harness.channel,
        ack.attempt_sequence.unwrap(),
        &target,
        receipt.route_generation,
    )
    .await;
    drop(client);
    harness.shutdown().await;
    audit.close();
    assert!(journal
        .join_until(Instant::now() + Duration::from_secs(5))
        .unwrap());
}

async fn check_lookup_and_filter(client: &mut Client, receipt: &proto::RolloutOperationReceipt) {
    let lookup = client
        .get_rollout_operation(request(
            "alice",
            proto::GetRolloutOperationRequest {
                id: "rollout".into(),
                operation_id: "rollback".into(),
            },
        ))
        .await
        .unwrap()
        .into_inner();
    assert_eq!(
        lookup.disposition,
        proto::RolloutOperationLookupDisposition::Found as i32
    );
    assert_eq!(lookup.receipt.as_ref(), Some(receipt));
    let listed = client
        .list_rollouts(request(
            "alice",
            proto::ListRolloutsRequest {
                service: Some("echo".into()),
                state: Some(proto::RolloutState::RolledBack as i32),
                page: Some(proto::PageRequest {
                    page_size: 1,
                    page_token: None,
                }),
            },
        ))
        .await
        .unwrap()
        .into_inner();
    assert_eq!(listed.rollouts.len(), 1);
    assert_eq!(listed.rollouts[0].rollback_target, receipt.rollback_target);
    assert!(client
        .change_rollout(request(
            "alice",
            change(
                "new-after-rollback",
                receipt.revision,
                receipt
                    .rollback_target
                    .as_ref()
                    .unwrap()
                    .historical_route_generation,
            )
        ))
        .await
        .is_err());
}

async fn check_audit(
    channel: &tonic::transport::Channel,
    sequence: u64,
    target: &proto::RolloutRollbackTarget,
    new_generation: u64,
) {
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
    let attempt = page
        .records
        .iter()
        .find_map(|record| match &record.data {
            Some(proto::phase2_audit_record::Data::Attempt(value))
                if record.sequence == sequence =>
            {
                Some(value)
            }
            _ => None,
        })
        .unwrap();
    assert_eq!(attempt.action, proto::AuditControlAction::Rollback as i32);
    assert_eq!(
        attempt.expected_rollback_target_generation,
        Some(target.historical_route_generation)
    );
    let conclusion = page
        .records
        .iter()
        .find_map(|record| match &record.data {
            Some(proto::phase2_audit_record::Data::Outcome(value))
                if value.attempt_sequence == sequence =>
            {
                Some(value)
            }
            _ => None,
        })
        .unwrap();
    assert_eq!(
        conclusion.result,
        proto::AuditOperationResult::Committed as i32
    );
    let identities = conclusion.identities.as_ref().unwrap();
    assert_eq!(
        identities.rollback_target_generation,
        Some(target.historical_route_generation)
    );
    assert_eq!(identities.route_generation, Some(new_generation));
    assert!(conclusion.canary_decision.is_none());
}

#[tokio::test]
async fn revoked_target_rejection_has_audit_but_no_rollback_receipt_or_route_change() {
    let directory = TempDir::new().unwrap();
    let (audit, mut journal) =
        DirectoryPhase2AuditJournal::open(directory.path().join("audit"), AuditLimits::default())
            .unwrap();
    let harness = Harness::with_rollouts(ManagementLimits::default(), audit.clone()).await;
    let input = start_input(&harness).await;
    let mut client = Client::new(harness.channel.clone());
    client.start_rollout(request("alice", input)).await.unwrap();
    let before = status(&mut client).await;
    let target = before.rollback_target.as_ref().unwrap();
    let digest = before.base.as_ref().unwrap().component_digest.clone();
    revoke_target(&harness.channel, digest).await;
    let rejected = client
        .change_rollout(request(
            "alice",
            change(
                "revoked-target",
                before.revision,
                target.historical_route_generation,
            ),
        ))
        .await
        .unwrap_err();
    assert!(rejected.metadata().contains_key("latent-audit-attempt"));
    let after = status(&mut client).await;
    assert_eq!(after.revision, before.revision);
    assert_eq!(after.route_generation, before.route_generation);
    assert_eq!(after.objects, before.objects);
    let operation = client
        .get_rollout_operation(request(
            "alice",
            proto::GetRolloutOperationRequest {
                id: "rollout".into(),
                operation_id: "revoked-target".into(),
            },
        ))
        .await
        .unwrap()
        .into_inner();
    assert_eq!(
        operation.disposition,
        proto::RolloutOperationLookupDisposition::Unknown as i32
    );
    assert!(operation.receipt.is_none());
    drop(client);
    harness.shutdown().await;
    audit.close();
    assert!(journal
        .join_until(Instant::now() + Duration::from_secs(5))
        .unwrap());
}

async fn revoke_target(channel: &tonic::transport::Channel, digest: String) {
    let mut client = proto::release_service_client::ReleaseServiceClient::new(channel.clone());
    let generation = client
        .get_release_lifecycle(request(
            "alice",
            proto::GetReleaseLifecycleRequest {
                digest: digest.clone(),
            },
        ))
        .await
        .unwrap()
        .into_inner()
        .status
        .unwrap()
        .record
        .unwrap()
        .generation;
    let revoked = client
        .change_release_lifecycle(request(
            "alice",
            proto::ChangeReleaseLifecycleRequest {
                digest,
                action: proto::ReleaseLifecycleAction::Revoke as i32,
                operation: Some(proto::ReleaseOperationPrecondition {
                    operation_id: "revoke-rollback-target".into(),
                    expected_generation: Some(generation),
                }),
                reason: proto::ReleaseLifecycleReason::OperatorRevocation as i32,
            },
        ))
        .await
        .unwrap()
        .into_inner();
    assert_eq!(
        revoked.operation.unwrap().disposition,
        proto::ReleaseOperationDisposition::Committed as i32
    );
}
