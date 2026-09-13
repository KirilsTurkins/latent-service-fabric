use super::super::support::{artifact, deployment, publish_variant as publish, request, Harness};
use latent_artifacts::{ArtifactRepository, LifecycleScope};
use latent_audit::{AuditLimits, DirectoryPhase2AuditJournal};
use latent_core::{ReleaseDigest, TenantId};
use latent_routing::RouteResolver;
use latent_wire::management::{proto, ManagementLimits};
use std::time::{Duration, Instant};
use tempfile::TempDir;
use tonic::Code;

fn selected(
    id: &str,
    publication: &proto::PublicationRef,
    component: &ReleaseDigest,
) -> proto::ApplyDeploymentRequest {
    let mut value = deployment(id, &publication.tenant, "echo", component);
    value.release_digest.clear();
    value.publication = Some(publication.clone());
    proto::ApplyDeploymentRequest {
        deployment: Some(value),
        expected_component_digest: Some(component.0.clone()),
        expected_generation: Some(0),
        operation: None,
    }
}

#[tokio::test]
async fn exact_deployment_selectors_keep_coexisting_publications_and_replay_identity() {
    let directory = TempDir::new().unwrap();
    let (audit, mut journal) =
        DirectoryPhase2AuditJournal::open(directory.path().join("audit"), AuditLimits::default())
            .unwrap();
    let harness = Harness::with_audit(ManagementLimits::default(), None, Some(audit.clone())).await;
    let (first, component) = publish(&harness, "acme", "1.0.0").await;
    let (second, same) = publish(&harness, "acme", "1.0.1").await;
    assert_eq!(component, same);
    let mut input = selected("first", &first, &component);
    input.operation = Some(proto::DeploymentOperationPrecondition {
        operation_id: "create".into(),
        expected_state_version: Some(0),
    });
    let applied = harness
        .deployments_client()
        .apply_deployment(request("alice", input.clone()))
        .await
        .unwrap()
        .into_inner();
    let output = applied.deployment.as_ref().unwrap();
    assert_eq!(output.publication.as_ref(), Some(&first));
    assert_eq!(output.requested_publication.as_ref(), Some(&first));
    assert_eq!(output.release_digest, component.0);
    assert_eq!(
        applied.receipt.as_ref().unwrap().publication.as_ref(),
        Some(&first)
    );
    let second_input = selected("second", &second, &component);
    let corrected = harness
        .deployments_client()
        .apply_deployment(request("alice", second_input))
        .await
        .unwrap()
        .into_inner();
    assert_eq!(corrected.deployment.unwrap().publication, Some(second));
    let replay = harness
        .deployments_client()
        .apply_deployment(request("alice", input))
        .await
        .unwrap()
        .into_inner();
    assert!(replay.replayed);
    assert_eq!(replay.receipt, applied.receipt);
    assert_eq!(replay.deployment, applied.deployment);
    let found = harness
        .deployments_client()
        .get_deployment_operation(request(
            "alice",
            proto::GetDeploymentOperationRequest {
                operation_id: "create".into(),
            },
        ))
        .await
        .unwrap()
        .into_inner();
    assert_eq!(found.receipt, applied.receipt);
    let legacy = proto::ApplyDeploymentRequest {
        deployment: Some(deployment("legacy", "acme", "echo", &component)),
        expected_generation: Some(0),
        ..Default::default()
    };
    assert_eq!(
        harness
            .deployments_client()
            .apply_deployment(request("alice", legacy))
            .await
            .unwrap_err()
            .code(),
        Code::Aborted
    );
    harness.shutdown().await;
    audit.close();
    assert!(journal
        .join_until(Instant::now() + Duration::from_secs(5))
        .unwrap());
}

#[tokio::test]
async fn deployment_selection_rejects_malformed_presence_and_hides_foreign_existence() {
    let harness = Harness::new(ManagementLimits::default()).await;
    let (first, component) = publish(&harness, "acme", "1.0.0").await;
    let input = selected("ship", &first, &component);
    for mutation in 0..5 {
        let mut changed = input.clone();
        let value = changed.deployment.as_mut().unwrap();
        match mutation {
            0 => value.release_digest = component.0.clone(),
            1 => value.publication = Some(proto::PublicationRef::default()),
            2 => value.requested_publication = Some(first.clone()),
            3 => changed.expected_component_digest = Some(format!("sha256:{}", "0".repeat(64))),
            4 => value.publication.as_mut().unwrap().tenant = "other".into(),
            _ => unreachable!(),
        }
        assert_eq!(
            harness
                .deployments_client()
                .apply_deployment(request("alice", changed))
                .await
                .unwrap_err()
                .code(),
            Code::InvalidArgument
        );
    }
    for id in [first.id, format!("publication:sha256:{}", "0".repeat(64))] {
        let other = proto::PublicationRef {
            id,
            tenant: "other".into(),
        };
        let status = harness
            .deployments_client()
            .apply_deployment(request("bob", selected("ship", &other, &component)))
            .await
            .unwrap_err();
        assert_eq!(status.code(), Code::NotFound);
        assert_eq!(status.message(), "publication not found");
    }
    assert_eq!(harness.deployments.generation().0, 0);
    harness.shutdown().await;
}

#[tokio::test]
async fn deployment_publication_response_limit_rejects_before_mutation() {
    let harness = Harness::new(ManagementLimits {
        max_response_bytes: 512,
        max_metadata_entries: 512,
        max_metadata_bytes: 512,
        max_string_bytes: 512,
        max_id_bytes: 512,
        max_page_token_bytes: 512,
        max_collection_entries: 512,
        max_route_services: 512,
        max_route_revisions: 512,
        ..Default::default()
    })
    .await;
    let (reference, component) = publish(&harness, "acme", "1.0.0").await;
    let status = harness
        .deployments_client()
        .apply_deployment(request("alice", selected("ship", &reference, &component)))
        .await
        .unwrap_err();
    assert_eq!(status.code(), Code::ResourceExhausted);
    assert_eq!(harness.deployments.generation().0, 0);
    harness.shutdown().await;
}

#[tokio::test]
async fn unscoped_local_compatibility_does_not_invent_a_tenant_publication() {
    let directory = TempDir::new().unwrap();
    let (audit, mut journal) =
        DirectoryPhase2AuditJournal::open(directory.path().join("audit"), AuditLimits::default())
            .unwrap();
    let harness = Harness::with_audit(ManagementLimits::default(), None, Some(audit.clone())).await;
    let mut source = artifact("acme", "echo", "unscoped-local");
    source.manifest.metadata.tenant = None;
    let published = harness.artifacts.publish(source).await.unwrap();
    let request_body = proto::ApplyDeploymentRequest {
        deployment: Some(deployment(
            "local",
            "acme",
            "echo",
            &published.release_digest,
        )),
        operation: Some(proto::DeploymentOperationPrecondition {
            operation_id: "local-apply".into(),
            expected_state_version: Some(0),
        }),
        expected_generation: Some(0),
        ..proto::ApplyDeploymentRequest::default()
    };
    let applied = harness
        .deployments_client()
        .apply_deployment(request("alice", request_body.clone()))
        .await
        .unwrap()
        .into_inner();
    let value = applied.deployment.as_ref().unwrap();
    assert_eq!(value.release_digest, published.release_digest.0);
    assert!(value.publication.is_none());
    assert!(value.requested_publication.is_none());
    assert!(applied.receipt.as_ref().unwrap().publication.is_none());
    let stored = harness
        .deployments
        .get_operation_snapshot(
            &TenantId("acme".into()),
            &latent_core::DeploymentId("local".into()),
        )
        .await
        .unwrap();
    let captured = stored
        .value()
        .deployment
        .as_ref()
        .unwrap()
        .publication
        .as_ref()
        .unwrap();
    assert_eq!(captured.scope, LifecycleScope::LocalUnscoped);
    let replay = harness
        .deployments_client()
        .apply_deployment(request("alice", request_body))
        .await
        .unwrap()
        .into_inner();
    assert!(replay.replayed);
    assert_eq!(replay.receipt, applied.receipt);
    assert_eq!(replay.deployment, applied.deployment);
    drop(stored);
    harness.shutdown().await;
    audit.close();
    assert!(journal
        .join_until(Instant::now() + Duration::from_secs(5))
        .unwrap());
}
