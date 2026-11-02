//! Authenticated tonic calls over real native publication, control and audit owners.
use super::support::{publish_variant, request, Harness};
use latent_artifacts::{
    LifecycleScope, PublicationRef, ReleaseActor, ReleaseActorKind, ReleaseLifecycleAction,
    ReleaseLifecycleReason, ReleaseMutationContext, ReleaseOperationPrecondition,
};
use latent_audit::{AuditHandle, AuditLimits, AuditWorker, DirectoryPhase2AuditJournal};
use latent_core::TenantId;
use latent_wire::management::{proto, ManagementLimits};
use std::time::{Duration, Instant};
use tonic::Code;
struct Journal {
    handle: AuditHandle,
    worker: AuditWorker,
    _root: tempfile::TempDir,
}
impl Journal {
    fn new(records: usize) -> Self {
        let root = tempfile::tempdir().unwrap();
        let (handle, worker) = DirectoryPhase2AuditJournal::open(
            root.path().join("audit"),
            AuditLimits {
                maximum_records: records,
                ..AuditLimits::default()
            },
        )
        .unwrap();
        Self {
            handle,
            worker,
            _root: root,
        }
    }
}
impl Drop for Journal {
    fn drop(&mut self) {
        self.handle.close();
        let stopped = self
            .worker
            .join_until(Instant::now() + Duration::from_secs(5));
        if !std::thread::panicking() {
            assert!(stopped.unwrap());
        }
    }
}
async fn retired(h: &Harness, name: &str) -> proto::PublicationRef {
    let (p, _) = publish_variant(h, "acme", name).await;
    let publication = PublicationRef {
        scope: LifecycleScope::Tenant(TenantId("acme".into())),
        id: p.id.parse().unwrap(),
    };
    h.artifacts
        .change_publication_lifecycle(
            ReleaseMutationContext {
                scope: publication.scope.clone(),
                actor: ReleaseActor {
                    subject: "fixture".into(),
                    kind: ReleaseActorKind::Host,
                },
                operation: Some(ReleaseOperationPrecondition {
                    operation_id: format!("retire-{name}"),
                    expected_generation: 1,
                }),
            },
            &publication,
            ReleaseLifecycleAction::Retire,
            ReleaseLifecycleReason::OperatorRetirement,
            &mut |_| Ok(()),
        )
        .unwrap();
    p
}
async fn selected(
    h: &Harness,
    p: &proto::PublicationRef,
    id: &str,
) -> proto::PublicationMaintenanceSelection {
    let v = h
        .releases_client()
        .get_publication_retention(request(
            "alice",
            proto::GetPublicationRetentionRequest {
                publications: vec![p.clone()],
                maximum_wait_millis: 1000,
            },
        ))
        .await
        .unwrap()
        .into_inner();
    assert_eq!(v.tenant, "acme");
    assert_eq!(v.catalog_fence.len(), 32);
    assert_eq!(v.entries.len(), 1);
    proto::PublicationMaintenanceSelection {
        operation_id: id.into(),
        catalog_fence: v.catalog_fence,
        targets: v.entries.into_iter().map(|v| v.target.unwrap()).collect(),
    }
}
fn mutation(
    kind: proto::PublicationMaintenanceKind,
    selection: proto::PublicationMaintenanceSelection,
) -> proto::MaintainPublicationsRequest {
    proto::MaintainPublicationsRequest {
        command: Some(proto::PublicationMaintenanceCommand {
            kind: kind as i32,
            selection: Some(selection),
            ..Default::default()
        }),
        maximum_wait_millis: 1000,
    }
}
fn ack(v: &tonic::Response<proto::MaintainPublicationsResponse>) {
    assert_eq!(v.metadata().get("latent-audit-status").unwrap(), "durable");
    let a = v.get_ref().audit_ack.as_ref().unwrap();
    assert_eq!(a.status, proto::AuditAckStatus::Durable as i32);
    assert!(a.attempt_sequence.is_some());
}
#[tokio::test]
async fn authenticated_publication_operator_pin_delete_reclaim_replay_and_lookup() {
    use proto::PublicationMaintenanceKind as K;
    let journal = Journal::new(128);
    let h = Harness::with_publication_maintenance(
        ManagementLimits::default(),
        Some(journal.handle.clone()),
    )
    .await;
    let p = retired(&h, "operator").await;
    let mut client = h.releases_client();
    let pin = mutation(K::Pin, selected(&h, &p, "pin").await);
    let v = client
        .maintain_publications(request("alice", pin))
        .await
        .unwrap();
    ack(&v);
    assert_eq!(
        v.get_ref()
            .receipt
            .as_ref()
            .unwrap()
            .actor
            .as_ref()
            .unwrap()
            .subject,
        "alice"
    );
    let delete = mutation(K::Delete, selected(&h, &p, "pinned-delete").await);
    assert!(client
        .maintain_publications(request("alice", delete))
        .await
        .is_err());
    let unpin = mutation(K::Unpin, selected(&h, &p, "unpin").await);
    ack(&client
        .maintain_publications(request("alice", unpin))
        .await
        .unwrap());
    let selection = selected(&h, &p, "delete").await;
    let delete = mutation(K::Delete, selection.clone());
    let v = client
        .maintain_publications(request("alice", delete.clone()))
        .await
        .unwrap();
    ack(&v);
    assert!(v.get_ref().receipt.as_ref().unwrap().reclaimed.is_none());
    let v = client
        .maintain_publications(request("alice", delete))
        .await
        .unwrap();
    ack(&v);
    assert!(v.get_ref().replay);
    let assessment = client
        .assess_publication_reclamation(request(
            "alice",
            proto::AssessPublicationReclamationRequest {
                deletion: Some(selection.clone()),
                maximum_files: 1024,
                maximum_bytes_hashed: 67108864,
                maximum_wait_millis: 1000,
            },
        ))
        .await
        .unwrap()
        .into_inner();
    assert!(
        assessment
            .potential
            .as_ref()
            .unwrap()
            .publication_file_bytes
            > 0
    );
    let cleanup = proto::MaintainPublicationsRequest {
        command: Some(proto::PublicationMaintenanceCommand {
            kind: K::Reclaim as i32,
            selection: Some(selection.clone()),
            reclamation_catalog_fence: assessment.catalog_fence,
            maximum_files: 1024,
            maximum_bytes_hashed: 67108864,
        }),
        maximum_wait_millis: 1000,
    };
    let v = client
        .maintain_publications(request("alice", cleanup.clone()))
        .await
        .unwrap();
    ack(&v);
    let receipt = v.into_inner().receipt.unwrap();
    assert!(receipt.reclaimed.as_ref().unwrap().publication_file_bytes > 0);
    assert_eq!(
        h.artifacts
            .publication_capacity_snapshot()
            .unwrap()
            .release_directories,
        0
    );
    let v = client
        .maintain_publications(request("alice", cleanup))
        .await
        .unwrap();
    ack(&v);
    assert!(v.get_ref().replay);
    assert_eq!(v.get_ref().receipt.as_ref(), Some(&receipt));
    let found = client
        .get_publication_maintenance_operation(request(
            "alice",
            proto::GetPublicationMaintenanceOperationRequest {
                kind: K::Reclaim as i32,
                operation_id: "delete".into(),
            },
        ))
        .await
        .unwrap()
        .into_inner();
    assert_eq!(found.receipt, Some(receipt));
    for (identity, kind, id) in [
        ("bob", K::Reclaim, "delete"),
        ("alice", K::Unpin, "pin"),
        ("alice", K::Delete, "missing"),
    ] {
        let v = client
            .get_publication_maintenance_operation(request(
                identity,
                proto::GetPublicationMaintenanceOperationRequest {
                    kind: kind as i32,
                    operation_id: id.into(),
                },
            ))
            .await
            .unwrap()
            .into_inner();
        assert_eq!(
            v.disposition,
            proto::ReleaseOperationLookupDisposition::Unknown as i32
        );
        assert!(v.receipt.is_none());
    }
    drop(client);
    h.shutdown().await;
}
#[tokio::test]
async fn authenticated_publication_operator_requires_audit_and_does_not_leak_foreign_selection() {
    let h = Harness::with_publication_maintenance(ManagementLimits::default(), None).await;
    let p = retired(&h, "no-audit").await;
    let mut client = h.releases_client();
    let selection = selected(&h, &p, "delete").await;
    let delete = mutation(proto::PublicationMaintenanceKind::Delete, selection);
    assert_eq!(
        client
            .maintain_publications(request("alice", delete.clone()))
            .await
            .unwrap_err()
            .code(),
        Code::FailedPrecondition
    );
    assert_eq!(
        client
            .maintain_publications(request("caller", delete.clone()))
            .await
            .unwrap_err()
            .code(),
        Code::PermissionDenied
    );
    assert_eq!(
        client
            .maintain_publications(tonic::Request::new(delete.clone()))
            .await
            .unwrap_err()
            .code(),
        Code::Unauthenticated
    );
    assert_eq!(
        client
            .maintain_publications(request("bob", delete))
            .await
            .unwrap_err()
            .code(),
        Code::InvalidArgument
    );
    let v = client
        .get_publication_retention(request(
            "alice",
            proto::GetPublicationRetentionRequest {
                publications: vec![p],
                maximum_wait_millis: 1000,
            },
        ))
        .await
        .unwrap();
    assert_eq!(v.get_ref().entries.len(), 1);
    drop(client);
    h.shutdown().await;
}
#[tokio::test]
async fn authenticated_publication_operator_full_audit_prevents_deletion_and_replay() {
    let journal = Journal::new(2);
    let h = Harness::with_publication_maintenance(
        ManagementLimits::default(),
        Some(journal.handle.clone()),
    )
    .await;
    let p = retired(&h, "audit-full").await;
    let mut client = h.releases_client();
    let pin = mutation(
        proto::PublicationMaintenanceKind::Pin,
        selected(&h, &p, "pin").await,
    );
    ack(&client
        .maintain_publications(request("alice", pin.clone()))
        .await
        .unwrap());
    let capacity = h.artifacts.publication_capacity_snapshot().unwrap();
    let before = journal.handle.snapshot().retained_records;
    assert_eq!(
        client
            .maintain_publications(request("alice", pin))
            .await
            .unwrap_err()
            .code(),
        Code::ResourceExhausted
    );
    let unpin = mutation(
        proto::PublicationMaintenanceKind::Unpin,
        selected(&h, &p, "unpin").await,
    );
    assert_eq!(
        client
            .maintain_publications(request("alice", unpin))
            .await
            .unwrap_err()
            .code(),
        Code::ResourceExhausted
    );
    assert_eq!(
        capacity,
        h.artifacts.publication_capacity_snapshot().unwrap()
    );
    assert_eq!(before, journal.handle.snapshot().retained_records);
    drop(client);
    h.shutdown().await;
}
#[tokio::test]
async fn authenticated_publication_operator_refuses_changed_fence_and_empty_or_oversized_batch() {
    let journal = Journal::new(128);
    let h = Harness::with_publication_maintenance(
        ManagementLimits::default(),
        Some(journal.handle.clone()),
    )
    .await;
    let p = retired(&h, "operator-bounds").await;
    let mut client = h.releases_client();
    let valid = selected(&h, &p, "delete").await;
    let before = journal.handle.snapshot().retained_records;
    let mut variants = Vec::new();
    let mut v = valid.clone();
    v.targets.clear();
    variants.push(v);
    let mut v = valid.clone();
    v.targets = vec![v.targets[0].clone(); 33];
    variants.push(v);
    let mut v = valid.clone();
    v.targets[0].expected_generation = 0;
    variants.push(v);
    let mut v = valid.clone();
    v.catalog_fence.pop();
    variants.push(v);
    let mut v = valid;
    v.catalog_fence[0] ^= 1;
    variants.push(v);
    for v in variants {
        assert!(client
            .maintain_publications(request(
                "alice",
                mutation(proto::PublicationMaintenanceKind::Delete, v)
            ))
            .await
            .is_err());
    }
    assert_eq!(before, journal.handle.snapshot().retained_records);
    assert_eq!(
        h.artifacts
            .publication_capacity_snapshot()
            .unwrap()
            .release_directories,
        1
    );
    drop(client);
    h.shutdown().await;
}
#[tokio::test]
async fn authenticated_publication_operator_small_response_budget_has_no_audit_or_catalog_mutation()
{
    let journal = Journal::new(128);
    let h = Harness::with_publication_maintenance(
        ManagementLimits {
            max_response_bytes: 512,
            max_metadata_bytes: 512,
            max_string_bytes: 512,
            max_page_token_bytes: 512,
            max_collection_entries: 512,
            max_route_services: 512,
            max_route_revisions: 512,
            ..ManagementLimits::default()
        },
        Some(journal.handle.clone()),
    )
    .await;
    let p = retired(&h, "operator-response").await;
    let reference = PublicationRef {
        scope: LifecycleScope::Tenant(TenantId("acme".into())),
        id: p.id.parse().unwrap(),
    };
    let snapshot = h
        .artifacts
        .publication_retention_snapshot(
            &reference.scope,
            std::slice::from_ref(&reference),
            Duration::from_secs(1),
        )
        .unwrap();
    let selected = proto::PublicationMaintenanceSelection {
        operation_id: "operation".into(),
        catalog_fence: snapshot.catalog_fence.as_bytes().to_vec(),
        targets: vec![proto::PublicationMaintenanceTarget {
            publication: Some(p),
            expected_generation: 2,
        }],
    };
    let before = h.artifacts.publication_capacity_snapshot().unwrap();
    let result = h
        .releases_client()
        .maintain_publications(request(
            "alice",
            mutation(proto::PublicationMaintenanceKind::Delete, selected),
        ))
        .await;
    assert_eq!(result.unwrap_err().code(), Code::ResourceExhausted);
    assert_eq!(journal.handle.snapshot().retained_records, 0);
    assert_eq!(before, h.artifacts.publication_capacity_snapshot().unwrap());
    h.shutdown().await;
}
