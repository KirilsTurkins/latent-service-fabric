use super::super::block_on;
use super::*;
use latent_audit::{
    AuditFilter, AuditHandle, AuditLimits, AuditOperationResult, AuditQueryRequest,
    AuditRecordData, AuditScope, AuditStoredRecord, AuditWorker, DirectoryPhase2AuditJournal,
};
use std::time::{Duration, Instant};

struct Journal {
    handle: AuditHandle,
    worker: AuditWorker,
}

impl Journal {
    fn open(root: &TempRoot, maximum_records: usize) -> Self {
        let (handle, worker) = DirectoryPhase2AuditJournal::open(
            root.path().join("audit"),
            AuditLimits {
                maximum_records,
                ..Default::default()
            },
        )
        .unwrap();
        Self { handle, worker }
    }

    fn rows(&self) -> Vec<AuditStoredRecord> {
        let expires = Instant::now() + Duration::from_secs(5);
        let ticket = loop {
            match self.handle.query(
                AuditQueryRequest {
                    scope: AuditScope::Tenant(tenant()),
                    filter: AuditFilter::default(),
                    cursor: None,
                    limit: 32,
                    maximum_bytes: 64 * 1024,
                },
                expires,
            ) {
                Ok(ticket) => break ticket,
                Err(failure) if failure.message == "audit-busy" && Instant::now() < expires => {
                    std::thread::yield_now()
                }
                Err(failure) => panic!("audit query: {failure:?}"),
            }
        };
        ticket.blocking_wait().unwrap().records().to_vec()
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

fn audited_publish(
    repository: &DirectoryArtifactRepository,
    journal: &Journal,
) -> WebMutationResult {
    let mut audit = WebAuditGuard::new(Some(&journal.handle), ReleaseLifecycleAction::Publish);
    let result = repository
        .publish_web_package(
            context("publish", 0),
            browser_test_upload(),
            &mut |preview| audit.preview(preview),
        )
        .unwrap();
    assert_eq!(
        block_on(Box::pin(audit.finish(repository))).status,
        ReleaseAuditStatus::Durable
    );
    result
}

#[test]
fn web_audit_binds_real_publication_and_replay_without_capsule_receipts() {
    let root = TempRoot::new();
    let audit_root = TempRoot::new();
    let repository = open(&root);
    let journal = Journal::open(&audit_root, 16);
    let first = audited_publish(&repository, &journal);
    let replay = audited_publish(&repository, &journal);
    assert!(replay.replay);
    assert_eq!(first.receipt, replay.receipt);
    assert!(matches!(
        block_on(repository.get_selected_operation(&first.receipt.publication.scope, "publish"))
            .unwrap()
            .1,
        ReleaseOperationLookup::Unknown
    ));
    let rows = journal.rows();
    assert_eq!(rows.len(), 4);
    for (index, row) in rows.iter().enumerate() {
        let identities = match &row.data {
            AuditRecordData::Attempt(attempt) => &attempt.identities,
            AuditRecordData::Outcome { conclusion, .. } => {
                assert_eq!(conclusion.result, AuditOperationResult::Committed);
                assert_eq!(conclusion.replay, index == 3);
                &conclusion.identities
            }
            _ => panic!("web control record"),
        };
        assert_eq!(
            identities.publication.as_ref(),
            Some(&first.receipt.publication.id)
        );
        assert!(identities.component.is_none());
        assert_eq!(identities.lifecycle_generation, Some(1));
    }
    assert_eq!(journal.handle.snapshot().reserved_records, 0);
}

#[test]
fn web_response_rejection_never_persists_attempt_payload_or_receipt() {
    let root = TempRoot::new();
    let audit_root = TempRoot::new();
    let repository = open(&root);
    let journal = Journal::open(&audit_root, 8);
    let mut audit = WebAuditGuard::new(Some(&journal.handle), ReleaseLifecycleAction::Publish);
    let result = repository.publish_web_package(
        context("publish", 0),
        browser_test_upload(),
        &mut |preview| {
            if preview.receipt.resulting_generation == 1 {
                return Err(crate::local_repository::resource_exhausted(
                    "response-preflight",
                ));
            }
            audit.preview(preview)
        },
    );
    assert!(result.is_err());
    assert_eq!(journal.handle.snapshot().retained_records, 0);
    assert!(repository
        .web_operation_status(&LifecycleScope::Tenant(tenant()), "publish")
        .unwrap()
        .is_none());
    assert_eq!(
        repository
            .publication_storage_snapshot()
            .unwrap()
            .retained_publications,
        0
    );
    audited_publish(&repository, &journal);
}

#[test]
fn web_full_audit_denies_retirement_but_emergency_revoke_remains_durable() {
    let root = TempRoot::new();
    let audit_root = TempRoot::new();
    let repository = open(&root);
    let journal = Journal::open(&audit_root, 2);
    let reference = audited_publish(&repository, &journal).receipt.publication;
    for action in [
        ReleaseLifecycleAction::Retire,
        ReleaseLifecycleAction::Revoke,
    ] {
        let (operation, reason) = match action {
            ReleaseLifecycleAction::Retire => {
                ("retire", ReleaseLifecycleReason::OperatorRetirement)
            }
            _ => ("revoke", ReleaseLifecycleReason::OperatorRevocation),
        };
        let mut audit = WebAuditGuard::new(Some(&journal.handle), action);
        let result = repository.transition_web_publication(
            context(operation, 1),
            &reference,
            action,
            reason,
            &mut |preview| audit.preview(preview),
        );
        assert_eq!(result.is_ok(), action == ReleaseLifecycleAction::Revoke);
        assert_eq!(
            block_on(Box::pin(audit.finish(&repository))).status,
            ReleaseAuditStatus::AuditUnavailable
        );
    }
    assert_eq!(
        repository
            .web_publication_status(&reference)
            .unwrap()
            .record
            .state,
        ReleaseLifecycleState::Revoked
    );
    assert_eq!(journal.handle.snapshot().unavailable_events, 1);
    assert_eq!(journal.rows().len(), 2);
}

#[test]
fn web_abandoned_waiter_retains_uncertainty_and_exact_durable_receipt_after_restart() {
    let root = TempRoot::new();
    let audit_root = TempRoot::new();
    let repository = open(&root);
    let journal = Journal::open(&audit_root, 8);
    let mut audit = WebAuditGuard::new(Some(&journal.handle), ReleaseLifecycleAction::Publish);
    let result = repository
        .publish_web_package(
            context("publish", 0),
            browser_test_upload(),
            &mut |preview| audit.preview(preview),
        )
        .unwrap();
    drop(audit);
    drop(repository);
    drop(journal);
    let repository = open(&root);
    let journal = Journal::open(&audit_root, 8);
    block_on(Box::pin(reconcile_release_audit(
        &journal.handle,
        &repository,
    )))
    .unwrap();
    let rows = journal.rows();
    assert_eq!(rows.len(), 2);
    let AuditRecordData::Outcome { conclusion, .. } = &rows[1].data else {
        panic!("reconciled outcome")
    };
    assert_eq!(conclusion.result, AuditOperationResult::Unknown);
    assert_eq!(
        repository
            .web_operation_status(&result.receipt.publication.scope, "publish")
            .unwrap(),
        Some(result.receipt)
    );
    assert!(audited_publish(&repository, &journal).replay);
    let replay_rows = journal.rows();
    let AuditRecordData::Outcome { conclusion, .. } = &replay_rows[3].data else {
        panic!("replayed outcome")
    };
    assert_eq!(conclusion.result, AuditOperationResult::Committed);
    assert!(conclusion.replay);
    assert!(journal.handle.snapshot().previous_session_loss_unknown);
    assert_eq!(journal.handle.snapshot().reserved_records, 0);
}
