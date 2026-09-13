mod recovery;
#[path = "../tests/support.rs"]
mod releases;
mod support;

use super::*;
use latent_artifacts::ReleaseAuditStatus;
use latent_audit::{AuditOperationResult, AuditRecordData};
use latent_control_store::deployment_operations::{
    DeploymentOperationLookup, DeploymentOperationRequest,
};
use latent_core::{DeploymentId, PlatformErrorCode, TenantId};
use support::{apply, context, expires, runtime, Fixture};

#[test]
fn exact_apply_delete_and_retained_replay_work_without_a_coordinator() {
    runtime().block_on(async {
        let mut fixture = Fixture::new().await;
        let (created, ack) = fixture.execute(apply("create", 1)).await;
        assert_eq!(ack.status, ReleaseAuditStatus::Durable);
        assert!(!created.replayed);
        assert_eq!(created.receipt.expected_state_version, 1);
        let deleted = DeploymentOperationRequest::Delete {
            context: context("delete", created.receipt.state_version),
            id: DeploymentId("candidate".into()),
            expected_generation: created.receipt.object_generation,
        };
        let (removed, ack) = fixture.execute(deleted).await;
        assert_eq!(ack.status, ReleaseAuditStatus::Durable);
        assert!(removed.deployment.is_none());
        assert!(removed.receipt.state_version > created.receipt.state_version);
        let (replayed, ack) = fixture.execute(apply("create", 1)).await;
        assert_eq!(ack.status, ReleaseAuditStatus::Durable);
        assert!(replayed.replayed);
        assert_eq!(replayed.receipt, created.receipt);
        assert_eq!(replayed.deployment, created.deployment);
        assert!(fixture
            .repository
            .get(&DeploymentId("candidate".into()))
            .await
            .unwrap()
            .is_none());
        let lookup = fixture
            .repository
            .get_operation(&TenantId("alice".into()), "delete")
            .await
            .unwrap();
        assert_eq!(
            lookup.value(),
            &DeploymentOperationLookup::Found(removed.receipt)
        );
        fixture.shutdown();
    });
}

#[test]
fn expired_commit_and_caller_loss_have_distinct_honest_outcomes() {
    runtime().block_on(async {
        let mut fixture = Fixture::new().await;
        let prepared = fixture.repository.prepare_operation(apply("expired", 1)).await.unwrap();
        let mut guard = ManagedDeploymentAudit::begin(&fixture.audit, prepared.preview(), false, expires()).await.unwrap();
        assert_eq!(guard.commit(fixture.repository.as_ref(), prepared, std::time::Instant::now()).err().unwrap().code, PlatformErrorCode::DeadlineExceeded);
        drop(guard);
        let rows = fixture.rows_after_terminal().await;
        assert!(rows.iter().any(|row| matches!(&row.data, AuditRecordData::Outcome {conclusion,..} if conclusion.result == AuditOperationResult::NotStarted)));
        let prepared = fixture.repository.prepare_operation(apply("lost-after-commit", 1)).await.unwrap();
        let mut guard = ManagedDeploymentAudit::begin(&fixture.audit, prepared.preview(), false, expires()).await.unwrap();
        let result = guard.commit(fixture.repository.as_ref(), prepared, expires()).unwrap();
        assert!(result.value().durability.is_ok());
        drop(guard);
        let rows = fixture.rows_after_terminal().await;
        assert!(rows.iter().any(|row| matches!(&row.data, AuditRecordData::Outcome {conclusion,..} if conclusion.result == AuditOperationResult::Unknown)));
        let lookup = fixture.repository.get_operation(&TenantId("alice".into()), "lost-after-commit").await.unwrap();
        assert_eq!(lookup.value(), &DeploymentOperationLookup::Found(result.value().receipt.clone()));
        // Startup reconciliation never rewrites an already terminal Unknown.
        reconcile_deployment_audit(&fixture.audit, fixture.repository.as_ref(), expires()).await.unwrap();
        assert_eq!(fixture.audit.snapshot().unknown_outcomes, 1);
        fixture.shutdown();
    });
}

#[test]
fn compact_rejection_and_exact_identity_binding_do_not_publish() {
    runtime().block_on(async {
        let mut fixture = Fixture::new().await;
        let invalid_cas = apply("rejected", 0);
        let identity = DeploymentRejectionIdentity::from_request(&invalid_cas).unwrap();
        let failure = fixture.repository.prepare_operation(invalid_cas).await.err().unwrap();
        assert_eq!(failure.code, PlatformErrorCode::StateConflict);
        let ack = record_rejection(&fixture.audit, identity, &failure, expires()).await.unwrap();
        assert_eq!(ack.status, ReleaseAuditStatus::Durable);
        let rows = fixture.rows_after_terminal().await;
        assert!(rows.iter().any(|row| matches!(&row.data, AuditRecordData::Outcome {conclusion,..} if conclusion.result == AuditOperationResult::Rejected && conclusion.receipt_digest.is_none())));
        let prepared = fixture.repository.prepare_operation(apply("bound", 1)).await.unwrap();
        let expected = mapping::attempt(prepared.preview(), false).unwrap();
        assert!(mapping::matches(&expected, prepared.preview()));
        for changed in [
            { let mut a=expected.clone(); a.expected_state_version=Some(0); a },
            { let mut a=expected.clone(); a.actor.subject="different".into(); a },
            { let mut a=expected.clone(); a.preview_receipt_digest=None; a },
            { let mut a=expected.clone(); a.operation_id="other".into(); a },
            { let mut a=expected.clone(); a.identities.state_version=Some(99); a },
        ] {
            assert!(!mapping::matches(&changed, prepared.preview()));
            assert_eq!(mapping::conclusion(&changed, Some(prepared.preview())).result, AuditOperationResult::Unknown);
        }
        drop(prepared);
        assert!(fixture.repository.get(&DeploymentId("candidate".into())).await.unwrap().is_none());
        fixture.shutdown();
    });
}
