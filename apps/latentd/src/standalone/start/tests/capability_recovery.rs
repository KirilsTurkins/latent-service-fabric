use super::*;
use latent_audit::{
    AuditActorIdentity, AuditActorKind, AuditCapabilityContext, AuditCapabilityResourceClass,
    AuditCapabilityRevision, AuditControlAction, AuditFilter, AuditIdentities, AuditLimits,
    AuditOperationAttempt, AuditOperationResult, AuditProviderOutcome, AuditQueryRequest,
    AuditRecordData, AuditScope,
};
use latent_core::TenantId;
use std::time::{Duration, Instant};

#[tokio::test]
async fn capability_crash_cut_recovers_identity_before_generic_release_fallback() {
    let directory = TempDir::new().unwrap();
    let mut settings = settings(&directory);
    settings.audit = Some(AuditLimits::default());
    let catalogs = Catalogs::open_with_control(&settings, &tokio::runtime::Handle::current())
        .await
        .unwrap();
    let audit = catalogs.audit.as_ref().unwrap().handle();
    let expected = attempt();
    let deadline = Instant::now() + Duration::from_secs(5);
    let reservation = loop {
        match audit.try_reserve_critical(&expected) {
            Err(failure) if failure.message == "audit-busy" && Instant::now() < deadline => {
                tokio::time::sleep(Duration::from_millis(1)).await;
            }
            result => break result.unwrap(),
        }
    };
    let mut guard = reservation.begin().wait().await.unwrap();
    guard.mutation_started().unwrap();
    let sequence = guard.sequence();
    let copied = directory.path().join("recovered");
    super::deployment_operations::copy_snapshot(&settings.data_directory, &copied, 0, &mut 0);
    drop(guard);
    assert!(catalogs
        .audit
        .as_ref()
        .unwrap()
        .shutdown(Duration::from_secs(5))
        .await
        .unwrap()
        .clean());
    drop(audit);
    drop(catalogs);
    settings.data_directory = copied;
    let reopened = Catalogs::open_with_control(&settings, &tokio::runtime::Handle::current())
        .await
        .unwrap();
    let audit = reopened.audit.as_ref().unwrap().handle();
    assert_eq!(audit.snapshot().pending_attempts, 0);
    assert_eq!(audit.snapshot().unknown_outcomes, 1);
    let query = AuditQueryRequest {
        scope: AuditScope::Tenant(TenantId("tests".into())),
        filter: AuditFilter::default(),
        cursor: None,
        limit: 16,
        maximum_bytes: 65536,
    };
    let deadline = Instant::now() + Duration::from_secs(5);
    let ticket = loop {
        match audit.query(query.clone(), deadline) {
            Err(failure) if failure.message == "audit-busy" && Instant::now() < deadline => {
                tokio::time::sleep(Duration::from_millis(1)).await;
            }
            result => break result.unwrap(),
        }
    };
    let page = ticket.wait().await.unwrap();
    let conclusion = page
        .records()
        .iter()
        .find_map(|record| match &record.data {
            AuditRecordData::Outcome {
                attempt_sequence,
                conclusion,
            } if *attempt_sequence == sequence => Some(conclusion),
            _ => None,
        })
        .unwrap();
    let mut identities = expected.identities;
    identities.capability.as_mut().unwrap().provider_outcome = Some(AuditProviderOutcome::Unknown);
    assert_eq!(conclusion.result, AuditOperationResult::Unknown);
    assert_eq!(conclusion.identities, identities);
    drop(page);
    drop(audit);
    assert!(reopened
        .audit
        .as_ref()
        .unwrap()
        .shutdown(Duration::from_secs(5))
        .await
        .unwrap()
        .clean());
}

fn attempt() -> AuditOperationAttempt {
    let digest: latent_core::ArtifactBlobDigest =
        format!("sha256:{}", "a".repeat(64)).parse().unwrap();
    AuditOperationAttempt {
        expected_state_version: None,
        expected_rollback_target_generation: None,
        scope: AuditScope::Tenant(TenantId("tests".into())),
        actor: AuditActorIdentity {
            kind: AuditActorKind::Administrator,
            subject: "operator".into(),
        },
        operation_id: "capability-crash-cut".into(),
        request_digest: digest.clone(),
        preview_receipt_digest: None,
        action: AuditControlAction::CapabilityCall,
        identities: AuditIdentities {
            publication: Some(
                format!("publication:sha256:{}", "b".repeat(64))
                    .parse()
                    .unwrap(),
            ),
            component: Some(latent_core::ReleaseDigest(format!(
                "sha256:{}",
                "c".repeat(64)
            ))),
            revision: Some(latent_core::RevisionId("capability-revision".into())),
            deployment: Some(latent_core::DeploymentId("capability-deployment".into())),
            route_generation: Some(latent_core::RouteGeneration(1)),
            lifecycle_generation: Some(1),
            capability: Some(AuditCapabilityContext {
                activation: "capability-activation".into(),
                parent_activation: None,
                root_activation: "capability-activation".into(),
                service: "service".into(),
                binding_definition_digest: format!("sha256:{}", "d".repeat(64)).parse().unwrap(),
                binding: AuditCapabilityRevision {
                    id: "binding".into(),
                    revision: 1,
                    digest: format!("sha256:{}", "e".repeat(64)).parse().unwrap(),
                },
                policies: vec![AuditCapabilityRevision {
                    id: "policy".into(),
                    revision: 1,
                    digest: format!("sha256:{}", "f".repeat(64)).parse().unwrap(),
                }],
                provider_profile: "bounded-http-v1".into(),
                provider_configuration_digest: format!("sha256:{}", "1".repeat(64))
                    .parse()
                    .unwrap(),
                provider_configuration_epoch: 1,
                capability: "latent:http/client@0.2.0".into(),
                operation: "send".into(),
                resource_class: AuditCapabilityResourceClass::Http,
                request: Some(latent_audit::AuditCapabilityRequestDigest {
                    scope: latent_audit::AuditCapabilityDigestScope::ProviderRequest,
                    digest,
                }),
                required: true,
                provider_outcome: None,
            }),
            ..Default::default()
        },
        replay: false,
        expected_generation: None,
        expected_deployment_generation: None,
        expected_rollout_revision: None,
        occurred_at_unix_millis: 1,
    }
}
