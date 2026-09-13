use super::*;
use latent_artifacts::{ArtifactRepository, ReleaseActor, ReleaseActorKind};
use latent_audit::{
    AuditFilter, AuditLimits, AuditOperationResult, AuditQueryRequest, AuditRecordData, AuditScope,
};
use latent_control_store::deployment_operations::{
    DeploymentOperationContext, DeploymentOperationRequest,
};
use latent_core::TenantId;
use latent_rollout::deployment_audit::ManagedDeploymentAudit;
use std::time::{Duration, Instant};

#[tokio::test]
#[expect(
    clippy::too_many_lines,
    reason = "one crash-cut schedule verifies exact commit, copied journal and startup reconciliation together"
)]
async fn managed_deployment_reconciles_before_generic_fallback_without_rollout_worker() {
    let directory = TempDir::new().unwrap();
    let mut settings = settings(&directory);
    settings.audit = Some(AuditLimits::default());
    assert!(settings.rollouts.is_none());
    let catalogs = Catalogs::open_with_control(&settings, &tokio::runtime::Handle::current())
        .await
        .unwrap();
    let release = catalogs
        .artifacts
        .publish(rollouts::fixtures::artifact("tests", "echo", "managed"))
        .await
        .unwrap();
    let manifest = latent_wire::management::deployment_manifest_from_proto(
        rollouts::fixtures::deployment("managed", "tests", "echo", &release.release_digest),
    )
    .unwrap();
    let prepared = catalogs
        .deployments
        .prepare_operation(DeploymentOperationRequest::Apply {
            context: DeploymentOperationContext {
                tenant: TenantId("tests".into()),
                actor: ReleaseActor {
                    subject: "operator".into(),
                    kind: ReleaseActorKind::Administrator,
                },
                operation_id: "crash-cut".into(),
                expected_state_version: 0,
            },
            manifest,
            expected_generation: 0,
        })
        .await
        .unwrap();
    let audit = catalogs.audit.as_ref().unwrap().handle();
    let deadline = Instant::now() + Duration::from_secs(5);
    let mut guard = ManagedDeploymentAudit::begin(&audit, prepared.preview(), false, deadline)
        .await
        .unwrap();
    let sequence = guard.acknowledgement().attempt_sequence.unwrap();
    let committed = guard
        .commit(catalogs.deployments.as_ref(), prepared, deadline)
        .unwrap();
    assert!(committed.value().durability.is_ok());
    let expected = prepared_receipt_digest(&committed.value().receipt);
    let copied = directory.path().join("recovered");
    copy_snapshot(&settings.data_directory, &copied, 0, &mut 0);
    // Only the copied journal lacks a conclusion; normal original cleanup may
    // record abandonment without changing the simulated crash cut.
    drop(guard);
    drop(committed);
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
    assert!(reopened.rollouts.is_none());
    let page = reopened
        .audit
        .as_ref()
        .unwrap()
        .handle()
        .query(
            AuditQueryRequest {
                scope: AuditScope::Tenant(TenantId("tests".into())),
                filter: AuditFilter::default(),
                cursor: None,
                limit: 16,
                maximum_bytes: 64 * 1024,
            },
            Instant::now() + Duration::from_secs(5),
        )
        .unwrap()
        .wait()
        .await
        .unwrap();
    let (records, _, _, lease) = page.into_parts();
    let conclusion = records
        .iter()
        .find_map(|record| match &record.data {
            AuditRecordData::Outcome {
                attempt_sequence,
                conclusion,
            } if *attempt_sequence == sequence => Some(conclusion),
            _ => None,
        })
        .unwrap();
    assert_eq!(conclusion.result, AuditOperationResult::Committed);
    assert_eq!(conclusion.receipt_digest.as_ref(), Some(&expected));
    drop(records);
    drop(lease);
    assert!(reopened
        .audit
        .as_ref()
        .unwrap()
        .shutdown(Duration::from_secs(5))
        .await
        .unwrap()
        .clean());
}

fn prepared_receipt_digest(
    receipt: &latent_control_store::deployment_operations::DeploymentOperationReceipt,
) -> latent_core::ArtifactBlobDigest {
    use sha2::{Digest, Sha256};
    format!(
        "sha256:{:x}",
        Sha256::digest(receipt.canonical_bytes().unwrap())
    )
    .parse()
    .unwrap()
}

fn copy_snapshot(from: &std::path::Path, to: &std::path::Path, depth: usize, count: &mut usize) {
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
            copy_snapshot(&entry.path(), &target, depth + 1, count);
        } else {
            assert!(kind.is_file());
            assert!(entry.metadata().unwrap().len() < 1024 * 1024);
            std::fs::copy(entry.path(), target).unwrap();
        }
    }
}
