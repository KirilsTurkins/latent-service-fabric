//! Real native journal + both native catalog owners. No deletion state model.
use super::*;
use latent_artifacts::{
    reconcile_publication_maintenance_audit, PublicationAuditGuard,
    PublicationMaintenanceReceipt as Receipt, PublicationMaintenanceRequest as Request,
    PublicationMaintenanceResult as ResultValue, PublicationReclamationLimits,
    PublicationReclamationRequest, ReleaseAuditStatus,
};
use latent_audit::{
    AuditControlAction, AuditFilter, AuditHandle, AuditLimits, AuditOperationResult,
    AuditQueryRequest, AuditRecordData, AuditScope, AuditStoredRecord, AuditWorker,
    DirectoryPhase2AuditJournal,
};
use std::time::Instant;
struct Journal {
    handle: AuditHandle,
    worker: AuditWorker,
}
impl Journal {
    fn open(root: &Path, limits: AuditLimits) -> Self {
        let (handle, worker) = DirectoryPhase2AuditJournal::open(root, limits).unwrap();
        Self { handle, worker }
    }
    fn records(&self) -> Vec<AuditStoredRecord> {
        let end = Instant::now() + TIMEOUT;
        loop {
            match self.handle.query(
                AuditQueryRequest {
                    scope: AuditScope::Tenant(latent_core::TenantId("alice".into())),
                    filter: AuditFilter::default(),
                    cursor: None,
                    limit: 128,
                    maximum_bytes: 65536,
                },
                end,
            ) {
                Ok(ticket) => return ticket.blocking_wait().unwrap().records().to_vec(),
                Err(e) if e.message == "audit-busy" && Instant::now() < end => {
                    std::thread::yield_now()
                }
                Err(e) => panic!("{e:?}"),
            }
        }
    }
}
impl Drop for Journal {
    fn drop(&mut self) {
        self.handle.close();
        let result = self.worker.join_until(Instant::now() + TIMEOUT);
        if !std::thread::panicking() {
            assert!(result.unwrap());
        }
    }
}
fn audited(
    repo: &DirectoryArtifactRepository,
    journal: &Journal,
    request: &Request,
) -> ResultValue {
    let outcome =
        repo.audited_publication_maintenance(&journal.handle, request, TIMEOUT, &mut |_| Ok(()));
    let result = outcome.result.unwrap();
    assert_eq!(outcome.audit.status, ReleaseAuditStatus::Durable);
    assert!(outcome.audit.attempt_sequence.is_some());
    result
}
fn retention(selected: PublicationDeletionRequest, action: PublicationRetentionAction) -> Request {
    Request::Retention(PublicationRetentionRequest {
        scope: selected.scope,
        actor: selected.actor,
        operation_id: selected.operation_id,
        expected_catalog_fence: selected.expected_catalog_fence,
        targets: selected.targets,
        action,
    })
}
#[test]
fn audited_native_pin_unpin_delete_reclaim_and_replay_have_exact_distinct_receipts() {
    let roots = [TempRoot::new(), TempRoot::new(), TempRoot::new()];
    let repo = artifacts(&roots[0]);
    let p = retired(&repo, "audit-one");
    let _control = bind(&roots[1], &repo);
    let journal = Journal::open(&roots[2].0.join("journal"), AuditLimits::default());
    let pin = retention(
        batch(&repo, std::slice::from_ref(&p), "pin-one"),
        PublicationRetentionAction::Pin,
    );
    audited(&repo, &journal, &pin);
    let selected = batch(&repo, std::slice::from_ref(&p), "delete-one");
    let before = journal.records().len();
    assert!(repo
        .audited_publication_maintenance(
            &journal.handle,
            &Request::Deletion(selected),
            TIMEOUT,
            &mut |_| panic!("pinned preflight")
        )
        .result
        .is_err());
    assert_eq!(journal.records().len(), before);
    let unpin = retention(
        batch(&repo, std::slice::from_ref(&p), "unpin-one"),
        PublicationRetentionAction::Unpin,
    );
    audited(&repo, &journal, &unpin);
    let deletion = batch(&repo, std::slice::from_ref(&p), "delete-one");
    let result = audited(&repo, &journal, &Request::Deletion(deletion.clone()));
    assert!(!result.replay);
    hidden(&repo, &p);
    let assessment = repo
        .inspect_publication_reclamation(
            &deletion,
            PublicationReclamationLimits::default(),
            TIMEOUT,
        )
        .unwrap();
    let cleanup = Request::Reclamation(PublicationReclamationRequest {
        deletion,
        expected_catalog_fence: assessment.catalog_fence,
        limits: PublicationReclamationLimits::default(),
    });
    let result = audited(&repo, &journal, &cleanup);
    let Receipt::Reclamation(receipt) = &result.receipt else {
        panic!("cleanup")
    };
    assert!(receipt.content.publication_file_bytes > 0);
    assert_eq!(
        repo.publication_capacity_snapshot()
            .unwrap()
            .release_directories,
        0
    );
    let state = bytes(&roots[0].0);
    let replay = audited(&repo, &journal, &cleanup);
    assert!(replay.replay);
    assert_eq!(replay.receipt, result.receipt);
    assert_eq!(state, bytes(&roots[0].0));
    let records = journal.records();
    assert_eq!(records.len(), 10);
    for (pair, action) in records.chunks_exact(2).zip([
        AuditControlAction::PublicationPin,
        AuditControlAction::PublicationUnpin,
        AuditControlAction::PublicationDelete,
        AuditControlAction::PublicationReclaim,
        AuditControlAction::PublicationReclaim,
    ]) {
        let AuditRecordData::Attempt(a) = &pair[0].data else {
            panic!("attempt")
        };
        let AuditRecordData::Outcome { conclusion, .. } = &pair[1].data else {
            panic!("outcome")
        };
        assert_eq!(a.action, action);
        assert_eq!(a.identities, latent_audit::AuditIdentities::default());
        assert_eq!(conclusion.result, AuditOperationResult::Committed);
        assert_eq!(conclusion.receipt_digest, a.preview_receipt_digest);
        assert_eq!(conclusion.replay, a.replay);
    }
}
#[test]
fn audited_native_full_journal_and_response_preflight_refuse_before_catalog_change() {
    let roots = [TempRoot::new(), TempRoot::new(), TempRoot::new()];
    let repo = artifacts(&roots[0]);
    let p = retired(&repo, "audit-budget");
    let _control = bind(&roots[1], &repo);
    let journal = Journal::open(
        &roots[2].0.join("journal"),
        AuditLimits {
            maximum_records: 2,
            ..AuditLimits::default()
        },
    );
    let request = retention(
        batch(&repo, std::slice::from_ref(&p), "pin-one"),
        PublicationRetentionAction::Pin,
    );
    let before = bytes(&roots[0].0);
    let rejected =
        repo.audited_publication_maintenance(&journal.handle, &request, TIMEOUT, &mut |_| {
            Err(PlatformError {
                code: PlatformErrorCode::ResourceExhausted,
                message: "response-budget".into(),
                retryable: false,
                details: vec![],
            })
        });
    assert!(rejected.result.is_err());
    assert_eq!(before, bytes(&roots[0].0));
    assert!(journal.records().is_empty());
    audited(&repo, &journal, &request);
    let unpin = retention(
        batch(&repo, std::slice::from_ref(&p), "unpin-one"),
        PublicationRetentionAction::Unpin,
    );
    let before = bytes(&roots[0].0);
    let capacity = repo.publication_capacity_snapshot().unwrap();
    assert!(repo
        .audited_publication_maintenance(&journal.handle, &unpin, TIMEOUT, &mut |_| Ok(()))
        .result
        .is_err());
    assert_eq!(before, bytes(&roots[0].0));
    assert_eq!(capacity, repo.publication_capacity_snapshot().unwrap());
    assert_eq!(journal.records().len(), 2);
}
#[test]
fn audited_native_changed_preflight_fence_records_unknown_without_retrying_mutation() {
    let roots = [TempRoot::new(), TempRoot::new(), TempRoot::new()];
    let repo = artifacts(&roots[0]);
    let p = retired(&repo, "audit-race");
    let _control = bind(&roots[1], &repo);
    let journal = Journal::open(&roots[2].0.join("journal"), AuditLimits::default());
    let request = Request::Deletion(batch(&repo, std::slice::from_ref(&p), "delete-race"));
    let result =
        repo.audited_publication_maintenance(&journal.handle, &request, TIMEOUT, &mut |_| {
            let selected = batch(&repo, std::slice::from_ref(&p), "concurrent-pin");
            let Request::Retention(pin) = retention(selected, PublicationRetentionAction::Pin)
            else {
                unreachable!()
            };
            repo.change_publication_retention(&pin, TIMEOUT, &mut |_| Ok(()))?;
            Ok(())
        });
    assert!(result.result.is_err());
    assert!(repo.publication_catalog_entry(&p).unwrap().is_some());
    let records = journal.records();
    assert_eq!(records.len(), 2);
    let AuditRecordData::Outcome { conclusion, .. } = &records[1].data else {
        panic!("outcome")
    };
    assert_eq!(conclusion.result, AuditOperationResult::Unknown);
    assert_eq!(result.audit.status, ReleaseAuditStatus::OutcomeUnknown);
}
fn copy_quiescent_files(source: &Path, target: &Path) {
    // The test owns a fully acknowledged attempt and performs no journal I/O
    // while capturing this crash image. This is not a supported live backup API.
    fs::create_dir_all(target).unwrap();
    fs::set_permissions(target, fs::metadata(source).unwrap().permissions()).unwrap();
    for entry in fs::read_dir(source).unwrap() {
        let e = entry.unwrap();
        if e.file_type().unwrap().is_dir() {
            copy_quiescent_files(&e.path(), &target.join(e.file_name()));
        } else {
            fs::copy(e.path(), target.join(e.file_name())).unwrap();
        }
    }
}
#[test]
fn audited_native_recovery_matches_original_receipt_and_generic_owner_cannot_consume_it() {
    let roots = [
        TempRoot::new(),
        TempRoot::new(),
        TempRoot::new(),
        TempRoot::new(),
    ];
    let repo = artifacts(&roots[0]);
    let p = retired(&repo, "audit-recovery");
    let _control = bind(&roots[1], &repo);
    let path = roots[2].0.join("journal");
    let journal = Journal::open(&path, AuditLimits::default());
    let deletion = batch(&repo, std::slice::from_ref(&p), "delete-recovery");
    let mut guard = PublicationAuditGuard::new(&journal.handle);
    let result = repo
        .tombstone_publications(&deletion, TIMEOUT, &mut |v| {
            guard.preview(
                &Request::Deletion(deletion.clone()),
                &ResultValue {
                    receipt: Receipt::Deletion(v.receipt.clone()),
                    replay: v.replay,
                },
            )
        })
        .unwrap();
    assert!(!result.replay);
    let restored = roots[3].0.join("journal");
    copy_quiescent_files(&path, &restored);
    assert_eq!(guard.finish(&repo).status, ReleaseAuditStatus::Durable);
    let recovery = Journal::open(&restored, AuditLimits::default());
    let before = bytes(&roots[0].0);
    assert!(run(latent_artifacts::reconcile_release_audit(
        &recovery.handle,
        repo.as_ref()
    ))
    .is_err());
    run(reconcile_publication_maintenance_audit(
        &recovery.handle,
        &repo,
    ))
    .unwrap();
    assert_eq!(before, bytes(&roots[0].0));
    let records = recovery.records();
    let AuditRecordData::Outcome { conclusion, .. } = &records[1].data else {
        panic!("outcome")
    };
    assert_eq!(conclusion.result, AuditOperationResult::Committed);
    hidden(&repo, &p);
}
#[test]
fn audited_native_missing_original_receipt_recovers_unknown_without_creating_tombstone() {
    let roots = [
        TempRoot::new(),
        TempRoot::new(),
        TempRoot::new(),
        TempRoot::new(),
    ];
    let repo = artifacts(&roots[0]);
    let p = retired(&repo, "audit-no-commit");
    let _control = bind(&roots[1], &repo);
    let path = roots[2].0.join("journal");
    let journal = Journal::open(&path, AuditLimits::default());
    let restored = roots[3].0.join("journal");
    let deletion = batch(&repo, std::slice::from_ref(&p), "delete-no-commit");
    let mut guard = PublicationAuditGuard::new(&journal.handle);
    let result = repo.tombstone_publications(&deletion, TIMEOUT, &mut |v| {
        guard.preview(
            &Request::Deletion(deletion.clone()),
            &ResultValue {
                receipt: Receipt::Deletion(v.receipt.clone()),
                replay: v.replay,
            },
        )?;
        copy_quiescent_files(&path, &restored);
        Err(PlatformError {
            code: PlatformErrorCode::Unavailable,
            message: "test-stop-before-mutation".into(),
            retryable: false,
            details: vec![],
        })
    });
    assert!(result.is_err());
    guard.finish(&repo);
    let recovery = Journal::open(&restored, AuditLimits::default());
    let before = bytes(&roots[0].0);
    run(reconcile_publication_maintenance_audit(
        &recovery.handle,
        &repo,
    ))
    .unwrap();
    assert_eq!(before, bytes(&roots[0].0));
    let records = recovery.records();
    let AuditRecordData::Outcome { conclusion, .. } = &records[1].data else {
        panic!("outcome")
    };
    assert_eq!(conclusion.result, AuditOperationResult::Unknown);
    assert!(repo.publication_catalog_entry(&p).unwrap().is_some());
}
#[test]
fn audited_native_interrupted_unlink_keeps_original_query_and_audit_outcome_separate() {
    let roots = [TempRoot::new(), TempRoot::new(), TempRoot::new()];
    let repo = artifacts(&roots[0]);
    let p = retired(&repo, "audit-unlink");
    let control = bind(&roots[1], &repo);
    let journal = Journal::open(&roots[2].0.join("journal"), AuditLimits::default());
    let deletion = batch(&repo, std::slice::from_ref(&p), "delete-unlink");
    audited(&repo, &journal, &Request::Deletion(deletion.clone()));
    let assessment = repo
        .inspect_publication_reclamation(
            &deletion,
            PublicationReclamationLimits::default(),
            TIMEOUT,
        )
        .unwrap();
    let request = Request::Reclamation(PublicationReclamationRequest {
        deletion: deletion.clone(),
        expected_catalog_fence: assessment.catalog_fence,
        limits: PublicationReclamationLimits::default(),
    });
    repo.inject_retention_fault_for_test(DevelopmentRetentionFault::AfterPublicationFileUnlink);
    let outcome =
        repo.audited_publication_maintenance(&journal.handle, &request, TIMEOUT, &mut |_| Ok(()));
    assert!(outcome.result.is_err());
    assert_eq!(outcome.audit.status, ReleaseAuditStatus::OutcomeUnknown);
    drop(control);
    drop(repo);
    let repo = artifacts(&roots[0]);
    let _control = bind(&roots[1], &repo);
    assert!(matches!(
        repo.publication_reclamation_operation(&deletion.scope, &deletion.operation_id)
            .unwrap(),
        latent_artifacts::PublicationReclamationLookup::Found(_)
    ));
    assert_eq!(
        repo.publication_capacity_snapshot()
            .unwrap()
            .release_directories,
        0
    );
    let before = bytes(&roots[0].0);
    run(reconcile_publication_maintenance_audit(
        &journal.handle,
        &repo,
    ))
    .unwrap();
    assert_eq!(before, bytes(&roots[0].0));
    let records = journal.records();
    let AuditRecordData::Outcome { conclusion, .. } = &records[3].data else {
        panic!("outcome")
    };
    assert_eq!(conclusion.result, AuditOperationResult::Unknown);
}
