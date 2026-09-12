use super::*;
use latent_artifacts::{ReleaseActor, ReleaseActorKind};
use latent_control_store::rollouts::{
    RolloutAction, RolloutId, RolloutOperationOutcome, RolloutOperationReceipt, RolloutReason,
    RolloutState,
};
use latent_core::{ArtifactBlobDigest, RouteGeneration, TenantId};
use std::os::unix::fs::PermissionsExt;

pub(super) fn receipt() -> RolloutOperationReceipt {
    let digest: ArtifactBlobDigest = format!("sha256:{}", "a".repeat(64)).parse().unwrap();
    RolloutOperationReceipt {
        rollout_id: RolloutId("rollout".into()),
        tenant: TenantId("alice".into()),
        operation_id: "start".into(),
        request_digest: digest.clone(),
        actor: ReleaseActor {
            kind: ReleaseActorKind::User,
            subject: "operator".into(),
        },
        action: RolloutAction::Start,
        expected_revision: 0,
        revision: 1,
        outcome: RolloutOperationOutcome::Committed,
        reason: RolloutReason::StageApplied,
        state_version: 2,
        route_generation: RouteGeneration(2),
        state: RolloutState::Running,
        step: 0,
        plan_digest: digest.clone(),
        completed_at_unix_millis: 1,
        receipt_digest: digest,
        canary_decision: None,
        rollback_target: None,
    }
}
pub(super) fn snapshot_journal(from: &std::path::Path, to: &std::path::Path) {
    std::fs::create_dir(to).unwrap();
    std::fs::set_permissions(to, std::fs::Permissions::from_mode(0o700)).unwrap();
    std::fs::create_dir(to.join("records")).unwrap();
    std::fs::set_permissions(to.join("records"), std::fs::Permissions::from_mode(0o700)).unwrap();
    for name in ["MODE", "HEAD"] {
        std::fs::copy(from.join(name), to.join(name)).unwrap();
    }
    let entries: Vec<_> = std::fs::read_dir(from.join("records")).unwrap().collect();
    assert_eq!(
        entries.len(),
        1,
        "snapshot exactly one fully synced attempt"
    );
    for entry in entries {
        let entry = entry.unwrap();
        assert!(entry.file_type().unwrap().is_file());
        std::fs::copy(entry.path(), to.join("records").join(entry.file_name())).unwrap();
    }
}
#[test]
fn startup_reconciliation_requires_exact_durable_receipt_and_handles_unknown() {
    runtime().block_on(async {
        for committed in [false, true] {
            let mut fixture = Fixture::new(CoordinatorLimits::default()).await;
            let prepared = fixture
                .repository
                .prepare_rollout(support::start())
                .await
                .unwrap();
            let description = audit::attempt(prepared.preview(), false).unwrap();
            let mut active = fixture
                .audit
                .try_reserve_critical(&description)
                .unwrap()
                .begin()
                .wait()
                .await
                .unwrap();
            active.mutation_started().unwrap();
            if committed {
                fixture
                    .repository
                    .commit_rollout(prepared)
                    .unwrap()
                    .durability
                    .unwrap();
            } else {
                drop(prepared);
            }
            let copy = fixture.root.path().join("recovered");
            snapshot_journal(&fixture.root.path().join("audit"), &copy);
            // The original owner terminates independently. The copied durable
            // cut contains only the acknowledged attempt, as after a crash.
            drop(active);
            fixture.shutdown().await;
            let (recovered, mut worker) =
                DirectoryPhase2AuditJournal::open(&copy, AuditLimits::default()).unwrap();
            reconcile_rollout_audit(&recovered, &fixture.repository, expires())
                .await
                .unwrap();
            assert_eq!(recovered.snapshot().pending_attempts, 0);
            assert_eq!(recovered.snapshot().unknown_outcomes, u64::from(!committed));
            recovered.close();
            assert!(worker.join_until(expires()).unwrap());
        }
    });
}

#[test]
fn expired_reconciliation_does_not_read_or_change_audit_state() {
    runtime().block_on(async {
        let mut fixture = Fixture::new(CoordinatorLimits::default()).await;
        let snapshot = fixture.audit.snapshot();
        assert_eq!(
            reconcile_rollout_audit(&fixture.audit, &fixture.repository, Instant::now())
                .await
                .unwrap_err()
                .code,
            latent_core::PlatformErrorCode::DeadlineExceeded
        );
        assert_eq!(snapshot, fixture.audit.snapshot());
        fixture.shutdown().await;
    });
}
