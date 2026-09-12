use super::*;
use crate::{ReleaseAuditAck, ReleaseAuditGuard, ReleaseAuditStatus};
use latent_audit::{
    AuditFilter, AuditHandle, AuditLimits, AuditOperationResult, AuditQueryRequest,
    AuditRecordData, AuditScope, AuditStoredRecord, AuditWorker, DirectoryPhase2AuditJournal,
};
use std::time::{Duration, Instant};

struct Journal {
    root: TempRoot,
    handle: AuditHandle,
    worker: AuditWorker,
}
impl Journal {
    fn new(records: usize) -> Self {
        let root = TempRoot::new();
        let limits = AuditLimits {
            maximum_records: records,
            ..Default::default()
        };
        let (handle, worker) =
            DirectoryPhase2AuditJournal::open(root.path().join("audit"), limits).unwrap();
        Self {
            root,
            handle,
            worker,
        }
    }
    fn rows(&self) -> Vec<AuditStoredRecord> {
        let page = self
            .handle
            .query(
                AuditQueryRequest {
                    scope: AuditScope::Tenant(TenantId("examples".to_owned())),
                    filter: AuditFilter::default(),
                    cursor: None,
                    limit: 32,
                    maximum_bytes: 64 * 1024,
                },
                Instant::now() + Duration::from_secs(5),
            )
            .unwrap()
            .blocking_wait()
            .unwrap();
        // Test-only bounded copy; production response paths transfer the lease.
        page.records().to_vec()
    }
}
impl Drop for Journal {
    fn drop(&mut self) {
        self.handle.close();
        assert!(self
            .worker
            .join_until(Instant::now() + Duration::from_secs(5))
            .unwrap());
    }
}

fn publish(
    repo: &DirectoryArtifactRepository,
    journal: &Journal,
    id: &str,
    value: CapsuleArtifact,
) -> (
    Result<crate::ManagedPublicationReceipt, PlatformError>,
    ReleaseAuditAck,
) {
    let mut audit = ReleaseAuditGuard::new(Some(&journal.handle), ReleaseLifecycleAction::Publish);
    let result = block_on(repo.publish_managed(
        context(id, 0),
        ManagedPublicationUpload::Local(value),
        &mut |preview| {
            accept(preview)?;
            audit.preview(preview)
        },
    ));
    let ack = block_on(Box::pin(
        audit.finish(repo, result.as_ref().ok().map(|value| &value.operation)),
    ));
    (result, ack)
}

#[test]
fn durable_catalog_outcomes_and_replays_are_audited_once_per_attempt() {
    let temp = TempRoot::new();
    let repo = repository(temp.path());
    let journal = Journal::new(16);
    let value = scoped_artifact("audit-release");
    let (first, ack) = publish(&repo, &journal, "create", value.clone());
    first.unwrap();
    assert_eq!(ack.status, ReleaseAuditStatus::Durable);
    let (replay, ack) = publish(&repo, &journal, "create", value.clone());
    replay.unwrap();
    assert_eq!(ack.status, ReleaseAuditStatus::Durable);
    let (rejected, ack) = publish(&repo, &journal, "wrong-cas", value);
    assert_eq!(rejected.unwrap_err().code, PlatformErrorCode::StateConflict);
    assert_eq!(ack.status, ReleaseAuditStatus::Durable);
    let rows = journal.rows();
    assert_eq!(rows.len(), 6);
    let outcomes: Vec<_> = rows
        .iter()
        .filter_map(|row| match &row.data {
            AuditRecordData::Outcome { conclusion, .. } => {
                Some((conclusion.result, conclusion.replay))
            }
            _ => None,
        })
        .collect();
    assert_eq!(
        outcomes,
        vec![
            (AuditOperationResult::Committed, false),
            (AuditOperationResult::Committed, true),
            (AuditOperationResult::Rejected, false),
        ]
    );
    assert_eq!(journal.handle.snapshot().reserved_records, 0);
}

#[test]
fn full_audit_blocks_regular_mutation_but_emergency_revoke_retains_catalog_receipt() {
    let temp = TempRoot::new();
    let repo = repository(temp.path());
    let journal = Journal::new(2);
    let value = scoped_artifact("audit-full");
    let release = value.descriptor.release_digest.clone();
    publish(&repo, &journal, "create", value).0.unwrap();
    let mut retirement =
        ReleaseAuditGuard::new(Some(&journal.handle), ReleaseLifecycleAction::Retire);
    let result = block_on(repo.change_release_lifecycle(
        context("retire", 1),
        &release,
        ReleaseLifecycleAction::Retire,
        ReleaseLifecycleReason::OperatorRetirement,
        &mut |preview| retirement.preview(preview),
    ));
    assert_eq!(
        result.unwrap_err().code,
        PlatformErrorCode::ResourceExhausted
    );
    drop(retirement);
    assert_eq!(
        block_on(repo.get_release_lifecycle(&scope(), &release))
            .unwrap()
            .unwrap()
            .record
            .state,
        ReleaseLifecycleState::Admitted
    );
    let mut revocation =
        ReleaseAuditGuard::new(Some(&journal.handle), ReleaseLifecycleAction::Revoke);
    let actual = block_on(repo.change_release_lifecycle(
        context("revoke", 1),
        &release,
        ReleaseLifecycleAction::Revoke,
        ReleaseLifecycleReason::SecurityIncident,
        &mut |preview| revocation.preview(preview),
    ))
    .unwrap();
    let ack = block_on(Box::pin(revocation.finish(&repo, Some(&actual))));
    assert_eq!(ack.status, ReleaseAuditStatus::AuditUnavailable);
    assert_eq!(actual.record.unwrap().state, ReleaseLifecycleState::Revoked);
    assert_eq!(journal.handle.snapshot().unavailable_events, 1);
    assert_eq!(journal.rows().len(), 2);
}

#[test]
fn response_rejection_occurs_before_either_catalog_or_audit_persistence() {
    let temp = TempRoot::new();
    let repo = repository(temp.path());
    let journal = Journal::new(8);
    let mut audit = ReleaseAuditGuard::new(Some(&journal.handle), ReleaseLifecycleAction::Publish);
    let result = block_on(repo.publish_managed(
        context("unreturnable", 0),
        ManagedPublicationUpload::Local(scoped_artifact("audit-preflight")),
        &mut |preview| {
            reject(preview)?;
            audit.preview(preview)
        },
    ));
    assert!(result.is_err());
    assert_eq!(journal.handle.snapshot().retained_records, 0);
    assert!(matches!(
        block_on(repo.get_release_operation(&scope(), "unreturnable")).unwrap(),
        ReleaseOperationLookup::Unknown
    ));
}

#[test]
fn failed_terminal_storage_preserves_real_committed_catalog_result_and_reserved_outcome() {
    let temp = TempRoot::new();
    let repo = repository(temp.path());
    let journal = Journal::new(8);
    let mut audit = ReleaseAuditGuard::new(Some(&journal.handle), ReleaseLifecycleAction::Publish);
    let actual = block_on(repo.publish_managed(
        context("committed-before-audit-failure", 0),
        ManagedPublicationUpload::Local(scoped_artifact("audit-sink-failure")),
        &mut |preview| audit.preview(preview),
    ))
    .unwrap();
    let stage = journal.root.path().join("audit/record.next");
    std::fs::create_dir(&stage).unwrap();
    let ack = block_on(Box::pin(audit.finish(&repo, Some(&actual.operation))));
    assert_eq!(ack.status, ReleaseAuditStatus::OutcomeUnknown);
    assert!(
        stage.is_dir(),
        "unknown/nonordinary staging object is preserved"
    );
    let snapshot = journal.handle.snapshot();
    assert!(snapshot.recovery_pending);
    assert_eq!(snapshot.reserved_records, 1);
    assert!(snapshot.reserved_bytes > 0);
    let ReleaseOperationLookup::Found(receipt) =
        block_on(repo.get_release_operation(&scope(), "committed-before-audit-failure")).unwrap()
    else {
        panic!("durable actual receipt");
    };
    assert_eq!(receipt, actual.operation);
    assert_eq!(receipt.disposition, ReleaseOperationDisposition::Committed);
}

#[test]
fn returned_receipt_change_cannot_change_the_audited_durable_catalog_outcome() {
    let temp = TempRoot::new();
    let repo = repository(temp.path());
    let journal = Journal::new(8);
    let mut audit = ReleaseAuditGuard::new(Some(&journal.handle), ReleaseLifecycleAction::Publish);
    let actual = block_on(repo.publish_managed(
        context("exact-preview", 0),
        ManagedPublicationUpload::Local(scoped_artifact("audit-exact-preview")),
        &mut |preview| audit.preview(preview),
    ))
    .unwrap();
    let mut changed = actual.operation.clone();
    changed.record.as_mut().unwrap().generation += 10;
    let ack = block_on(Box::pin(audit.finish(&repo, Some(&changed))));
    // The incorrect returned value is rejected as evidence. The exact catalog
    // lookup still proves the original committed receipt, which is safe to use.
    assert_eq!(ack.status, ReleaseAuditStatus::Durable);
    let rows = journal.rows();
    let AuditRecordData::Outcome { conclusion, .. } = &rows[1].data else {
        panic!("outcome");
    };
    assert_eq!(conclusion.identities.lifecycle_generation, Some(1));
    assert_eq!(conclusion.result, AuditOperationResult::Committed);
}
