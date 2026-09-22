use super::*;
use latent_audit::{AuditHandle, AuditOperationResult, AuditRecordData};
use latent_control_store::http_routes::{
    TriggerOperationContext, TriggerOperationLookup, TriggerOperationRequest, TriggerTargetIdentity,
};
use latent_core::{PlatformErrorCode, TriggerId};
use latent_rollout::trigger_audit::{reconcile_trigger_audit, ManagedTriggerAudit};
use std::os::unix::fs::PermissionsExt;

fn expires() -> Instant {
    Instant::now() + Duration::from_secs(5)
}

async fn prepare(h: &Harness) -> TriggerOperationRequest {
    let input = setup(h).await;
    client(h)
        .apply_trigger(request("alice", input))
        .await
        .unwrap();
    let current = h
        .deployments
        .get_trigger(&TenantId("acme".into()), &TriggerId("browser".into()))
        .unwrap();
    let row = current.value().trigger.as_ref().unwrap();
    TriggerOperationRequest::Apply {
        context: TriggerOperationContext {
            tenant: TenantId("acme".into()),
            actor: ReleaseActor {
                subject: "alice".into(),
                kind: ReleaseActorKind::Host,
            },
            operation_id: "native-update".into(),
            expected_state_version: current.value().state_version,
        },
        manifest: row.manifest.clone(),
        expected_generation: row.generation,
    }
}

async fn terminal_rows(audit: &AuditHandle) -> Vec<latent_audit::AuditStoredRecord> {
    let deadline = expires();
    while audit.snapshot().pending_attempts != 0 {
        assert!(Instant::now() < deadline);
        tokio::time::sleep(Duration::from_millis(1)).await;
    }
    loop {
        match audit.query(
            latent_audit::AuditQueryRequest {
                scope: latent_audit::AuditScope::Tenant(TenantId("acme".into())),
                filter: latent_audit::AuditFilter::default(),
                cursor: None,
                limit: 32,
                maximum_bytes: 32768,
            },
            deadline,
        ) {
            Ok(ticket) => return ticket.wait().await.unwrap().records().to_vec(),
            Err(e) if e.message == "audit-busy" && Instant::now() < deadline => {
                tokio::task::yield_now().await;
            }
            Err(e) => panic!("audit query: {e:?}"),
        }
    }
}

#[tokio::test]
async fn trigger_audit_expiry_caller_loss_and_identity_mismatch_never_claim_false_success() {
    let dir = TempDir::new().unwrap();
    let (audit, mut journal) =
        DirectoryPhase2AuditJournal::open(dir.path().join("audit"), AuditLimits::default())
            .unwrap();
    let h = Harness::with_audit(ManagementLimits::default(), None, Some(audit.clone())).await;
    let command = prepare(&h).await;
    let prepared = h
        .deployments
        .prepare_trigger_operation(command.clone())
        .unwrap();
    let mut guard = ManagedTriggerAudit::begin(&audit, prepared.preview(), false, expires())
        .await
        .unwrap();
    assert_eq!(
        guard
            .commit(&h.deployments, prepared, Instant::now())
            .err()
            .unwrap()
            .code,
        PlatformErrorCode::DeadlineExceeded
    );
    drop(guard);
    assert!(terminal_rows(&audit).await.iter().any(|r| matches!(&r.data, AuditRecordData::Outcome {conclusion, ..} if conclusion.result == AuditOperationResult::NotStarted)));
    let prepared = h.deployments.prepare_trigger_operation(command).unwrap();
    let mut guard = ManagedTriggerAudit::begin(&audit, prepared.preview(), false, expires())
        .await
        .unwrap();
    let result = guard.commit(&h.deployments, prepared, expires()).unwrap();
    assert!(guard.matches(result.value()));
    let copy_result = || latent_control_store::http_routes::TriggerOperationCommit {
        receipt: result.value().receipt.clone(),
        trigger: None,
        replayed: result.value().replayed,
        durability: Ok(()),
    };
    for altered in [
        {
            let mut r = copy_result();
            r.receipt.actor.subject = "another-actor".into();
            r
        },
        {
            let mut r = copy_result();
            r.receipt.expected_state_version = 0;
            r
        },
        {
            let mut r = copy_result();
            let Some(TriggerTargetIdentity::Application {
                deployment_generation,
                ..
            }) = r.receipt.target.as_mut()
            else {
                panic!("application target")
            };
            *deployment_generation += 1;
            r
        },
        {
            let mut r = copy_result();
            r.replayed = true;
            r
        },
    ] {
        assert!(!guard.matches(&altered));
    }
    drop(guard);
    assert!(terminal_rows(&audit).await.iter().any(|r| matches!(&r.data, AuditRecordData::Outcome {conclusion, ..} if conclusion.result == AuditOperationResult::Unknown)));
    assert_eq!(
        h.deployments
            .get_trigger_operation(&TenantId("acme".into()), "native-update")
            .unwrap()
            .value(),
        &TriggerOperationLookup::Found(result.value().receipt.clone())
    );
    reconcile_trigger_audit(&audit, &h.deployments, expires())
        .await
        .unwrap();
    assert_eq!(audit.snapshot().unknown_outcomes, 1);
    drop(result);
    h.shutdown().await;
    audit.close();
    assert!(journal.join_until(expires()).unwrap());
}

fn snapshot(from: &std::path::Path, to: &std::path::Path) {
    std::fs::create_dir(to).unwrap();
    std::fs::set_permissions(to, std::fs::Permissions::from_mode(0o700)).unwrap();
    std::fs::create_dir(to.join("records")).unwrap();
    std::fs::set_permissions(to.join("records"), std::fs::Permissions::from_mode(0o700)).unwrap();
    for name in ["MODE", "HEAD"] {
        std::fs::copy(from.join(name), to.join(name)).unwrap();
    }
    let rows: Vec<_> = std::fs::read_dir(from.join("records")).unwrap().collect();
    assert!(rows.len() <= 8);
    for row in rows {
        let row = row.unwrap();
        assert!(row.file_type().unwrap().is_file());
        std::fs::copy(row.path(), to.join("records").join(row.file_name())).unwrap();
    }
}

#[tokio::test]
async fn trigger_audit_recovery_requires_an_exact_committed_receipt() {
    for committed in [false, true] {
        let dir = TempDir::new().unwrap();
        let (audit, mut journal) =
            DirectoryPhase2AuditJournal::open(dir.path().join("audit"), AuditLimits::default())
                .unwrap();
        let h = Harness::with_audit(ManagementLimits::default(), None, Some(audit.clone())).await;
        let command = prepare(&h).await;
        let prepared = h.deployments.prepare_trigger_operation(command).unwrap();
        let mut guard = ManagedTriggerAudit::begin(&audit, prepared.preview(), false, expires())
            .await
            .unwrap();
        if committed {
            guard.commit(&h.deployments, prepared, expires()).unwrap();
        } else {
            drop(prepared);
        }
        // Copy acknowledged files while the attempt still has no terminal row:
        // recovery observes the same durable boundary as process loss.
        snapshot(&dir.path().join("audit"), &dir.path().join("recovered"));
        drop(guard);
        audit.close();
        assert!(journal.join_until(expires()).unwrap());
        let (recovered, mut worker) =
            DirectoryPhase2AuditJournal::open(dir.path().join("recovered"), AuditLimits::default())
                .unwrap();
        reconcile_trigger_audit(&recovered, &h.deployments, expires())
            .await
            .unwrap();
        assert_eq!(recovered.snapshot().pending_attempts, 0);
        assert_eq!(recovered.snapshot().unknown_outcomes, u64::from(!committed));
        let rows = terminal_rows(&recovered).await;
        assert!(rows.iter().any(|r| matches!(&r.data, AuditRecordData::Outcome {conclusion, ..} if conclusion.identities.state_version == Some(3) && conclusion.result == if committed {AuditOperationResult::Committed} else {AuditOperationResult::Unknown})));
        recovered.close();
        assert!(worker.join_until(expires()).unwrap());
        h.shutdown().await;
    }
}
