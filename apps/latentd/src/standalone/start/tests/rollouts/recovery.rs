use super::*;
use latent_artifacts::{ArtifactRepository, ReleaseActor, ReleaseActorKind};
use latent_audit::{
    AuditActorIdentity, AuditActorKind, AuditControlAction, AuditFilter, AuditIdentities,
    AuditOperationAttempt, AuditOperationResult, AuditQueryRequest, AuditRecordData, AuditScope,
};
use latent_control_store::{
    rollouts::{
        DeploymentExpectation, RolloutContext, RolloutId, RolloutOperationPrecondition,
        RolloutRequest, StartRolloutSpec,
    },
    DeploymentStore,
};
use latent_core::{DeploymentId, TenantId};
use latent_wire::management::deployment_manifest_from_proto;
use std::time::Instant;

fn snapshot(from: &std::path::Path, to: &std::path::Path, depth: usize, count: &mut usize) {
    assert!(depth < 8);
    std::fs::create_dir(to).unwrap();
    std::fs::set_permissions(to, std::fs::metadata(from).unwrap().permissions()).unwrap();
    for entry in std::fs::read_dir(from).unwrap() {
        let entry = entry.unwrap();
        *count += 1;
        assert!(*count < 100);
        let kind = entry.file_type().unwrap();
        let target = to.join(entry.file_name());
        if kind.is_dir() {
            snapshot(&entry.path(), &target, depth + 1, count);
        } else {
            assert!(kind.is_file());
            assert!(entry.metadata().unwrap().len() < 1024 * 1024);
            std::fs::copy(entry.path(), target).unwrap();
        }
    }
}

#[tokio::test]
#[allow(
    clippy::too_many_lines,
    reason = "one crash-cut schedule keeps the durable attempt, catalog and disabled restart assertions together"
)]
async fn disabled_rollouts_reconcile_existing_history_without_exposing_the_service() {
    let directory = TempDir::new().unwrap();
    let mut settings = settings(&directory);
    settings.audit = Some(AuditLimits::default());
    settings.rollouts = Some(crate::config::RolloutSettings {
        store: RolloutLimits {
            maximum_receipts: 2,
            maximum_stages: 17,
            ..RolloutLimits::default()
        },
        coordinator: CoordinatorLimits::default(),
    });
    settings.shutdown_grace = Duration::from_secs(5);
    let catalogs = Catalogs::open_with_control(&settings, &tokio::runtime::Handle::current())
        .await
        .unwrap();
    let base = catalogs
        .artifacts
        .publish(fixtures::artifact("tests", "echo", "base"))
        .await
        .unwrap();
    let candidate = catalogs
        .artifacts
        .publish(fixtures::artifact("tests", "echo", "candidate"))
        .await
        .unwrap();
    let base = deployment_manifest_from_proto(fixtures::deployment(
        "base",
        "tests",
        "echo",
        &base.release_digest,
    ))
    .unwrap();
    let base = catalogs
        .deployments
        .apply_versioned(&TenantId("tests".into()), base, Some(0))
        .await
        .unwrap();
    let mut candidate =
        fixtures::deployment("candidate", "tests", "echo", &candidate.release_digest);
    candidate.route_weight = 1000;
    let prepared = catalogs
        .deployments
        .prepare_rollout(RolloutRequest::Start {
            context: RolloutContext {
                tenant: TenantId("tests".into()),
                actor: ReleaseActor {
                    subject: "operator".into(),
                    kind: ReleaseActorKind::Administrator,
                },
                operation: RolloutOperationPrecondition {
                    operation_id: "pending-start".into(),
                    expected_revision: 0,
                },
            },
            spec: StartRolloutSpec {
                id: RolloutId("retained".into()),
                base: DeploymentExpectation {
                    id: DeploymentId("base".into()),
                    generation: base.deployment.generation,
                },
                candidate: deployment_manifest_from_proto(candidate).unwrap(),
                candidate_weights: (10..=25).map(|step| step * 100).chain([10_000]).collect(),
            },
        })
        .await
        .unwrap();
    let preview = prepared.preview();
    let attempt = AuditOperationAttempt {
        scope: AuditScope::Tenant(preview.tenant.clone()),
        actor: AuditActorIdentity {
            subject: preview.actor.subject.clone(),
            kind: AuditActorKind::Administrator,
        },
        operation_id: preview.operation_id.clone(),
        request_digest: preview.request_digest.clone(),
        preview_receipt_digest: Some(latent_artifacts::package::artifact_blob_digest(
            &preview.canonical_bytes().unwrap(),
        )),
        action: AuditControlAction::Rollout,
        identities: AuditIdentities {
            rollout: Some(preview.rollout_id.0.clone()),
            rollout_revision: Some(preview.revision),
            rollout_step: Some(preview.step),
            state_version: Some(preview.state_version),
            route_generation: Some(preview.route_generation),
            ..AuditIdentities::default()
        },
        replay: false,
        expected_generation: None,
        expected_deployment_generation: None,
        expected_rollout_revision: Some(0),
        occurred_at_unix_millis: 1,
    };
    let audit = catalogs.audit.as_ref().unwrap().handle();
    let mut guard = audit
        .try_reserve_critical(&attempt)
        .unwrap()
        .begin()
        .wait()
        .await
        .unwrap();
    guard.mutation_started().unwrap();
    let committed = catalogs.deployments.commit_rollout(prepared).unwrap();
    committed.durability.unwrap();
    // Copy the fully synced attempt and catalog cut before the original
    // process gets a chance to append its abandonment outcome.
    let recovered = directory.path().join("recovered");
    snapshot(&settings.data_directory, &recovered, 0, &mut 0);
    settings.data_directory = recovered;
    settings.rollouts = None;
    drop(guard);
    assert!(catalogs
        .rollouts
        .as_ref()
        .unwrap()
        .shutdown(Duration::from_secs(5))
        .await
        .unwrap()
        .clean());
    catalogs
        .audit
        .as_ref()
        .unwrap()
        .shutdown(Duration::from_secs(5))
        .await
        .unwrap();
    drop(catalogs);
    drop(audit);
    let reopened = Catalogs::open_with_control(&settings, &tokio::runtime::Handle::current())
        .await
        .unwrap();
    assert!(reopened.rollouts.is_none());
    let audit = reopened.audit.as_ref().unwrap().handle();
    assert_eq!(audit.snapshot().pending_attempts, 0);
    let page = audit
        .query(
            AuditQueryRequest {
                scope: AuditScope::Tenant(TenantId("tests".into())),
                filter: AuditFilter::default(),
                cursor: None,
                limit: 8,
                maximum_bytes: 32768,
            },
            Instant::now() + Duration::from_secs(5),
        )
        .unwrap()
        .wait()
        .await
        .unwrap();
    let (records, _, _, lease) = page.into_parts();
    assert!(records.iter().any(|record| matches!(&record.data,AuditRecordData::Outcome{conclusion,..} if conclusion.result == AuditOperationResult::Committed)));
    drop(records);
    drop(lease);
    let status = reopened
        .deployments
        .get_rollout(&TenantId("tests".into()), &RolloutId("retained".into()))
        .unwrap()
        .unwrap();
    assert_eq!(status.route_generation, committed.receipt.route_generation);
    assert_eq!(status.candidate_weights.len(), 17);
    let node = Box::pin(crate::standalone::StandaloneNode::start_with_catalogs(
        settings,
        reopened,
        tokio::runtime::Handle::current(),
        crate::standalone::RuntimeThreads::default(),
    ))
    .await
    .unwrap();
    let mut client = proto::rollout_service_client::RolloutServiceClient::connect(format!(
        "http://{}",
        node.endpoint()
    ))
    .await
    .unwrap();
    let mut request = tonic::Request::new(proto::GetRolloutRequest {
        id: "retained".into(),
    });
    request.metadata_mut().insert(
        "authorization",
        "Bearer test-token-000000000000000000000000000000"
            .parse()
            .unwrap(),
    );
    assert_eq!(
        client.get_rollout(request).await.unwrap_err().code(),
        tonic::Code::Unimplemented
    );
    drop(client);
    assert!(node.shutdown().await.unwrap().clean);
}
