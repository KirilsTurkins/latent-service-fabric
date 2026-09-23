use super::support::{artifact, deployment, request, Harness};
use latent_artifacts::{
    ArtifactRepository, LifecycleScope, ManagedPublicationUpload, ReleaseActor, ReleaseActorKind,
    ReleaseMutationContext, ReleaseOperationPrecondition,
};
use latent_audit::{AuditLimits, DirectoryPhase2AuditJournal};
use latent_control_store::DeploymentStore;
use latent_core::{ContractId, FunctionId, InterfaceId, TenantId};
use latent_routing::{InvocationTarget, RouteResolver};
use latent_wire::management::{deployment_manifest_from_proto, proto, ManagementLimits};
use std::time::{Duration, Instant};
use tempfile::TempDir;
use tonic::{transport::Channel, Code};

#[cfg(unix)]
#[path = "triggers/audit_recovery.rs"]
mod audit_recovery;

fn client(h: &Harness) -> proto::trigger_service_client::TriggerServiceClient<Channel> {
    proto::trigger_service_client::TriggerServiceClient::new(h.channel.clone())
}
#[expect(
    clippy::unnecessary_wraps,
    reason = "fixture creates the optional protobuf precondition directly"
)]
fn operation(id: &str, state: u64) -> Option<proto::TriggerOperationPrecondition> {
    Some(proto::TriggerOperationPrecondition {
        operation_id: id.into(),
        expected_state_version: Some(state),
    })
}
async fn setup(h: &Harness) -> proto::ApplyTriggerRequest {
    let mut artifact = artifact("acme", "web", "web-trigger");
    let contract = ContractId("latent:web/application@0.1.0".into());
    artifact.manifest.exports[0].contract = contract.clone();
    artifact.contracts[0].id = contract.clone();
    artifact.contracts[0].package_name = "latent:web".into();
    artifact.contracts[0].semantic_version = "0.1.0".into();
    artifact.contracts[0].interfaces[0].id = InterfaceId(contract.0.clone());
    artifact.contracts[0].interfaces[0].functions[0].id = FunctionId("handle".into());
    artifact.contracts[0].interfaces[0].functions[0].name = "handle".into();
    artifact.contracts[0].interfaces[0].functions[0].asynchronous = true;
    let p = h
        .artifacts
        .publish_managed(
            ReleaseMutationContext {
                scope: LifecycleScope::Tenant(TenantId("acme".into())),
                actor: ReleaseActor {
                    subject: "fixture".into(),
                    kind: ReleaseActorKind::Host,
                },
                operation: Some(ReleaseOperationPrecondition {
                    operation_id: "web".into(),
                    expected_generation: 0,
                }),
            },
            ManagedPublicationUpload::Local(artifact),
            &mut |_| Ok(()),
        )
        .await
        .unwrap();
    let mut d = deployment(
        "web",
        "acme",
        "web",
        &proto::PublicationRef {
            id: p.publication.id.as_str().into(),
            tenant: "acme".into(),
        },
    );
    d.release_digest = p.release.descriptor.release_digest.0.clone();
    h.deployments
        .apply(deployment_manifest_from_proto(d).unwrap())
        .await
        .unwrap();
    let target = InvocationTarget {
        tenant: TenantId("acme".into()),
        service: latent_core::ServiceId("web".into()),
        contract: contract.clone(),
        function: FunctionId("handle".into()),
        route: Some("web".into()),
    };
    let selected = h.deployments.resolve(&target, None).unwrap();
    proto::ApplyTriggerRequest {
        trigger: Some(proto::Trigger {
            id: "browser".into(),
            kind: "HttpTrigger".into(),
            generation: 0,
            metadata: Some(proto::ObjectMetadata {
                name: "browser".into(),
                tenant: Some("acme".into()),
                ..Default::default()
            }),
            target: Some(proto::TriggerTarget {
                service: "web".into(),
                contract: contract.0,
                function: "handle".into(),
                route: Some("web".into()),
                publication: Some(proto::PublicationRef {
                    id: p.publication.id.into_string(),
                    tenant: "acme".into(),
                }),
                revision: Some(selected.revision.0),
                deployment_generation: Some(1),
                kind: proto::TriggerTargetKind::Application as i32,
            }),
            configuration: [
                ("profile", "buffered-v1"),
                ("scheme", "https"),
                ("host", "ACME.EXAMPLE.TEST:443"),
                ("path", "/"),
                ("pathMatch", "prefix"),
                ("method", "GET"),
            ]
            .into_iter()
            .map(|(k, v)| (k.into(), v.into()))
            .collect(),
        }),
        expected_generation: Some(0),
        operation: operation("create", 1),
    }
}

#[tokio::test]
#[expect(
    clippy::too_many_lines,
    reason = "one authenticated RPC schedule checks atomic changes, retained replay and exact audit associations"
)]
async fn trigger_rpc_authentication_atomic_crud_receipts_and_audit() {
    let dir = TempDir::new().unwrap();
    let (audit, mut journal) =
        DirectoryPhase2AuditJournal::open(dir.path().join("audit"), AuditLimits::default())
            .unwrap();
    let harness = Harness::with_audit(ManagementLimits::default(), None, Some(audit.clone())).await;
    let input = setup(&harness).await;
    for (identity, code) in [
        ("absent", Code::Unauthenticated),
        ("caller", Code::PermissionDenied),
        ("bob", Code::PermissionDenied),
    ] {
        let mut forged = request(identity, input.clone());
        forged
            .metadata_mut()
            .insert("latent-tenant", "acme".parse().unwrap());
        forged
            .metadata_mut()
            .insert("latent-principal-kind", "administrator".parse().unwrap());
        assert_eq!(
            client(&harness)
                .apply_trigger(forged)
                .await
                .unwrap_err()
                .code(),
            code
        );
    }
    let created = client(&harness)
        .apply_trigger(request("alice", input.clone()))
        .await
        .unwrap()
        .into_inner();
    assert_eq!(
        created.audit_ack.as_ref().unwrap().status,
        proto::AuditAckStatus::Durable as i32
    );
    let receipt = created.receipt.as_ref().unwrap();
    assert_eq!(receipt.actor.as_ref().unwrap().subject, "alice");
    assert_eq!(receipt.tenant, "acme");
    assert_eq!(
        created.trigger.as_ref().unwrap().configuration["host"],
        "acme.example.test"
    );
    let current = client(&harness)
        .get_trigger(request(
            "alice",
            proto::GetTriggerRequest {
                id: "browser".into(),
            },
        ))
        .await
        .unwrap()
        .into_inner();
    assert_eq!(current.trigger, created.trigger);
    assert_eq!(current.state_version, receipt.state_version);
    assert!(client(&harness)
        .get_trigger(request(
            "bob",
            proto::GetTriggerRequest {
                id: "browser".into()
            }
        ))
        .await
        .unwrap()
        .into_inner()
        .trigger
        .is_none());
    let page = client(&harness)
        .list_triggers(request("alice", proto::ListTriggersRequest::default()))
        .await
        .unwrap()
        .into_inner();
    assert_eq!(page.triggers.len(), 1);
    let mut stale = input.clone();
    stale.operation = operation("stale", 1);
    assert_eq!(
        client(&harness)
            .apply_trigger(request("alice", stale))
            .await
            .unwrap_err()
            .code(),
        Code::Aborted
    );
    let removed = client(&harness)
        .delete_trigger(request(
            "alice",
            proto::DeleteTriggerRequest {
                id: "browser".into(),
                expected_generation: Some(receipt.object_generation),
                operation: operation("delete", receipt.state_version),
            },
        ))
        .await
        .unwrap();
    assert_eq!(
        removed.metadata().get("latent-trigger-durability").unwrap(),
        "confirmed"
    );
    assert_eq!(
        removed.metadata().get("latent-audit-status").unwrap(),
        "durable"
    );
    assert!(client(&harness)
        .get_trigger(request(
            "alice",
            proto::GetTriggerRequest {
                id: "browser".into()
            }
        ))
        .await
        .unwrap()
        .into_inner()
        .trigger
        .is_none());
    let replay = client(&harness)
        .apply_trigger(request("alice", input))
        .await
        .unwrap()
        .into_inner();
    assert!(replay.replayed);
    assert_eq!(replay.receipt, created.receipt);
    assert!(client(&harness)
        .get_trigger(request(
            "alice",
            proto::GetTriggerRequest {
                id: "browser".into()
            }
        ))
        .await
        .unwrap()
        .into_inner()
        .trigger
        .is_none());
    for (identity, found) in [("alice", true), ("bob", false)] {
        let lookup = client(&harness)
            .get_trigger_operation(request(
                identity,
                proto::GetTriggerOperationRequest {
                    operation_id: "create".into(),
                },
            ))
            .await
            .unwrap()
            .into_inner();
        assert_eq!(lookup.receipt.is_some(), found);
        if found {
            assert_eq!(lookup.receipt, created.receipt);
        }
    }
    let records = proto::audit_service_client::AuditServiceClient::new(harness.channel.clone())
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
    assert!(records.records.iter().any(|row|matches!(&row.data,Some(proto::phase2_audit_record::Data::Attempt(a)) if a.action==proto::AuditControlAction::TriggerApply as i32 && a.identities.as_ref().unwrap().trigger.as_deref()==Some("browser"))));
    assert!(records.records.iter().any(|row|matches!(&row.data,Some(proto::phase2_audit_record::Data::Attempt(a)) if a.action==proto::AuditControlAction::TriggerDelete as i32)));
    harness.shutdown().await;
    audit.close();
    assert!(journal
        .join_until(Instant::now() + Duration::from_secs(5))
        .unwrap());
}

#[tokio::test]
async fn trigger_rpc_requires_audit_and_preflights_response_capacity_before_commit() {
    for (enabled, maximum, expected) in [
        (false, 4 * 1024 * 1024, Code::Unimplemented),
        (true, 256 * 1024, Code::ResourceExhausted),
    ] {
        let dir = TempDir::new().unwrap();
        let (audit, mut journal) =
            DirectoryPhase2AuditJournal::open(dir.path().join("audit"), AuditLimits::default())
                .unwrap();
        let h = Harness::with_audit(
            ManagementLimits {
                max_response_bytes: maximum,
                ..Default::default()
            },
            None,
            enabled.then(|| audit.clone()),
        )
        .await;
        let input = setup(&h).await;
        assert_eq!(
            client(&h)
                .apply_trigger(request("alice", input))
                .await
                .unwrap_err()
                .code(),
            expected
        );
        let snapshot = h
            .deployments
            .get_trigger(
                &TenantId("acme".into()),
                &latent_core::TriggerId("browser".into()),
            )
            .unwrap();
        assert!(snapshot.value().trigger.is_none());
        assert_eq!(snapshot.value().state_version, 1);
        drop(snapshot);
        h.shutdown().await;
        audit.close();
        assert!(journal
            .join_until(Instant::now() + Duration::from_secs(5))
            .unwrap());
    }
}
